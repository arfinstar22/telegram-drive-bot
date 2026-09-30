"""Filename tokenizer — splits filenames into meaningful tokens.

Handles dots, underscores, dashes, brackets, parentheses, braces, spaces.
Preserves compound technical tokens like WEB-DL, x264, H.265.
"""

from __future__ import annotations

import re


# Compound tokens that should NOT be split
_COMPOUND_PATTERNS: dict[str, str] = {
    r"web[\s._-]?dl": "WEB-DL",
    r"web[\s._-]?rip": "WEBRip",
    r"blu[\s._-]?ray": "BluRay",
    r"br[\s._-]?rip": "BRRip",
    r"bd[\s._-]?rip": "BDRip",
    r"hd[\s._-]?rip": "HDRip",
    r"dvd[\s._-]?rip": "DVDRip",
    r"hd[\s._-]?tv": "HDTV",
    r"h[\s._-]?264": "H.264",
    r"h[\s._-]?265": "H.265",
    r"true[\s._-]?hd": "TrueHD",
    r"dolby[\s._-]?digital": "DolbyDigital",
    r"dolby[\s._-]?atmos": "DolbyAtmos",
    r"e[\s._-]?ac3": "EAC3",
    r"video[\s._-]?note": "video_note",
    r"voice[\s._-]?note": "voice_note",
}


def tokenize(filename: str) -> list[str]:
    """Split filename into tokens, preserving compound technical markers.

    Returns list of raw token strings (not lowered — caller decides casing).
    """
    stem = _strip_extension(filename)

    # Protect compound tokens by replacing with placeholders
    protected: dict[str, str] = {}
    working = stem
    for pattern, canonical in _COMPOUND_PATTERNS.items():
        regex = re.compile(pattern, re.IGNORECASE)
        match = regex.search(working)
        if match:
            placeholder = f"XCOMPOUND{len(protected)}X"
            protected[placeholder] = canonical
            working = working[:match.start()] + placeholder + working[match.end():]

    # Split on delimiters: . _ - space [ ] ( ) { }
    raw_tokens = re.split(r'[\s._\-\[\](){}]+', working)

    # Restore compound tokens and filter empties
    tokens = []
    for tok in raw_tokens:
        if not tok:
            continue
        if tok in protected:
            tokens.append(protected[tok])
        else:
            tokens.append(tok)

    return tokens


def _strip_extension(filename: str) -> str:
    """Strip file extension from filename."""
    dot_pos = filename.rfind(".")
    if dot_pos > 0 and dot_pos > len(filename) - 10:
        possible_ext = filename[dot_pos + 1:]
        if re.match(r'^[a-zA-Z0-9]{1,8}$', possible_ext):
            return filename[:dot_pos]
    return filename


def get_extension(filename: str) -> str | None:
    """Extract normalized extension (lowercase, no dot)."""
    dot_pos = filename.rfind(".")
    if dot_pos > 0 and dot_pos > len(filename) - 10:
        ext = filename[dot_pos + 1:].lower()
        if re.match(r'^[a-zA-Z0-9]{1,8}$', ext):
            return ext
    return None
