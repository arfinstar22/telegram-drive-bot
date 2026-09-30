"""Document and Receipt Intelligence Analyzer coordinator for Task 3C.

Provides unified entrypoints:
- analyze_document(ocr_result, screenshot_result, text) -> DocumentIntelligenceResult
- analyze_receipt(text_or_ocr) -> DocumentIntelligenceResult
- parse_receipt(text_or_ocr) -> ReceiptData
- parse_document(text_or_ocr) -> DocumentData
- extract_line_items(text) -> list[ReceiptItem]
- DocumentIntelligenceAnalyzer facade class
"""

from __future__ import annotations

import logging
from typing import Any

from darfin_intelligence.document.line_items import extract_line_items
from darfin_intelligence.document.models import (
    DocumentData,
    DocumentIntelligenceResult,
    ReceiptData,
    ReceiptItem,
)
from darfin_intelligence.document.normalizer import clean_document_text
from darfin_intelligence.document.document_parser import parse_document_data
from darfin_intelligence.document.receipt_parser import parse_receipt_data
from darfin_intelligence.ocr.cleaner import clean_ocr_text
from darfin_intelligence.ocr.models import OCRResult
from darfin_intelligence.screenshot.analyzer import analyze_screenshot
from darfin_intelligence.screenshot.models import ScreenshotIntelligenceResult

log = logging.getLogger(__name__)


def _extract_raw_and_cleaned(
    ocr_result: OCRResult | None = None,
    text: str | None = None,
) -> tuple[str, str]:
    """Safely extract raw and normalized text from multiple input variants."""
    raw_text = ""
    if ocr_result is not None:
        if isinstance(ocr_result, OCRResult):
            raw_text = ocr_result.raw_text or ocr_result.normalized_text or ""
        elif isinstance(ocr_result, dict):
            raw_text = ocr_result.get("raw_text") or ocr_result.get("normalized_text") or ocr_result.get("text", "")
        elif isinstance(ocr_result, str):
            raw_text = ocr_result
    elif text is not None:
        raw_text = text

    normalized_text = clean_document_text(raw_text)
    return raw_text, normalized_text


def parse_receipt(text_or_ocr: Any) -> ReceiptData:
    """Parse receipt text or OCRResult directly into ReceiptData."""
    raw, cleaned = _extract_raw_and_cleaned(
        ocr_result=text_or_ocr if not isinstance(text_or_ocr, str) else None,
        text=text_or_ocr if isinstance(text_or_ocr, str) else None,
    )
    receipt_data, _ = parse_receipt_data(cleaned)
    return receipt_data


def parse_document(text_or_ocr: Any) -> DocumentData:
    """Parse generic document text or OCRResult directly into DocumentData."""
    raw, cleaned = _extract_raw_and_cleaned(
        ocr_result=text_or_ocr if not isinstance(text_or_ocr, str) else None,
        text=text_or_ocr if isinstance(text_or_ocr, str) else None,
    )
    doc_data, _ = parse_document_data(cleaned)
    return doc_data


def analyze_receipt(text_or_ocr: Any) -> DocumentIntelligenceResult:
    """Analyze receipt text or OCRResult and return DocumentIntelligenceResult."""
    return analyze_document(
        ocr_result=text_or_ocr if not isinstance(text_or_ocr, str) else None,
        text=text_or_ocr if isinstance(text_or_ocr, str) else None,
        force_receipt=True,
    )


def analyze_document(
    ocr_result: OCRResult | dict[str, Any] | str | None = None,
    screenshot_result: ScreenshotIntelligenceResult | None = None,
    text: str | None = None,
    force_receipt: bool = False,
) -> DocumentIntelligenceResult:
    """Coordinate receipt and document intelligence extraction without AI APIs.

    Integrates:
    - Task 3A OCR text
    - Task 3B Screenshot intelligence signals
    - Task 3C Deterministic Receipt and Document parsers
    """
    raw_text, cleaned_text = _extract_raw_and_cleaned(ocr_result, text)

    # Handle empty or whitespace input
    if not cleaned_text.strip():
        return DocumentIntelligenceResult(
            status="unknown",
            document_type="unknown",
            receipt=None,
            document=None,
            warnings=["No readable text found in document OCR result"],
            confidence=0.0,
            explanation=["Empty input text provided"],
            raw_text=raw_text,
            normalized_text=cleaned_text,
        )

    # 1. Integrate Task 3B screenshot intelligence if not passed
    ss_category = "screenshot_unknown"
    if screenshot_result is not None:
        ss_category = screenshot_result.category
    else:
        # Run lightweight local classification
        ss_res = analyze_screenshot(cleaned_text)
        ss_category = ss_res.category

    # 2. Determine parsing priority
    # If Task 3B indicates receipt_candidate or force_receipt is True
    prioritize_receipt = force_receipt or (ss_category == "receipt_candidate")

    # Parse both structures deterministically
    receipt_data, receipt_warnings = parse_receipt_data(cleaned_text)
    doc_data, doc_warnings = parse_document_data(cleaned_text)

    # Decide primary document type based on signals and evidence
    explanation: list[str] = []
    warnings: list[str] = []

    # Check if receipt features are strong (merchant, total, subtotal, items)
    has_receipt_features = (
        receipt_data.total is not None
        and (receipt_data.merchant_name is not None or len(receipt_data.items) > 0 or receipt_data.subtotal is not None)
    )

    # Determine whether receipt or generic document takes precedence
    is_receipt = False
    if force_receipt:
        is_receipt = True
    elif doc_data.document_type == "invoice" and doc_data.confidence >= 0.50:
        is_receipt = False
    elif doc_data.document_type != "unknown" and doc_data.confidence > receipt_data.confidence:
        is_receipt = False
    elif ss_category == "document" and doc_data.document_type != "unknown":
        is_receipt = False
    elif has_receipt_features and receipt_data.confidence >= doc_data.confidence:
        is_receipt = True
    elif prioritize_receipt and receipt_data.confidence >= 0.60:
        is_receipt = True
    elif receipt_data.total is not None and doc_data.document_type == "unknown":
        is_receipt = True

    if is_receipt:
        doc_type = "receipt"
        confidence = receipt_data.confidence
        warnings.extend(receipt_warnings)

        if has_receipt_features and confidence >= 0.70:
            status = "classified"
            explanation.append(f"Classified as 'receipt' with strong evidence (confidence: {confidence:.2f})")
            if receipt_data.merchant_name:
                explanation.append(f"✓ Merchant: {receipt_data.merchant_name}")
            if receipt_data.total is not None:
                explanation.append(f"✓ Total: {receipt_data.currency} {receipt_data.total}")
            if receipt_data.items:
                explanation.append(f"✓ Items detected: {len(receipt_data.items)}")
        elif receipt_data.total is not None and not has_receipt_features:
            # Single total alone -> ambiguous!
            status = "ambiguous"
            explanation.append("Ambiguous receipt: contains total amount but lacks merchant or item evidence")
            confidence = min(0.40, confidence)
        else:
            status = "classified" if confidence >= 0.50 else "ambiguous"
            explanation.append(f"Identified as 'receipt' (confidence: {confidence:.2f})")

        primary_receipt = receipt_data
        primary_document = doc_data if doc_data.document_type != "unknown" else None

    else:
        doc_type = doc_data.document_type
        confidence = doc_data.confidence
        warnings.extend(doc_warnings)

        if doc_type != "unknown" and confidence >= 0.60:
            status = "classified"
            explanation.append(f"Classified as '{doc_type}' (confidence: {confidence:.2f})")
            if doc_data.document_number:
                explanation.append(f"✓ Document Number: {doc_data.document_number}")
            if doc_data.subject:
                explanation.append(f"✓ Subject: {doc_data.subject}")
        elif doc_type != "unknown":
            status = "ambiguous"
            explanation.append(f"Ambiguous '{doc_type}': weak structural signals")
        else:
            status = "unknown"
            doc_type = "unknown"
            confidence = 0.0
            explanation.append("Insufficient document or receipt structure detected")

        primary_receipt = receipt_data if receipt_data.total is not None else None
        primary_document = doc_data

    return DocumentIntelligenceResult(
        status=status,
        document_type=doc_type,
        receipt=primary_receipt,
        document=primary_document,
        warnings=warnings,
        confidence=confidence,
        explanation=explanation,
        raw_text=raw_text,
        normalized_text=cleaned_text,
    )


class DocumentIntelligenceAnalyzer:
    """Facade for Task 3C Document and Receipt Intelligence."""

    @staticmethod
    def analyze(
        ocr_result: OCRResult | dict[str, Any] | str | None = None,
        screenshot_result: ScreenshotIntelligenceResult | None = None,
        text: str | None = None,
    ) -> DocumentIntelligenceResult:
        return analyze_document(ocr_result=ocr_result, screenshot_result=screenshot_result, text=text)

    @staticmethod
    def analyze_receipt(text_or_ocr: Any) -> DocumentIntelligenceResult:
        return analyze_receipt(text_or_ocr)

    @staticmethod
    def parse_receipt(text_or_ocr: Any) -> ReceiptData:
        return parse_receipt(text_or_ocr)

    @staticmethod
    def parse_document(text_or_ocr: Any) -> DocumentData:
        return parse_document(text_or_ocr)

    @staticmethod
    def extract_line_items(text: str) -> list[ReceiptItem]:
        return extract_line_items(text)
