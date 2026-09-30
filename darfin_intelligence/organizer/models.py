"""Data models for Smart Folder Mapping (Task 2B)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class FolderCandidate:
    """Ranked folder candidate with scoring breakdown."""
    folder_id: int
    name: str
    path: str
    score: int
    match_type: str = "generic"  # exact, alias, category, domain, token, contextual
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder_id": self.folder_id,
            "name": self.name,
            "path": self.path,
            "score": self.score,
            "match_type": self.match_type,
            "reasons": self.reasons,
        }


@dataclass
class FolderSuggestion:
    """Structured folder mapping suggestion for a file."""
    status: str = "no_match"  # "matched", "ambiguous", "no_match", "failed"
    target_folder_id: int | None = None
    target_folder_name: str | None = None
    target_folder_path: str | None = None
    confidence: float = 0.0
    candidates: list[FolderCandidate] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "target": {
                "id": self.target_folder_id,
                "name": self.target_folder_name,
                "path": self.target_folder_path,
            } if self.target_folder_id is not None else None,
            "confidence": self.confidence,
            "candidates": [c.to_dict() for c in self.candidates],
            "reasons": self.reasons,
        }
        if self.error:
            d["error"] = self.error
        return d

    def explain(self) -> str:
        """Produce human-readable explanation of folder recommendation."""
        lines = [
            f"Folder Suggestion Status: {self.status.upper()}",
            f"Target: {self.target_folder_path or 'None'} (id={self.target_folder_id}, confidence={self.confidence:.2f})",
            "",
            "Reasons:",
        ]
        for r in self.reasons:
            lines.append(f"  ✓ {r}")

        if self.candidates:
            lines.append("")
            lines.append("Ranked Candidates:")
            for i, c in enumerate(self.candidates[:5], 1):
                lines.append(f"  {i}. {c.path} (score={c.score}, match={c.match_type})")

        return "\n".join(lines)


import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OrganizationItem:
    """Single file planned reorganization item."""
    file_id: int
    filename: str
    source_folder_id: int | None = None
    source_path: str | None = None
    target_folder_id: int | None = None
    target_folder_name: str | None = None
    target_path: str | None = None
    confidence: float = 0.0
    decision: str = "review"  # "auto", "suggest", "review", "skip"
    status: str = "planned"   # "planned", "already_in_target", "no_match", "ambiguous", "in_trash", "low_confidence", "sensitive_review", "stale_plan", "unauthorized", "executed", "failed"
    domain: str | None = None
    category: str | None = None
    family: str | None = None
    reasons: list[str] = field(default_factory=list)
    stale_fingerprint: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "source_folder_id": self.source_folder_id,
            "source_path": self.source_path,
            "target_folder_id": self.target_folder_id,
            "target_folder_name": self.target_folder_name,
            "target_path": self.target_path,
            "confidence": round(self.confidence, 2),
            "decision": self.decision,
            "status": self.status,
            "domain": self.domain,
            "category": self.category,
            "family": self.family,
            "reasons": self.reasons,
            "stale_fingerprint": self.stale_fingerprint,
        }

    def explain(self) -> str:
        lines = [
            f"File: {self.filename} (id={self.file_id})",
            f"Target: {self.target_path or self.target_folder_name or 'None'} (id={self.target_folder_id})",
            f"Confidence: {self.confidence:.2f}",
            f"Decision: {self.decision.upper()} | Status: {self.status.upper()}",
            "",
            "Reasons:",
        ]
        for r in self.reasons:
            lines.append(f"  ✓ {r}")
        return "\n".join(lines)


@dataclass
class OrganizationPlan:
    """Batch reorganization plan across multiple files."""
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: int | None = None
    created_at: str = field(default_factory=_now_iso)
    total_files: int = 0
    items: list[OrganizationItem] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    auto_organize_enabled: bool = False
    dry_run: bool = True

    def get_eligible_items(self) -> list[OrganizationItem]:
        """Items ready for execution (status == 'planned')."""
        return [it for it in self.items if it.status == "planned"]

    def get_auto_items(self) -> list[OrganizationItem]:
        """Items marked for automatic execution."""
        return [it for it in self.items if it.status == "planned" and it.decision == "auto"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "total_files": self.total_files,
            "summary": self.summary,
            "auto_organize_enabled": self.auto_organize_enabled,
            "dry_run": self.dry_run,
            "items": [it.to_dict() for it in self.items],
        }

    def explain(self) -> str:
        lines = [
            f"Organization Plan: {self.plan_id}",
            f"Created At: {self.created_at}",
            f"Total Files: {self.total_files}",
            f"Auto-Organize Enabled: {self.auto_organize_enabled}",
            f"Dry Run: {self.dry_run}",
            f"Summary: {self.summary}",
            "",
            "Items:",
        ]
        for it in self.items:
            lines.append(f"  - [{it.decision.upper()}] {it.filename} -> {it.target_path or 'None'} ({it.status})")
        return "\n".join(lines)

