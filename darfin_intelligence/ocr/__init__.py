"""Darfin Intelligence Local OCR Core (Task 3A).

Provides local, deterministic text extraction from images without cloud or AI APIs.
"""

from darfin_intelligence.ocr.models import OCRBlock, OCRResult
from darfin_intelligence.ocr.cleaner import clean_ocr_text
from darfin_intelligence.ocr.engine import (
    BaseOCREngine,
    LocalTesseractEngine,
    MockOCREngine,
)
from darfin_intelligence.ocr.service import (
    LocalOCREngine,
    OCRService,
    ocr_available,
    ocr,
    extract_text,
    analyze_image_text,
    SUPPORTED_FORMATS,
)

__all__ = [
    "OCRBlock",
    "OCRResult",
    "clean_ocr_text",
    "BaseOCREngine",
    "LocalTesseractEngine",
    "MockOCREngine",
    "LocalOCREngine",
    "OCRService",
    "ocr_available",
    "ocr",
    "extract_text",
    "analyze_image_text",
    "SUPPORTED_FORMATS",
]
