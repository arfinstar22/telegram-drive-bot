"""Smart Folder Mapper core execution module (Task 2B)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from darfin_intelligence.organizer.models import FolderCandidate, FolderSuggestion
from darfin_intelligence.organizer.folder_matcher import build_folder_index, score_folder

if TYPE_CHECKING:
    from darfin_intelligence.classifier.models import ClassificationResult


def map_folder(
    classification: ClassificationResult,
    folders: list[dict[str, Any]],
    context_tokens: list[str] | None = None,
) -> FolderSuggestion:
    """Map a file's ClassificationResult to the best matching user folder.

    Args:
        classification: ClassificationResult output from Task 2A.
        folders: List of folder dictionaries belonging to the user.
        context_tokens: Optional additional context tokens (e.g. course name).

    Returns:
        FolderSuggestion with target folder, confidence, candidates, and reasons.
        Pure in-memory calculation — never modifies files or database.
    """
    if not folders:
        return FolderSuggestion(
            status="no_match",
            reasons=["User does not have any folders created yet."],
        )

    domain = classification.domain
    category = classification.category
    family = classification.family

    # Auto-extract context tokens from filename if not explicitly provided
    if context_tokens is None:
        context_tokens = []
        if classification.filename:
            import re
            stem = classification.filename.rsplit(".", 1)[0]
            context_tokens = [tok for tok in re.split(r"[\s._\-\[\](){}]+", stem.lower()) if tok]
        if category:
            context_tokens.append(category.lower())

    # Index folders and compute hierarchy paths if not already pre-indexed
    if isinstance(folders, dict):
        folder_index = folders
    else:
        folder_index = build_folder_index(folders)

    # Score each unique folder
    candidates: list[FolderCandidate] = []
    seen_dedup: set[tuple[str, int | None]] = set()

    for fid, f in folder_index.items():
        # Prevent duplicate entries like 'Film', 'film', 'FILM' under the same parent
        dedup_key = (f["cleaned_name"], f.get("parent_id"))
        if dedup_key in seen_dedup:
            continue
        seen_dedup.add(dedup_key)

        score, match_type, reasons = score_folder(
            folder_entry=f,
            domain=domain,
            category=category,
            family=family,
            context_tokens=context_tokens,
        )

        if score > 0:
            candidates.append(FolderCandidate(
                folder_id=fid,
                name=f.get("name", ""),
                path=f.get("path", f.get("name", "")),
                score=score,
                match_type=match_type,
                reasons=reasons,
            ))

    # Stable deterministic tie-breaker sorting:
    # 1. Higher score first
    # 2. Exact match type priority
    # 3. Shorter path first (prefer cleaner root unless nested had higher score)
    # 4. Smaller folder_id first
    candidates.sort(
        key=lambda c: (
            -c.score,
            0 if "exact" in c.match_type else 1,
            len(c.path),
            c.folder_id,
        )
    )

    MIN_SCORE_THRESHOLD = 25

    # Filter viable candidates
    viable = [c for c in candidates if c.score >= MIN_SCORE_THRESHOLD]

    if not viable:
        # Determine why no match occurred
        reason = "No user folder matches the file's category or domain."
        if family == "video":
            reason = "No media or video folder found among user's folders."
        elif domain:
            reason = f"No user folder matches domain '{domain}' or category '{category}'."

        return FolderSuggestion(
            status="no_match",
            target_folder_id=None,
            candidates=candidates[:5],
            reasons=[reason],
        )

    top = viable[0]

    # Check for ambiguity among top candidates
    if len(viable) >= 2:
        second = viable[1]
        diff = top.score - second.score
        ratio = top.score / max(1, second.score)

        # If scores are virtually tied
        if diff <= 5 and ratio < 1.15:
            return FolderSuggestion(
                status="ambiguous",
                target_folder_id=None,
                target_folder_name=None,
                target_folder_path=None,
                confidence=round(top.score / (top.score + second.score), 2),
                candidates=viable[:5],
                reasons=[
                    f"Multiple folders closely match: '{top.name}' ({top.score}) vs '{second.name}' ({second.score})"
                ],
            )

    # Clear winner
    total_viable_scores = sum(c.score for c in viable)
    confidence = round(top.score / total_viable_scores, 2)
    if len(viable) == 1 or (len(viable) >= 2 and (top.score - viable[1].score) >= 20):
        confidence = max(confidence, 0.88)

    return FolderSuggestion(
        status="matched",
        target_folder_id=top.folder_id,
        target_folder_name=top.name,
        target_folder_path=top.path,
        confidence=confidence,
        candidates=viable[:5],
        reasons=top.reasons,
    )


class FolderMapper:
    """Class interface for Smart Folder Mapper."""

    @staticmethod
    def map_folder(
        classification: ClassificationResult,
        folders: list[dict[str, Any]],
        context_tokens: list[str] | None = None,
    ) -> FolderSuggestion:
        return map_folder(classification, folders, context_tokens)
