"""Data models for Darfin Search Intelligence Core.

Deterministic, serializable dataclasses representing queries, filters, matches, and results.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class SearchFilters:
    """Explicit search filters extracted from query operators or passed by caller."""
    extension: str | None = None
    mime_type: str | None = None
    family: str | None = None
    domain: str | None = None
    folder_id: int | None = None
    folder_name: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    size_min: int | None = None
    size_max: int | None = None
    has_ocr: bool | None = None
    document_type: str | None = None
    payment_method: str | None = None
    merchant: str | None = None
    currency: str | None = None
    is_trashed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchQuery:
    """Parsed and normalized search query."""
    raw_query: str
    tokens: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    filters: SearchFilters = field(default_factory=SearchFilters)
    entities: dict[str, Any] = field(default_factory=dict)
    normalized_query: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "tokens": list(self.tokens),
            "phrases": list(self.phrases),
            "filters": self.filters.as_dict(),
            "entities": dict(self.entities),
            "normalized_query": self.normalized_query,
        }


@dataclass
class SearchMatch:
    """Individual search match scoring a specific asset."""
    asset_id: int | str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    highlights: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    file_data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "score": round(self.score, 2),
            "matched_fields": list(self.matched_fields),
            "highlights": dict(self.highlights),
            "reasons": list(self.reasons),
            "confidence": round(self.confidence, 4),
            "file_data": dict(self.file_data),
        }


@dataclass
class SearchResult:
    """Paginated collection of ranked search matches."""
    items: list[SearchMatch] = field(default_factory=list)
    query: str = ""
    total_candidates: int = 0
    total_results: int = 0
    execution_time_ms: float = 0.0
    strategy: str = "deterministic_lexical_metadata"
    warnings: list[str] = field(default_factory=list)
    limit: int = 25
    offset: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "query": self.query,
            "total_candidates": self.total_candidates,
            "total_results": self.total_results,
            "execution_time_ms": round(self.execution_time_ms, 3),
            "strategy": self.strategy,
            "warnings": list(self.warnings),
            "limit": self.limit,
            "offset": self.offset,
        }
