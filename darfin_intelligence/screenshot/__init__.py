"""Screenshot Intelligence Core package for Darfin Storage (Task 3B).

Provides deterministic rule-based analysis of screenshot OCR text without AI APIs.
"""

from __future__ import annotations

from darfin_intelligence.screenshot.models import (
    ExtractedDate,
    ExtractedPrice,
    ExtractedEntities,
    SignalMatch,
    ScreenshotIntelligenceResult,
)
from darfin_intelligence.screenshot.entities import (
    extract_dates,
    extract_times,
    extract_prices,
    extract_urls,
    extract_emails,
    extract_phone_numbers,
    extract_merchant,
    extract_codes_and_sensitive,
    extract_chat_names,
    extract_all_entities,
)
from darfin_intelligence.screenshot.scorer import (
    SCREENSHOT_CATEGORIES,
    evaluate_screenshot_signals,
    classify_screenshot,
)
from darfin_intelligence.screenshot.analyzer import (
    analyze_screenshot,
    ScreenshotAnalyzer,
)

__all__ = [
    "ExtractedDate",
    "ExtractedPrice",
    "ExtractedEntities",
    "SignalMatch",
    "ScreenshotIntelligenceResult",
    "extract_dates",
    "extract_times",
    "extract_prices",
    "extract_urls",
    "extract_emails",
    "extract_phone_numbers",
    "extract_merchant",
    "extract_codes_and_sensitive",
    "extract_chat_names",
    "extract_all_entities",
    "SCREENSHOT_CATEGORIES",
    "evaluate_screenshot_signals",
    "classify_screenshot",
    "analyze_screenshot",
    "ScreenshotAnalyzer",
]
