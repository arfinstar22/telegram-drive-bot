"""Deterministic fuzzy matching for Darfin Search Intelligence Core.

Lightweight, local sequence similarity without external models or embeddings.
"""

from __future__ import annotations

import difflib


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def fuzzy_match_token(
    token: str,
    candidate_words: list[str],
    threshold: float = 0.80,
    min_length: int = 4,
) -> tuple[float, str | None]:
    """Find best fuzzy match for a token against candidate words.

    Args:
        token: Query token to match.
        candidate_words: List of words from filename, folder, or OCR.
        threshold: Minimum similarity ratio (0.0 - 1.0).
        min_length: Minimum token length to allow fuzzy matching.

    Returns:
        (best_ratio, best_word) or (0.0, None) if no match meets threshold.
    """
    if not token or len(token) < min_length or not candidate_words:
        return 0.0, None

    token_lower = token.lower()
    best_ratio = 0.0
    best_word: str | None = None

    for candidate in candidate_words:
        if not candidate or len(candidate) < min_length:
            continue
        c_lower = candidate.lower()
        if token_lower == c_lower:
            # Exact match, not fuzzy
            return 1.0, candidate

        # Length difference heuristic: if length difference > 3, skip ratio check
        if abs(len(token_lower) - len(c_lower)) > 3:
            continue

        ratio = difflib.SequenceMatcher(None, token_lower, c_lower).ratio()
        if ratio > best_ratio and ratio >= threshold:
            best_ratio = ratio
            best_word = candidate

    if best_ratio >= threshold:
        return best_ratio, best_word

    return 0.0, None
