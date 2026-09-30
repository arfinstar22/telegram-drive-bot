"""Normalization utilities for Darfin Search Intelligence Core.

Standardizes search queries, tokens, sizes, and currency values.
"""

from __future__ import annotations

import re
import unicodedata

# Common technical and media aliases
TECHNICAL_ALIASES: dict[str, str] = {
    "webdl": "web-dl",
    "web-dl": "web-dl",
    "webrip": "webrip",
    "bluray": "bluray",
    "blu-ray": "bluray",
    "brrip": "bluray",
    "bdrip": "bluray",
    "4k": "2160p",
    "uhd": "2160p",
    "2160p": "2160p",
    "1080p": "1080p",
    "fhd": "1080p",
    "720p": "720p",
    "hd": "720p",
    "480p": "480p",
    "h264": "x264",
    "x264": "x264",
    "h.264": "x264",
    "x.264": "x264",
    "h265": "hevc",
    "x265": "hevc",
    "x.265": "hevc",
    "hevc": "hevc",
}

# Domain & family aliases (maps variations to canonical token)
SEMANTIC_ALIASES: dict[str, str] = {
    "film": "movie",
    "films": "movie",
    "movie": "movie",
    "movies": "movie",
    "cinema": "movie",
    "bioskop": "movie",
    "series": "series",
    "serial": "series",
    "drakor": "series",
    "anime": "anime",
    "struk": "receipt",
    "receipt": "receipt",
    "kwitansi": "receipt",
    "kuitansi": "receipt",
    "nota": "receipt",
    "bon": "receipt",
    "foto": "image",
    "photo": "image",
    "photos": "image",
    "gambar": "image",
    "image": "image",
    "images": "image",
    "pic": "image",
    "picture": "image",
    "dokumen": "document",
    "document": "document",
    "documents": "document",
    "doc": "document",
    "docs": "document",
    "berkas": "document",
    "surat": "letter",
    "musik": "audio",
    "music": "audio",
    "lagu": "audio",
    "song": "audio",
    "audio": "audio",
    "rekaman": "audio",
    "arsip": "archive",
    "archive": "archive",
    "zip": "archive",
    "rar": "archive",
    "video": "video",
    "vidio": "video",
}


def normalize_search_string(text: str) -> str:
    """Normalize general search string (NFKC, lowercase, stripped)."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", str(text))
    # Replace common separators with spaces
    normalized = re.sub(r"[\t\r\n]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().lower()


def normalize_token(token: str) -> str:
    """Normalize a single token, preserving technical alphanumeric characters."""
    if not token:
        return ""
    # Strip peripheral punctuation: . , : ; ! ? ' " ` ( ) [ ] { }
    cleaned = token.strip(".,:;!?\"'`()[]{}*<>~#$")
    cleaned_lower = cleaned.lower()

    if not cleaned_lower:
        return ""

    # Check technical aliases first
    if cleaned_lower in TECHNICAL_ALIASES:
        return TECHNICAL_ALIASES[cleaned_lower]

    return cleaned_lower


def canonical_alias(token: str) -> str:
    """Return canonical semantic alias if known, or token itself."""
    norm = normalize_token(token)
    return SEMANTIC_ALIASES.get(norm, norm)


def parse_size_str(size_str: str) -> int | None:
    """Parse size strings like '10mb', '500kb', '1.5gb' into integer bytes."""
    if not size_str:
        return None
    m = re.match(r"^([><=]?)\s*([\d.]+)\s*([kmgt]?b?)$", size_str.lower().strip())
    if not m:
        return None
    try:
        val = float(m.group(2))
        unit = m.group(3)
        multiplier = 1
        if "k" in unit:
            multiplier = 1024
        elif "m" in unit:
            multiplier = 1024 * 1024
        elif "g" in unit:
            multiplier = 1024 * 1024 * 1024
        elif "t" in unit:
            multiplier = 1024 * 1024 * 1024 * 1024
        return int(val * multiplier)
    except (ValueError, TypeError):
        return None


def parse_amount_number(amount_str: str) -> float | None:
    """Parse monetary expressions like 'Rp 25.000', '25000', '12,500.00' to float."""
    if not amount_str:
        return None
    clean = re.sub(r"^(?:rp\.?|idr|\$|usd)\s*", "", amount_str.strip(), flags=re.IGNORECASE)
    clean = clean.strip()
    if not clean:
        return None

    # Indonesian dot-thousands (e.g. 25.000 or 127.500)
    if re.match(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$", clean):
        parts = clean.split(",")
        int_part = parts[0].replace(".", "")
        dec_part = "." + parts[1] if len(parts) > 1 else ""
        try:
            return float(int_part + dec_part)
        except ValueError:
            return None

    # Standard US comma-thousands (e.g. 25,000 or 12,500.00)
    if re.match(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$", clean):
        try:
            return float(clean.replace(",", ""))
        except ValueError:
            return None

    # Plain integer or float
    if re.match(r"^\d+(?:\.\d+)?$", clean):
        try:
            return float(clean)
        except ValueError:
            return None

    return None
