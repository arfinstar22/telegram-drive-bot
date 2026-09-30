"""Preference Engine for learning user folder habits (Task 2D).

Implements:
- Pattern normalization from filenames (extracts clean reusable tokens, rejects raw noise)
- Confidence scaling based on consistent positive/negative feedback
- Deterministic score boost (+10 for 1 choice, +20 for 3 choices, +30 for 5+ choices)
- Conflict resolution when preferences compete
- Stale folder detection & graceful fallback
- Strict technical safety invariant:
  ACTUAL FILE TYPE > TECHNICAL EVIDENCE > CLASSIFICATION > FOLDER MATCH > USER PREFERENCE
  Personal preferences NEVER override technical file family rules (e.g. Video is never Office).
- Zero self-modifying code, zero global dictionary mutation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from darfin_intelligence.organizer.models import FolderCandidate, FolderSuggestion
from darfin_intelligence.preferences.models import UserPreference, PreferenceBoost

log = logging.getLogger(__name__)

# Stopwords and noise tokens ignored during pattern extraction
NOISE_TOKENS: frozenset[str] = frozenset({
    "final", "revisi", "rev", "revisi1", "revisi2", "revisi3", "draft",
    "copy", "salinan", "baru", "new", "temp", "v1", "v2", "v3",
    "part", "pt", "cv", "desa", "bab", "tugas", "file", "berkas",
    "unduhan", "download", "scan", "document", "dokumen",
})

# Incompatible family-folder keywords to enforce Section 5 & 7 safety
INCOMPATIBLE_FOLDER_MAP: dict[str, set[str]] = {
    "video": {"office", "kantor", "dokumen kantor", "laporan", "pekerjaan", "surat"},
    "photo": {"film", "movie", "movies", "cinema", "bioskop"},
    "audio": {"film", "movie", "movies", "cinema", "office", "kantor"},
    "document": {"film", "movie", "movies", "cinema", "bioskop", "galeri", "foto"},
}


def extract_reusable_patterns(filename: str, tokens: list[str] | None = None) -> list[str]:
    """Extract clean, normalized, reusable semantic keyword patterns from a filename.

    Example:
    'Proposal_KKN_Desa_Waindawula_Final_Revisi_3.pdf' -> ['proposal', 'kkn', 'proposal kkn']
    Never returns noisy raw strings.
    """
    if not filename:
        return []

    # Strip extension
    stem = re.sub(r"\.[a-zA-Z0-9]{1,8}$", "", filename)
    # Replace punctuation and technical markers with space
    clean = re.sub(r"[._\-+\[\](),]", " ", stem).lower()
    words = [w.strip() for w in clean.split() if w.strip()]

    # Extract meaningful tokens (length >= 3, not pure numbers, not in noise)
    valid_tokens: list[str] = []
    for w in words:
        if len(w) >= 3 and not w.isdigit() and w not in NOISE_TOKENS:
            valid_tokens.append(w)

    patterns: list[str] = []
    # 1. Single keywords
    for t in valid_tokens:
        if t not in patterns:
            patterns.append(t)

    # 2. 2-word combinations if available
    if len(valid_tokens) >= 2:
        for i in range(len(valid_tokens) - 1):
            pair = f"{valid_tokens[i]} {valid_tokens[i+1]}"
            if pair not in patterns:
                patterns.append(pair)

    return patterns


def is_folder_compatible_with_family(folder_name: str, file_family: str | None) -> bool:
    """Enforce technical safety: personal preferences CANNOT override file family rules."""
    if not file_family or not folder_name:
        return True

    family_lower = file_family.lower()
    folder_lower = folder_name.lower().strip()

    blocked_keywords = INCOMPATIBLE_FOLDER_MAP.get(family_lower, set())
    for kw in blocked_keywords:
        if kw == folder_lower or kw in folder_lower.split():
            return False

    return True


def apply_preferences(
    suggestion: FolderSuggestion,
    preferences: list[UserPreference | dict[str, Any]],
    file_family: str | None = None,
    filename: str | None = None,
    current_folders: list[dict[str, Any]] | None = None,
) -> FolderSuggestion:
    """Apply learned user preferences to boost matching candidate folders.

    Maintains:
    - User-scoped isolation
    - Technical safety override (Video cannot become Office)
    - Stale folder protection (skips deleted folders)
    - Ambiguity preservation when preferences conflict
    - Clear human-readable explanation
    """
    if not preferences or not filename:
        return suggestion

    # Extract normalized reusable patterns from filename
    patterns = extract_reusable_patterns(filename)
    if not patterns:
        return suggestion

    # Map current user folders for validation and stale folder detection
    valid_folder_map: dict[int, dict[str, Any]] = {}
    if current_folders:
        valid_folder_map = {f["id"]: f for f in current_folders if isinstance(f, dict) and "id" in f}

    # Normalize preferences to UserPreference objects
    pref_objs: list[UserPreference] = []
    for p in preferences:
        if isinstance(p, UserPreference):
            pref_objs.append(p)
        elif isinstance(p, dict):
            pref_objs.append(UserPreference(
                user_id=p.get("user_id", 0),
                pattern=p.get("pattern", "").strip().lower(),
                target_folder_id=int(p.get("target_folder_id", 0)),
                domain=p.get("domain"),
                category=p.get("category"),
                positive_count=int(p.get("positive_count", 1)),
                negative_count=int(p.get("negative_count", 0)),
                confidence=float(p.get("confidence", 0.5)),
            ))

    # Match preferences against extracted patterns
    matching_prefs: list[UserPreference] = []
    for pref in pref_objs:
        if pref.pattern in patterns:
            matching_prefs.append(pref)

    if not matching_prefs:
        return suggestion

    # Work on a copy of candidates
    candidates = [
        FolderCandidate(
            folder_id=c.folder_id,
            name=c.name,
            path=c.path,
            score=c.score,
            match_type=c.match_type,
            reasons=list(c.reasons),
        )
        for c in suggestion.candidates
    ]
    cand_by_id = {c.folder_id: c for c in candidates}

    # Group matching preferences by pattern to detect competing choices
    pattern_groups: dict[str, list[UserPreference]] = {}
    for pref in matching_prefs:
        pattern_groups.setdefault(pref.pattern, []).append(pref)

    # Apply boosts with safety checks
    boosts_applied = 0
    for pref in matching_prefs:
        # Check for competing preferences on the exact same pattern (Section 10 & 29)
        rivals = [p for p in pattern_groups[pref.pattern] if p.target_folder_id != pref.target_folder_id]
        if rivals:
            total_pattern_pos = sum(p.positive_count for p in pattern_groups[pref.pattern])
            ratio = pref.positive_count / max(1, total_pattern_pos)
            # If ratio <= 0.60 (e.g. 5 vs 5 -> 0.50, 5 vs 4 -> 0.55), preferences are conflicting / ambiguous
            if ratio <= 0.60:
                boost = 0
            elif ratio >= 0.80:
                # Strong dominance (e.g. 10 vs 1 -> 0.91): dominant gets full boost
                boost = pref.calculate_boost()
            else:
                # Moderate dominance (e.g. 7 vs 3)
                boost = max(5, int(pref.calculate_boost() * 0.5))
        else:
            boost = pref.calculate_boost()

        if boost <= 0:
            continue

        target_id = pref.target_folder_id

        # 1. Stale folder protection (Section 13)
        if current_folders and target_id not in valid_folder_map:
            pref.is_stale = True
            log.debug("Preference target folder %s no longer exists, skipping as stale", target_id)
            continue

        folder_name = (
            cand_by_id[target_id].name if target_id in cand_by_id
            else valid_folder_map.get(target_id, {}).get("name", f"Folder-{target_id}")
        )

        # 2. Strict Technical Family Safety (Sections 5 & 7)
        # Personal preferences NEVER override actual technical file family
        if not is_folder_compatible_with_family(folder_name, file_family):
            log.info(
                "Technical evidence (%s) overrides user preference for '%s'",
                file_family,
                folder_name,
            )
            continue

        # 3. Apply boost to candidate
        reason_text = (
            f"Personal preference: Kebiasaan folder Anda memilih '{folder_name}' "
            f"untuk pola '{pref.pattern}' (+{boost})"
        )

        if target_id in cand_by_id:
            cand = cand_by_id[target_id]
            cand.score += boost
            cand.reasons.append(reason_text)
            boosts_applied += 1
        elif current_folders and target_id in valid_folder_map:
            # Candidate was not in initial top list, but is a valid user folder
            f_meta = valid_folder_map[target_id]
            cand = FolderCandidate(
                folder_id=target_id,
                name=folder_name,
                path=folder_name,
                score=boost,
                match_type="user_preference",
                reasons=[reason_text],
            )
            candidates.append(cand)
            cand_by_id[target_id] = cand
            boosts_applied += 1

    if boosts_applied == 0:
        return suggestion

    # Deterministic re-ranking
    candidates.sort(key=lambda c: (c.score, c.match_type == "exact", -c.folder_id), reverse=True)

    top = candidates[0]
    new_reasons = list(top.reasons)

    # Re-evaluate ambiguity among top candidates
    if len(candidates) >= 2:
        second = candidates[1]
        diff = top.score - second.score
        ratio = top.score / max(1, second.score)

        if diff <= 5 and ratio < 1.15:
            return FolderSuggestion(
                status="ambiguous",
                target_folder_id=None,
                target_folder_name=None,
                target_folder_path=None,
                confidence=round(top.score / (top.score + second.score), 2),
                candidates=candidates[:5],
                reasons=[
                    f"Multiple folders closely match: '{top.name}' ({top.score}) vs '{second.name}' ({second.score})"
                ],
            )

    return FolderSuggestion(
        status="matched",
        target_folder_id=top.folder_id,
        target_folder_name=top.name,
        target_folder_path=top.path,
        confidence=max(suggestion.confidence, min(1.0, round(top.score / 120.0, 2))),
        candidates=candidates[:5],
        reasons=new_reasons,
    )


class PreferenceEngine:
    """Service facade for user preference processing."""

    @staticmethod
    def extract_patterns(filename: str, tokens: list[str] | None = None) -> list[str]:
        return extract_reusable_patterns(filename, tokens)

    @staticmethod
    def is_compatible(folder_name: str, file_family: str | None) -> bool:
        return is_folder_compatible_with_family(folder_name, file_family)

    @staticmethod
    def apply(
        suggestion: FolderSuggestion,
        preferences: list[UserPreference | dict[str, Any]],
        file_family: str | None = None,
        filename: str | None = None,
        current_folders: list[dict[str, Any]] | None = None,
    ) -> FolderSuggestion:
        return apply_preferences(
            suggestion=suggestion,
            preferences=preferences,
            file_family=file_family,
            filename=filename,
            current_folders=current_folders,
        )
