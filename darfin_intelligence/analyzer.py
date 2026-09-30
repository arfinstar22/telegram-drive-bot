"""Analyzer — main entry point for the intelligence pipeline.

Pipeline:
  FILE → FILE TYPE DETECTOR → METADATA COLLECTOR → FILENAME TOKENIZER
  → NORMALIZER → DICTIONARY/ALIAS RESOLVER → PATTERN DETECTOR
  → SIGNAL ENGINE → PARSER → CONFIDENCE ENGINE → INTELLIGENCE RESULT
"""

from __future__ import annotations

import logging
import time

from darfin_intelligence.models import IntelligenceResult, FileTypeInfo, Signal
from darfin_intelligence.tokenizer import tokenize, get_extension
from darfin_intelligence.normalizer import normalize_token
from darfin_intelligence.dictionaries import (
    EXTENSION_FAMILIES,
    DOMAIN_KEYWORDS,
    mime_to_family,
)
from darfin_intelligence.signals import (
    collect_signals,
    score_signals,
    compute_confidence,
    determine_family,
)
from darfin_intelligence.parsers import (
    parse_media_filename,
    parse_generic_filename,
    parse_whatsapp_filename,
)

log = logging.getLogger(__name__)


def analyze(
    filename: str,
    mime_type: str | None = None,
    file_type: str | None = None,
    file_id: int | None = None,
) -> IntelligenceResult:
    """Run the full intelligence pipeline on a file.

    Args:
        filename: Original filename (e.g. "Movie.2026.1080p.WEB-DL.mkv")
        mime_type: MIME type if known (e.g. "video/x-matroska")
        file_type: Telegram file_type if known (e.g. "video", "document")
        file_id: Database file ID if available

    Returns:
        IntelligenceResult with all detected metadata.
        Never raises — returns result with status="failed" on error.
    """
    start = time.monotonic()

    try:
        result = _run_pipeline(filename, mime_type, file_type, file_id)
    except Exception as exc:
        log.error("Intelligence analysis failed for %r: %s", filename, exc)
        result = IntelligenceResult(
            file_id=file_id,
            filename_original=filename,
            filename_normalized=filename,
            status="failed",
            error=str(exc),
        )

    duration_ms = round((time.monotonic() - start) * 1000, 2)
    log.debug(
        "Intelligence: file_id=%s parser=%s status=%s duration=%.2fms",
        file_id, result.parser_name, result.status, duration_ms,
    )

    return result


def _run_pipeline(
    filename: str,
    mime_type: str | None,
    file_type: str | None,
    file_id: int | None,
) -> IntelligenceResult:
    """Internal pipeline execution."""
    result = IntelligenceResult(
        file_id=file_id,
        filename_original=filename,
    )

    # 1. Extract extension
    extension = get_extension(filename)

    # 2. Tokenize filename
    tokens = tokenize(filename)
    result.tokens = tokens

    # 3. Normalize filename
    normalized_parts = []
    for token in tokens:
        canonical = normalize_token(token)
        normalized_parts.append(canonical if canonical else token)
    result.filename_normalized = " ".join(normalized_parts)

    # 4. Build FileTypeInfo
    fti = FileTypeInfo()
    fti.extension = f".{extension}" if extension else None
    fti.extension_normalized = extension
    fti.mime_type = mime_type
    fti.mime_family = mime_to_family(mime_type)
    if extension:
        fti.container = extension
        ext_family = EXTENSION_FAMILIES.get(extension)
        if ext_family and ext_family != "application":
            fti.family = ext_family
    # MIME overrides extension for family
    if fti.mime_family and fti.mime_family != "other":
        fti.family = fti.mime_family

    result.file_type = fti

    # 5. Collect signals
    signals = collect_signals(tokens, extension, mime_type, file_type)
    result.signals = signals

    # 6. Score signals
    scores = score_signals(signals)
    result.signal_scores = scores

    # 7. Compute confidence
    confidence = compute_confidence(scores)
    result.confidence = confidence

    # 8. Determine family (signals override simple extension lookup)
    if scores:
        family = determine_family(scores, confidence)
        result.file_type.family = family

    # 9. Collect domain signals
    for token in tokens:
        tok_lower = token.lower()
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if tok_lower in keywords:
                strength = "weak"
                # Domain signal is strong if it aligns with the detected family
                if domain in ("media",) and result.file_type.family == "video":
                    strength = "strong"
                elif domain in ("education", "office", "finance", "identity", "health") and result.file_type.family == "document":
                    strength = "strong"
                result.domain_signals[tok_lower] = f"{domain}/{strength}"

    # 10. Parse entities
    # Try WhatsApp parser first
    wa_result = parse_whatsapp_filename(tokens, filename)
    if wa_result:
        result.entities, result.parser_name = wa_result
    elif _has_media_signals(signals):
        result.entities, result.parser_name = parse_media_filename(tokens)
    else:
        result.entities, result.parser_name = parse_generic_filename(tokens)

    # 11. Build evidence list
    result.evidence = [
        f"{s.source}={s.value}" for s in sorted(signals, key=lambda s: -s.weight)
    ]

    result.status = "success"
    return result


def _has_media_signals(signals: list[Signal]) -> bool:
    """Check if there are enough media signals to use the media parser."""
    media_weight = sum(
        s.weight for s in signals
        if s.category == "video" and s.source in ("technical_marker", "mime", "extension", "telegram_type")
    )
    return media_weight >= 15
