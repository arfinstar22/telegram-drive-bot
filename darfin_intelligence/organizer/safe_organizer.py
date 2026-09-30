"""Safe Smart Organizer Service (Task 2C).

Implements:
- OrganizationPlan creation (pure memory calculation, dry-run by default)
- Safety thresholds & sensitive category protection (no auto-moves for identity, health, legal, finance)
- Preview & user approval workflows
- Recheck verification (ownership, existence, trash, destination validity, stale plan detection)
- Cross-user attack resistance and isolated batch move reporting
- Audit logging without leaking credentials or tokens
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import database as db
from darfin_intelligence.analyzer import analyze
from darfin_intelligence.classifier import classify
from darfin_intelligence.classifier.models import ClassificationResult
from darfin_intelligence.organizer.folder_matcher import build_folder_index
from darfin_intelligence.organizer.folder_mapper import map_folder
from darfin_intelligence.organizer.models import (
    OrganizationItem,
    OrganizationPlan,
    _now_iso,
)

log = logging.getLogger(__name__)
audit_log = logging.getLogger("darfin_intelligence.organizer.audit")

# ── Configuration Constants ─────────────────────────────────────

# Safe default: AUTO_ORGANIZE_ENABLED is False (Sections 2, 17, 23)
DEFAULT_AUTO_ORGANIZE_ENABLED: bool = False

# High confidence threshold for auto-organize eligibility (Section 18)
DEFAULT_AUTO_ORGANIZE_MIN_CONFIDENCE: float = 0.95

# Minimum confidence required for suggestions; below this requires manual review (Section 15)
DEFAULT_SUGGESTION_MIN_CONFIDENCE: float = 0.50

# Sensitive domains: NEVER auto-move, always require explicit user review (Section 19)
SENSITIVE_DOMAINS: frozenset[str] = frozenset({
    "identity",
    "health",
    "legal",
    "finance",
})

# In-memory audit log store for testing and telemetry
_AUDIT_LOG_RECORDS: list[dict[str, Any]] = []


# ── Audit Logging Helper ────────────────────────────────────────

def record_audit(
    user_id: int,
    file_id: int,
    filename: str,
    source_folder_id: int | None,
    target_folder_id: int,
    confidence: float,
    reasons: list[str],
) -> dict[str, Any]:
    """Record an audit trail entry for a file move without leaking secrets."""
    entry = {
        "timestamp": _now_iso(),
        "user_id": user_id,
        "file_id": file_id,
        "filename": filename,
        "source_folder_id": source_folder_id,
        "target_folder_id": target_folder_id,
        "confidence": round(confidence, 2),
        "reasons": reasons,
    }
    _AUDIT_LOG_RECORDS.append(entry)
    audit_log.info(
        "ORGANIZER_MOVE: user=%s file_id=%s ('%s') %s -> %s (conf=%.2f)",
        user_id,
        file_id,
        filename,
        source_folder_id,
        target_folder_id,
        confidence,
    )
    return entry


def get_audit_records(user_id: int | None = None) -> list[dict[str, Any]]:
    """Retrieve audit records, optionally filtered by user_id."""
    if user_id is None:
        return list(_AUDIT_LOG_RECORDS)
    return [r for r in _AUDIT_LOG_RECORDS if r.get("user_id") == user_id]


def clear_audit_records() -> None:
    """Clear in-memory audit records (useful for test resets)."""
    _AUDIT_LOG_RECORDS.clear()


# ── SafeOrganizer Service ────────────────────────────────────────

class SafeOrganizer:
    """Safe smart organizer for generating plans and executing verified moves."""

    @staticmethod
    def create_plan(
        files: list[dict[str, Any]],
        folders: list[dict[str, Any]] | dict[str, Any],
        auto_organize_enabled: bool = DEFAULT_AUTO_ORGANIZE_ENABLED,
        min_confidence: float = DEFAULT_AUTO_ORGANIZE_MIN_CONFIDENCE,
        dry_run: bool = True,
        user_id: int | None = None,
        user_preferences: list[Any] | None = None,
    ) -> OrganizationPlan:
        """Generate an OrganizationPlan for the given files and user folders.

        This is a pure in-memory calculation:
        - Never writes to the database.
        - Never moves or alters files.
        - Respects user folder reuse and hierarchy.
        """
        # Build index once for fast lookups across all files
        if isinstance(folders, dict) and "path_by_id" in folders:
            folder_index = folders
        else:
            folder_index = build_folder_index(folders if isinstance(folders, list) else [])

        items: list[OrganizationItem] = []
        path_by_id = folder_index.get("path_by_id", {})
        folder_by_id = folder_index.get("folder_by_id", {})

        for f in files:
            file_id = f.get("id") or f.get("file_id") or 0
            filename = f.get("file_name") or f.get("filename") or ""
            source_folder_id = f.get("folder_id")
            source_path = path_by_id.get(source_folder_id) if source_folder_id is not None else None
            is_trashed = bool(f.get("is_trashed") or f.get("trashed", False))

            stale_fingerprint = {
                "file_id": file_id,
                "source_folder_id": source_folder_id,
                "updated_at": f.get("updated_at"),
            }

            # 1. Trash protection (Section 13)
            if is_trashed:
                items.append(OrganizationItem(
                    file_id=file_id,
                    filename=filename,
                    source_folder_id=source_folder_id,
                    source_path=source_path,
                    target_folder_id=None,
                    target_folder_name=None,
                    target_path=None,
                    confidence=0.0,
                    decision="skip",
                    status="in_trash",
                    reasons=["File is in trash; skipping auto-organization"],
                    stale_fingerprint=stale_fingerprint,
                ))
                continue

            # 2. Extract classification or classify on the fly
            classification = f.get("classification")
            if not isinstance(classification, ClassificationResult):
                intel = f.get("intelligence")
                if not intel:
                    intel = analyze(filename)
                classification = classify(intel)

            # 3. Map folder using Task 2B
            suggestion = map_folder(classification, folder_index)

            # 3b. Apply user preferences if provided (Task 2D)
            if user_preferences:
                from darfin_intelligence.preferences.engine import apply_preferences
                suggestion = apply_preferences(
                    suggestion=suggestion,
                    preferences=user_preferences,
                    file_family=getattr(classification, "family", getattr(classification, "file_family", "other")),
                    filename=filename,
                    current_folders=folders if isinstance(folders, list) else None,
                )

            target_id = suggestion.target_folder_id
            target_name = suggestion.target_folder_name
            target_path = suggestion.target_folder_path
            class_conf = getattr(classification, "confidence", 1.0)
            conf = round(suggestion.confidence * class_conf, 2)

            # 4. Evaluate decision and status
            if suggestion.status == "ambiguous":
                status = "ambiguous"
                decision = "review"
                reasons = ["Multiple candidate folders tied; manual selection required", *suggestion.reasons]
            elif suggestion.status == "no_match" or target_id is None:
                status = "no_match"
                decision = "skip"
                reasons = ["No matching destination folder found in user folders"]
            elif source_folder_id is not None and source_folder_id == target_id:
                status = "already_in_target"
                decision = "skip"
                reasons = [f"File is already in target folder '{target_name}'"]
            elif conf < DEFAULT_SUGGESTION_MIN_CONFIDENCE:
                status = "low_confidence"
                decision = "review"
                reasons = [
                    f"Confidence ({conf:.2f}) below threshold ({DEFAULT_SUGGESTION_MIN_CONFIDENCE:.2f}); manual review required",
                    *suggestion.reasons,
                ]
            elif classification.domain in SENSITIVE_DOMAINS:
                # Sensitive categories safety: NEVER auto-move (Section 19)
                status = "planned"
                decision = "suggest"
                reasons = [
                    f"Sensitive domain '{classification.domain}' requires explicit user confirmation",
                    *suggestion.reasons,
                ]
            elif auto_organize_enabled and conf >= min_confidence:
                # Auto-organize enabled and high confidence (Section 18)
                status = "planned"
                decision = "auto"
                reasons = [
                    f"High confidence ({conf:.2f}) exceeds auto-organize threshold ({min_confidence:.2f})",
                    *suggestion.reasons,
                ]
            else:
                # Standard suggestion (Section 17: default SUGGEST_ONLY)
                status = "planned"
                decision = "suggest"
                reasons = suggestion.reasons

            items.append(OrganizationItem(
                file_id=file_id,
                filename=filename,
                source_folder_id=source_folder_id,
                source_path=source_path,
                target_folder_id=target_id,
                target_folder_name=target_name,
                target_path=target_path,
                confidence=conf,
                decision=decision,
                status=status,
                domain=classification.domain,
                category=classification.category,
                family=getattr(classification, "family", getattr(classification, "file_family", "other")),
                reasons=reasons,
                stale_fingerprint=stale_fingerprint,
            ))

        # Calculate summary counts
        summary = {
            "total": len(items),
            "planned": sum(1 for it in items if it.status == "planned"),
            "auto": sum(1 for it in items if it.decision == "auto" and it.status == "planned"),
            "suggest": sum(1 for it in items if it.decision == "suggest" and it.status == "planned"),
            "review": sum(1 for it in items if it.decision == "review"),
            "skip": sum(1 for it in items if it.decision == "skip"),
            "already_in_target": sum(1 for it in items if it.status == "already_in_target"),
            "in_trash": sum(1 for it in items if it.status == "in_trash"),
            "no_match": sum(1 for it in items if it.status == "no_match"),
            "ambiguous": sum(1 for it in items if it.status == "ambiguous"),
            "low_confidence": sum(1 for it in items if it.status == "low_confidence"),
        }

        return OrganizationPlan(
            user_id=user_id,
            total_files=len(items),
            items=items,
            summary=summary,
            auto_organize_enabled=auto_organize_enabled,
            dry_run=dry_run,
        )

    @staticmethod
    def preview(
        files: list[dict[str, Any]],
        folders: list[dict[str, Any]] | dict[str, Any],
        user_id: int | None = None,
        user_preferences: list[Any] | None = None,
    ) -> OrganizationPlan:
        """Generate a dry-run preview plan for user review."""
        return SafeOrganizer.create_plan(
            files=files,
            folders=folders,
            auto_organize_enabled=False,
            dry_run=True,
            user_id=user_id,
            user_preferences=user_preferences,
        )

    @staticmethod
    def execute_item(
        item: OrganizationItem | dict[str, Any],
        user_id: int,
        get_file_fn: Callable[..., dict[str, Any] | None] | None = None,
        get_folder_fn: Callable[..., dict[str, Any] | None] | None = None,
        move_file_fn: Callable[..., bool] | None = None,
    ) -> dict[str, Any]:
        """Execute a single approved move with full security recheck.

        Rechecks:
        - Authenticated user
        - File existence and user ownership
        - File not in trash
        - Target folder existence and user ownership
        - Idempotency (already in target)
        - Stale plan detection (source folder has not changed)
        """
        if not user_id:
            return {
                "success": False,
                "status": "unauthorized",
                "error": "Authentication required",
                "file_id": item.file_id if isinstance(item, OrganizationItem) else item.get("file_id"),
            }

        # Resolve item properties
        if isinstance(item, OrganizationItem):
            file_id = item.file_id
            target_folder_id = item.target_folder_id
            source_folder_id = item.source_folder_id
            confidence = item.confidence
            reasons = item.reasons
        else:
            file_id = int(item.get("file_id", 0))
            target_folder_id = item.get("target_folder_id")
            source_folder_id = item.get("source_folder_id")
            confidence = float(item.get("confidence", 0.0))
            reasons = item.get("reasons", [])

        if not file_id or target_folder_id is None:
            return {
                "success": False,
                "status": "invalid_request",
                "error": "Missing file_id or target_folder_id",
                "file_id": file_id,
            }

        target_folder_id = int(target_folder_id)

        # Database adapters
        _get_file = get_file_fn or db.get_file
        _get_folder = get_folder_fn or db.get_folder
        _move_file = move_file_fn or db.move_file

        # 1. Recheck file existence and ownership
        f = _get_file(file_id, user_id=user_id)
        if not f or f.get("user_id") != user_id:
            return {
                "success": False,
                "status": "unauthorized",
                "error": "File not found or unauthorized",
                "file_id": file_id,
            }

        # 2. Recheck trash state
        if bool(f.get("is_trashed") or f.get("trashed")):
            return {
                "success": False,
                "status": "in_trash",
                "error": "File is in trash; cannot move",
                "file_id": file_id,
            }

        # 3. Recheck target folder existence and ownership
        dest = _get_folder(target_folder_id, user_id=user_id)
        if not dest or dest.get("user_id") != user_id:
            return {
                "success": False,
                "status": "unauthorized",
                "error": "Target folder not found or unauthorized",
                "file_id": file_id,
                "target_folder_id": target_folder_id,
            }

        # 4. Idempotency recheck (already in target folder)
        current_folder_id = f.get("folder_id")
        if current_folder_id == target_folder_id:
            return {
                "success": True,
                "status": "already_in_target",
                "message": "File is already in target folder",
                "file_id": file_id,
                "target_folder_id": target_folder_id,
                "folder_name": dest.get("name"),
            }

        # 5. Stale plan detection (source folder changed since plan creation)
        if source_folder_id is not None and current_folder_id != source_folder_id:
            return {
                "success": False,
                "status": "stale_plan",
                "error": f"Stale plan: file source folder changed from {source_folder_id} to {current_folder_id}",
                "file_id": file_id,
                "current_folder_id": current_folder_id,
                "expected_source_folder_id": source_folder_id,
            }

        # 6. Execute safe move
        moved = _move_file(file_id, target_folder_id, user_id=user_id)
        if moved:
            record_audit(
                user_id=user_id,
                file_id=file_id,
                filename=f.get("file_name", ""),
                source_folder_id=current_folder_id,
                target_folder_id=target_folder_id,
                confidence=confidence,
                reasons=reasons,
            )
            return {
                "success": True,
                "status": "executed",
                "file_id": file_id,
                "target_folder_id": target_folder_id,
                "folder_name": dest.get("name"),
            }

        return {
            "success": False,
            "status": "failed",
            "error": "Database move operation failed",
            "file_id": file_id,
        }

    @staticmethod
    def execute_batch(
        items: list[OrganizationItem | dict[str, Any]],
        user_id: int,
        get_file_fn: Callable[..., dict[str, Any] | None] | None = None,
        get_folder_fn: Callable[..., dict[str, Any] | None] | None = None,
        move_file_fn: Callable[..., bool] | None = None,
    ) -> dict[str, Any]:
        """Execute a batch of approved moves with partial result reporting.

        Returns:
            dict containing lists of 'success', 'failed', 'skipped', 'unauthorized',
            and boolean 'ok' (True only if zero failed and zero unauthorized).
        """
        success: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        unauthorized: list[dict[str, Any]] = []

        for it in items:
            res = SafeOrganizer.execute_item(
                item=it,
                user_id=user_id,
                get_file_fn=get_file_fn,
                get_folder_fn=get_folder_fn,
                move_file_fn=move_file_fn,
            )
            status = res.get("status")
            if status == "executed":
                success.append(res)
            elif status in ("already_in_target", "in_trash", "stale_plan"):
                skipped.append(res)
            elif status == "unauthorized":
                unauthorized.append(res)
            else:
                failed.append(res)

        ok = (len(failed) == 0 and len(unauthorized) == 0)
        return {
            "ok": ok,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "unauthorized": unauthorized,
            "summary": {
                "total": len(items),
                "moved": len(success),
                "skipped": len(skipped),
                "unauthorized": len(unauthorized),
                "failed": len(failed),
            },
        }


# Convenience functional interface
create_plan = SafeOrganizer.create_plan
preview = SafeOrganizer.preview
execute_item = SafeOrganizer.execute_item
execute_batch = SafeOrganizer.execute_batch
