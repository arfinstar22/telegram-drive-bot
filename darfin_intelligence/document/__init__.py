"""Receipt and Document Intelligence Core package for Darfin Storage (Task 3C).

Provides deterministic rule-based analysis of receipts and formal documents.
100% local, zero AI APIs.
"""

from __future__ import annotations

from darfin_intelligence.document.models import (
    ReceiptItem,
    ReceiptData,
    DocumentData,
    DocumentIntelligenceResult,
    IntelligenceResult,
)
from darfin_intelligence.document.normalizer import (
    normalize_ocr_typos,
    clean_document_text,
)
from darfin_intelligence.document.amounts import (
    parse_money_value,
    extract_labeled_amounts,
    extract_all_standalone_amounts,
)
from darfin_intelligence.document.dates import (
    parse_iso_date,
    extract_document_dates,
    extract_labeled_date,
)
from darfin_intelligence.document.line_items import (
    extract_line_items,
    validate_item_arithmetic,
)
from darfin_intelligence.document.receipt_parser import (
    parse_receipt_data,
    extract_merchant_name,
    extract_payment_method,
)
from darfin_intelligence.document.document_parser import (
    parse_document_data,
    extract_document_number,
    extract_subject,
    extract_recipient,
    extract_sender,
    extract_attachment,
)
from darfin_intelligence.document.analyzer import (
    analyze_document,
    analyze_receipt,
    parse_receipt,
    parse_document,
    DocumentIntelligenceAnalyzer,
)

__all__ = [
    "ReceiptItem",
    "ReceiptData",
    "DocumentData",
    "DocumentIntelligenceResult",
    "IntelligenceResult",
    "normalize_ocr_typos",
    "clean_document_text",
    "parse_money_value",
    "extract_labeled_amounts",
    "extract_all_standalone_amounts",
    "parse_iso_date",
    "extract_document_dates",
    "extract_labeled_date",
    "extract_line_items",
    "validate_item_arithmetic",
    "parse_receipt_data",
    "extract_merchant_name",
    "extract_payment_method",
    "parse_document_data",
    "extract_document_number",
    "extract_subject",
    "extract_recipient",
    "extract_sender",
    "extract_attachment",
    "analyze_document",
    "analyze_receipt",
    "parse_receipt",
    "parse_document",
    "DocumentIntelligenceAnalyzer",
]
