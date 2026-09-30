"""Signal engine — weighted evidence collection and scoring.

Signal hierarchy (Level 5 = strongest):
  Level 5: File signature / magic bytes  (+100)
  Level 4: MIME type                     (+80)
  Level 3: Known extension               (+30)
  Level 2: Technical pattern marker       (+15)
  Level 1: Domain keyword                 (+3)
"""

from __future__ import annotations

import re

from darfin_intelligence.models import Signal
from darfin_intelligence.dictionaries import (
    EXTENSION_FAMILIES,
    MEDIA_TECHNICAL_SIGNALS,
    DOMAIN_KEYWORDS,
    mime_to_family,
)
from darfin_intelligence.normalizer import (
    normalize_resolution,
    normalize_source,
    normalize_codec,
    normalize_audio_codec,
    is_technical_marker,
)


# Weight constants
W_MAGIC = 100
W_MIME = 80
W_EXTENSION = 30
W_TECHNICAL = 15
W_STRUCTURAL = 10
W_DOMAIN = 3


def collect_signals(
    tokens: list[str],
    extension: str | None,
    mime_type: str | None,
    telegram_file_type: str | None = None,
) -> list[Signal]:
    """Collect all evidence signals from available metadata.

    Returns list of Signal objects, unsorted.
    """
    signals: list[Signal] = []

    # Level 4: MIME type
    if mime_type:
        family = mime_to_family(mime_type)
        if family and family != "other":
            signals.append(Signal(
                source="mime",
                category=family,
                value=mime_type,
                weight=W_MIME,
                level=4,
            ))

    # Level 3: Extension
    if extension:
        ext_lower = extension.lower()
        family = EXTENSION_FAMILIES.get(ext_lower)
        if family:
            signals.append(Signal(
                source="extension",
                category=family if family != "application" else "archive",
                value=f".{ext_lower}",
                weight=W_EXTENSION,
                level=3,
            ))

    # Level 3.5: Telegram file_type (between extension and MIME)
    _TELEGRAM_TYPE_MAP = {
        "video": "video", "video_note": "video",
        "photo": "image", "animation": "image",
        "audio": "audio", "voice": "audio",
        "document": "document",
    }
    if telegram_file_type:
        mapped = _TELEGRAM_TYPE_MAP.get(telegram_file_type)
        if mapped:
            signals.append(Signal(
                source="telegram_type",
                category=mapped,
                value=telegram_file_type,
                weight=W_EXTENSION + 5,  # slightly above extension
                level=3,
            ))

    # Level 2: Technical markers in tokens
    for token in tokens:
        tok_lower = token.lower()
        if tok_lower in MEDIA_TECHNICAL_SIGNALS or is_technical_marker(token):
            cat = "video"  # most technical markers imply media/video
            if normalize_resolution(tok_lower):
                cat = "video"
            elif normalize_source(tok_lower):
                cat = "video"
            elif normalize_codec(tok_lower):
                cat = "video"
            elif normalize_audio_codec(tok_lower):
                cat = "audio"
            signals.append(Signal(
                source="technical_marker",
                category=cat,
                value=token,
                weight=W_TECHNICAL,
                level=2,
            ))

    # Level 2: Series pattern in original token sequence
    token_str = " ".join(tokens)
    series_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,3})', token_str)
    if series_match:
        signals.append(Signal(
            source="structural",
            category="video",
            value=f"S{series_match.group(1)}E{series_match.group(2)}",
            weight=W_STRUCTURAL,
            level=2,
        ))

    # Level 1: Domain keywords in tokens
    for token in tokens:
        tok_lower = token.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if tok_lower in keywords:
                signals.append(Signal(
                    source="domain_keyword",
                    category=domain,
                    value=token,
                    weight=W_DOMAIN,
                    level=1,
                ))

    # Level 2: Negative evidence signals
    # If media evidence is strong (weight >= 30), apply negative penalty to conflicting domain categories (office, education, finance)
    video_weight = sum(s.weight for s in signals if s.category == "video" and s.level >= 2)
    if video_weight >= 30:
        for s in list(signals):
            if s.source == "domain_keyword" and s.category in ("office", "education", "finance"):
                signals.append(Signal(
                    source="negative_evidence",
                    category=s.category,
                    value=f"suppressed_by_media_evidence({s.value})",
                    weight=-s.weight,
                    level=2,
                ))

    # Conversely, if document evidence is strong (e.g. PDF MIME or extension), suppress media domain tokens
    doc_weight = sum(s.weight for s in signals if s.category == "document" and s.level >= 3)
    if doc_weight >= 30:
        for s in list(signals):
            if s.source == "domain_keyword" and s.category == "media":
                signals.append(Signal(
                    source="negative_evidence",
                    category=s.category,
                    value=f"suppressed_by_document_evidence({s.value})",
                    weight=-s.weight,
                    level=2,
                ))

    return signals


def score_signals(signals: list[Signal]) -> dict[str, int]:
    """Aggregate signals into category scores.

    Maps domain categories to file families for comparison.
    """
    family_scores: dict[str, int] = {}
    domain_scores: dict[str, int] = {}

    for sig in signals:
        if sig.category in ("video", "image", "audio", "document", "archive"):
            family_scores[sig.category] = max(0, family_scores.get(sig.category, 0) + sig.weight)
        else:
            domain_scores[sig.category] = max(0, domain_scores.get(sig.category, 0) + sig.weight)

    # Merge: domain scores contribute to their natural file family
    # but at their original (low) weight — they don't override
    scores = dict(family_scores)
    for domain, dscore in domain_scores.items():
        scores[domain] = max(0, dscore)

    return scores


def compute_confidence(scores: dict[str, int]) -> dict[str, float]:
    """Compute confidence per family from scores.

    Returns dict like {"video": 0.95, "document": 0.03, ...}.
    File-family scores only (not domain).
    """
    families = ["video", "image", "audio", "document", "archive"]
    family_scores = {f: scores.get(f, 0) for f in families}
    total = sum(family_scores.values())

    if total == 0:
        return {}

    return {f: round(s / total, 4) for f, s in family_scores.items() if s > 0}


def determine_family(scores: dict[str, int], confidence: dict[str, float]) -> str:
    """Determine the winning file family from scores.

    Only file-type families compete. Domain keywords never override
    strong file-type evidence.
    """
    families = ["video", "image", "audio", "document", "archive"]
    family_scores = {f: scores.get(f, 0) for f in families if scores.get(f, 0) > 0}

    if not family_scores:
        return "other"

    winner = max(family_scores, key=family_scores.get)
    return winner
