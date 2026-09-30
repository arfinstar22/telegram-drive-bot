"""Parsers — extract structured entities from filename tokens.

media.py handles the TITLE.YEAR.RESOLUTION.SOURCE.CODEC.AUDIO pattern.
generic.py handles documents, WhatsApp files, screenshots, etc.
"""

from __future__ import annotations

import re

from darfin_intelligence.models import MediaEntities
from darfin_intelligence.normalizer import (
    normalize_resolution,
    normalize_source,
    normalize_codec,
    normalize_audio_codec,
    is_technical_marker,
    is_year,
)


def parse_media_filename(tokens: list[str]) -> tuple[MediaEntities, str]:
    """Parse media-style filename tokens.

    Returns (entities, parser_name).

    Strategy: walk tokens left to right. Everything before the first
    recognized technical marker or year is title. After that, extract
    resolution/source/codec/audio/year/season/episode.
    """
    entities = MediaEntities()

    title_parts: list[str] = []
    found_boundary = False
    remaining_tokens: list[str] = []

    for i, token in enumerate(tokens):
        tok_lower = token.lower()

        if not found_boundary:
            # Check if this token is a boundary (year, resolution, source, etc.)
            if is_year(token) and _has_media_context(tokens, i):
                found_boundary = True
                entities.year = int(token)
                remaining_tokens = tokens[i + 1:]
                continue
            if is_technical_marker(token):
                found_boundary = True
                remaining_tokens = tokens[i:]
                break
            title_parts.append(token)
        # After boundary found, handled below

    if not found_boundary:
        # No boundary found — entire filename is title
        # Try to detect year from any token
        for token in tokens:
            if is_year(token):
                entities.year = int(token)
                title_parts = [t for t in tokens if t != token]
                break

    # Extract entities from remaining tokens
    for token in remaining_tokens:
        tok_lower = token.lower()

        if not entities.year and is_year(token):
            entities.year = int(token)
            continue

        res = normalize_resolution(tok_lower)
        if res and not entities.resolution:
            entities.resolution = res
            continue

        src = normalize_source(tok_lower)
        if src and not entities.source:
            entities.source = src
            continue

        codec = normalize_codec(tok_lower)
        if codec and not entities.codec:
            entities.codec = codec
            continue

        audio = normalize_audio_codec(tok_lower)
        if audio and not entities.audio_codec:
            entities.audio_codec = audio
            continue

    # Series detection across all tokens
    full_str = " ".join(tokens)
    se = re.search(r'[Ss](\d{1,2})[Ee](\d{1,3})', full_str)
    if se:
        entities.season = int(se.group(1))
        entities.episode = int(se.group(2))
        # Remove SxxExx from title parts
        title_parts = [t for t in title_parts if not re.match(r'[Ss]\d{1,2}[Ee]\d{1,3}', t)]
    else:
        se_only = re.search(r'[Ss](\d{1,2})$', full_str)
        if se_only:
            entities.season = int(se_only.group(1))

    # Release group: last token after a dash if not a known marker
    if remaining_tokens:
        last = remaining_tokens[-1]
        if not is_technical_marker(last) and not is_year(last) and not normalize_audio_codec(last.lower()):
            entities.release_group = last

    if title_parts:
        entities.title = " ".join(title_parts)

    return entities, "media_filename_parser"


def parse_generic_filename(tokens: list[str]) -> tuple[MediaEntities, str]:
    """Parse generic (non-media) filename tokens.

    Extracts title and year. Domain classification happens in signal engine.
    """
    entities = MediaEntities()

    title_parts: list[str] = []
    for token in tokens:
        if is_year(token) and not entities.year:
            entities.year = int(token)
        else:
            title_parts.append(token)

    if title_parts:
        entities.title = " ".join(title_parts)

    return entities, "generic_filename_parser"


def parse_whatsapp_filename(tokens: list[str], original: str) -> tuple[MediaEntities, str] | None:
    """Try to parse WhatsApp-style filenames (IMG_YYYYMMDD, VID_YYYYMMDD, etc.)."""
    stem = original.rsplit(".", 1)[0] if "." in original else original

    patterns = [
        (r'^(?:VID|video)[-_]?((?:19|20)\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', "WhatsApp Video"),
        (r'^(?:IMG|foto|photo)[-_]?((?:19|20)\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', "WhatsApp Photo"),
        (r'^(?:AUD|audio|PTT|voice)[-_]?((?:19|20)\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', "WhatsApp Audio"),
        (r'^(?:Screenshot|tangkapan[-_]?layar)[-_]?((?:19|20)\d\d)[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])', "Screenshot"),
    ]

    for pattern, label in patterns:
        m = re.match(pattern, stem, re.IGNORECASE)
        if m:
            entities = MediaEntities()
            entities.year = int(m.group(1))
            entities.title = label
            return entities, "whatsapp_filename_parser"

    return None


def _has_media_context(tokens: list[str], year_idx: int) -> bool:
    """Check if a year token has nearby media context (resolution, source, etc.)."""
    # If there are technical markers anywhere, the year is likely real
    for i, token in enumerate(tokens):
        if i == year_idx:
            continue
        if is_technical_marker(token):
            return True
    # Year at the end of tokens with no other context → still accept
    # (could be a document year too, but parser doesn't auto-classify)
    return True
