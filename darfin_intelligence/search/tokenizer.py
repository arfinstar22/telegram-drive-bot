"""Query tokenizer for Darfin Search Intelligence Core.

Extracts phrases and individual normalized tokens while preserving technical expressions.
"""

from __future__ import annotations

import re
from darfin_intelligence.search.normalizer import normalize_token


# Regex for quoted phrases: "..." or '...'
PHRASE_PATTERN = re.compile(r'["\']([^"\']+)["\']')

# Regex for splitting unquoted tokens: split on whitespace, underscores, or slashes
# but preserve hyphenated technical words like web-dl
TOKEN_SPLIT_PATTERN = re.compile(r'[\s_/,;]+')


def tokenize_query(query: str) -> tuple[list[str], list[str]]:
    """Tokenize search query into list of individual tokens and quoted phrases.

    Returns:
        (tokens, phrases)
    """
    if not query or not query.strip():
        return [], []

    phrases: list[str] = []
    # 1. Extract quoted phrases
    def _extract_phrase(match: re.Match) -> str:
        phrase_content = match.group(1).strip()
        if phrase_content:
            phrases.append(phrase_content.lower())
        return " "  # Replace matched phrase with whitespace

    remaining = PHRASE_PATTERN.sub(_extract_phrase, query)

    # 2. Split remaining string into tokens
    raw_tokens = TOKEN_SPLIT_PATTERN.split(remaining)
    tokens: list[str] = []

    for raw in raw_tokens:
        tok = normalize_token(raw)
        if tok and tok not in tokens:
            tokens.append(tok)

    return tokens, phrases


def extract_filename_tokens(filename: str) -> list[str]:
    """Tokenize a filename into individual stem words and technical tokens."""
    if not filename:
        return []
    # Remove extension
    parts = filename.rsplit(".", 1)
    stem = parts[0] if len(parts) > 1 and len(parts[1]) <= 10 else filename

    # Split on dots, spaces, underscores, hyphens, brackets
    raw_tokens = re.split(r'[\s._\-+\[\]()]+', stem)
    tokens: list[str] = []

    for raw in raw_tokens:
        tok = normalize_token(raw)
        if tok and tok not in tokens:
            tokens.append(tok)

    return tokens
