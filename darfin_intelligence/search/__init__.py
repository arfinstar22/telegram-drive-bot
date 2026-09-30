"""Darfin Search Intelligence Core (Task 4).

Deterministic, local-only lexical and metadata search engine.
Zero external AI APIs, zero vector databases, zero cloud dependencies.
"""

from __future__ import annotations

from darfin_intelligence.search.models import (
    SearchFilters,
    SearchMatch,
    SearchQuery,
    SearchResult,
)
from darfin_intelligence.search.query_parser import parse_query
from darfin_intelligence.search.service import (
    SearchService,
    get_search_service,
    search,
    search_files,
)

__all__ = [
    "SearchFilters",
    "SearchMatch",
    "SearchQuery",
    "SearchResult",
    "SearchService",
    "get_search_service",
    "parse_query",
    "search",
    "search_files",
]
