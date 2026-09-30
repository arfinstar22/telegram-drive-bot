"""Screenshot Intelligence Analyzer coordinating entity extraction and category classification (Task 3B).

Provides:
- analyze_screenshot(input_data) -> ScreenshotIntelligenceResult
- ScreenshotAnalyzer service class
"""

from __future__ import annotations

import logging
from typing import Any

from darfin_intelligence.ocr.cleaner import clean_ocr_text
from darfin_intelligence.ocr.models import OCRResult
from darfin_intelligence.screenshot.entities import extract_all_entities
from darfin_intelligence.screenshot.models import ScreenshotIntelligenceResult
from darfin_intelligence.screenshot.scorer import (
    classify_screenshot,
    evaluate_screenshot_signals,
)

log = logging.getLogger(__name__)


def analyze_screenshot(input_data: OCRResult | str | dict[str, Any]) -> ScreenshotIntelligenceResult:
    """Analyze screenshot OCR text, extract entities, and classify category.

    Accepts:
    - OCRResult instance (from Task 3A)
    - string (raw OCR text)
    - dict (serialized OCRResult)

    Guarantees:
    - 100% deterministic local execution (zero AI APIs, zero external calls)
    - Preserves raw and normalized text
    - Never leaks or logs sensitive OTP/payment card numbers
    """
    raw_text = ""
    normalized_text = ""
    ocr_confidence: float | None = None

    if isinstance(input_data, OCRResult):
        raw_text = input_data.raw_text or ""
        normalized_text = input_data.normalized_text or clean_ocr_text(raw_text)
        ocr_confidence = input_data.confidence
    elif isinstance(input_data, str):
        raw_text = input_data
        normalized_text = clean_ocr_text(input_data)
        ocr_confidence = None
    elif isinstance(input_data, dict):
        raw_text = input_data.get("raw_text") or input_data.get("text", "")
        normalized_text = input_data.get("normalized_text") or clean_ocr_text(raw_text)
        ocr_confidence = input_data.get("confidence")

    effective_text = normalized_text or raw_text

    # Handle completely empty text
    if not effective_text.strip():
        return ScreenshotIntelligenceResult(
            status="unknown",
            category="screenshot_unknown",
            confidence=0.0,
            raw_text=raw_text,
            normalized_text=normalized_text,
            ocr_confidence=ocr_confidence,
            explanation=["No readable text found in screenshot OCR result"],
        )

    # 1. Extract structured entities (dates, times, prices, URLs, emails, phones, merchant, codes)
    entities = extract_all_entities(effective_text)

    # 2. Evaluate multi-signal scoring across all categories
    scores, matches, evidence_notes = evaluate_screenshot_signals(effective_text, entities)

    # 3. Classify category and determine confidence + ambiguity
    category, status, confidence, explanation = classify_screenshot(
        scores=scores,
        matches=matches,
        evidence_notes=evidence_notes,
        entities=entities,
        ocr_confidence=ocr_confidence,
    )

    return ScreenshotIntelligenceResult(
        status=status,
        category=category,
        confidence=confidence,
        entities=entities,
        signals=matches,
        evidence=evidence_notes,
        explanation=explanation,
        raw_text=raw_text,
        normalized_text=normalized_text,
        ocr_confidence=ocr_confidence,
        category_scores={k: v for k, v in scores.items() if v > 0},
    )


class ScreenshotAnalyzer:
    """Service facade for Screenshot Intelligence Core."""

    @staticmethod
    def analyze(input_data: OCRResult | str | dict[str, Any]) -> ScreenshotIntelligenceResult:
        return analyze_screenshot(input_data)
