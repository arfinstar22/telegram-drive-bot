"""Darfin Intelligence — deterministic, rule-based file analysis engine.

No AI APIs, no external dependencies, no LLMs.
Uses MIME, extension, magic bytes, filename patterns, dictionaries,
and weighted signal scoring to classify and parse file metadata.
"""

from darfin_intelligence.models import IntelligenceResult
from darfin_intelligence.analyzer import analyze
from darfin_intelligence.classifier import classify, ClassificationResult, DomainClassifier
from darfin_intelligence.organizer import (
    map_folder,
    FolderSuggestion,
    FolderMapper,
    SafeOrganizer,
    OrganizationPlan,
    OrganizationItem,
    create_plan,
    preview,
)
from darfin_intelligence.preferences import (
    UserPreference,
    PreferenceEngine,
    apply_preferences,
)
from darfin_intelligence.ocr import (
    OCRResult,
    OCRBlock,
    OCRService,
    ocr_available,
    ocr,
    extract_text,
    clean_ocr_text,
)
from darfin_intelligence.screenshot import (
    ScreenshotIntelligenceResult,
    ScreenshotAnalyzer,
    analyze_screenshot,
)
from darfin_intelligence.document import (
    DocumentIntelligenceResult,
    ReceiptData,
    ReceiptItem,
    DocumentData,
    DocumentIntelligenceAnalyzer,
    analyze_document,
    analyze_receipt,
    parse_receipt,
    parse_document,
    extract_line_items,
)
from darfin_intelligence.search import (
    SearchService,
    SearchQuery,
    SearchFilters,
    SearchMatch,
    SearchResult,
    search,
    search_files,
    get_search_service,
)

__all__ = [
    "analyze",
    "classify",
    "map_folder",
    "create_plan",
    "preview",
    "apply_preferences",
    "ocr",
    "extract_text",
    "ocr_available",
    "clean_ocr_text",
    "analyze_screenshot",
    "analyze_document",
    "analyze_receipt",
    "parse_receipt",
    "parse_document",
    "extract_line_items",
    "search",
    "search_files",
    "SearchService",
    "get_search_service",
    "SearchQuery",
    "SearchFilters",
    "SearchMatch",
    "SearchResult",
    "IntelligenceResult",
    "ClassificationResult",
    "FolderSuggestion",
    "DomainClassifier",
    "FolderMapper",
    "SafeOrganizer",
    "OrganizationPlan",
    "OrganizationItem",
    "UserPreference",
    "PreferenceEngine",
    "OCRResult",
    "OCRBlock",
    "OCRService",
    "ScreenshotIntelligenceResult",
    "ScreenshotAnalyzer",
    "DocumentIntelligenceResult",
    "ReceiptData",
    "ReceiptItem",
    "DocumentData",
    "DocumentIntelligenceAnalyzer",
]
__version__ = "4.0.0"




