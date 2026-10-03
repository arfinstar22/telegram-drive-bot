"""SearchService facade for Darfin Search Intelligence Core.

Coordinates query parsing, filtering, indexing, scoring, pagination, and user isolation.
"""

from __future__ import annotations

import re
import time
from typing import Any

from darfin_intelligence.search.filters import apply_filters
from darfin_intelligence.search.index import build_indexable_file
from darfin_intelligence.search.models import SearchFilters, SearchMatch, SearchResult
from darfin_intelligence.search.query_parser import parse_query
from darfin_intelligence.search.scorer import score_file


def _mask_sensitive_text(text: str) -> str:
    """Mask credit card numbers and OTP codes for privacy protection."""
    if not text:
        return ""
    # Mask 13-19 digit card numbers
    masked = re.sub(r"\b(?:\d[ -]*?){13,19}\b", "**** ****", text)
    # Mask OTP mentions
    masked = re.sub(r"\b(otp|kode verifikasi)\s*[:=]?\s*(\d{4,8})\b", r"\1: ****", masked, flags=re.IGNORECASE)
    return masked


class SearchService:
    """Deterministic, user-scoped search engine."""

    def __init__(self, db_module: Any = None) -> None:
        if db_module is not None:
            self.db = db_module
        else:
            try:
                import database as db
                self.db = db
            except ImportError:
                self.db = None

    def _retrieve_candidates(
        self,
        user_id: int,
        parsed_query: SearchQuery,
        active_filters: SearchFilters,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        seen_ids: set[Any] = set()
        candidates: list[dict[str, Any]] = []

        def _add_items(items: list[dict[str, Any]]) -> None:
            for item in items:
                if not isinstance(item, dict):
                    continue
                fid = item.get("id")
                if fid is not None and fid not in seen_ids:
                    uid = item.get("user_id")
                    if uid is not None and int(uid) != user_id:
                        continue
                    seen_ids.add(fid)
                    candidates.append(item)

        # Primary path: Fetch full user catalog via get_all_user_files (in-memory cached, paginated)
        if self.db and hasattr(self.db, "get_all_user_files"):
            try:
                all_files = self.db.get_all_user_files(
                    user_id,
                    limit=None,
                    is_trashed=active_filters.is_trashed,
                )
                if all_files:
                    _add_items(all_files)
                    return candidates
            except Exception as exc:
                warnings.append(f"get_all_user_files error: {exc}")

        # Fallback path if get_all_user_files is missing or throws error
        if self.db and hasattr(self.db, "db") and self.db.db is not None:
            try:
                base_rows = (
                    self.db.db.table("files")
                    .select("*, folders(name)")
                    .eq("user_id", user_id)
                    .eq("is_trashed", active_filters.is_trashed)
                    .order("created_at", desc=True)
                    .limit(1000)
                    .execute()
                    .data or []
                )
                _add_items(base_rows)
            except Exception as exc:
                warnings.append(f"DB fallback fetch error: {exc}")

        return candidates

    def search(
        self,
        user_id: int,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 25,
        offset: int = 0,
        sort_by: str = "relevance",
        assets: list[dict[str, Any]] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> SearchResult:
        """Execute deterministic search strictly scoped to user_id.

        Args:
            user_id: Authenticated user ID (must be positive integer).
            query: User search query string (supports operators like ext:pdf, folder:Film).
            filters: Optional programmatic SearchFilters.
            limit: Maximum items to return (1-100, default 25).
            offset: Zero-based item offset for pagination.
            sort_by: 'relevance' (default), 'newest', 'oldest', 'largest', 'smallest', 'name'.
            assets: Optional pre-loaded assets (for testing or memory search).
            preferences: Optional Task 2D user preferences.

        Returns:
            SearchResult with ranked SearchMatch items, execution time, and total counts.
        """
        start_time = time.perf_counter()
        warnings: list[str] = []

        # 1. Enforce user isolation & input validation
        if not isinstance(user_id, int) or user_id <= 0:
            return SearchResult(
                items=[],
                query=str(query or ""),
                total_candidates=0,
                total_results=0,
                execution_time_ms=0.0,
                warnings=["Invalid user_id: access denied"],
            )

        limit = min(100, max(1, int(limit)))
        offset = max(0, int(offset))

        # 2. Parse query and merge filters
        parsed_query = parse_query(query)
        active_filters = SearchFilters()

        # Merge filters: explicit arguments override query-parsed filters
        for f_key in active_filters.__dataclass_fields__:
            query_val = getattr(parsed_query.filters, f_key)
            if query_val is not None:
                setattr(active_filters, f_key, query_val)
            if filters is not None:
                arg_val = getattr(filters, f_key)
                if arg_val is not None:
                    setattr(active_filters, f_key, arg_val)

        # 3. Retrieve candidate assets
        candidates: list[dict[str, Any]] = []
        if assets is not None:
            # Strictly filter memory assets to user_id
            for a in assets:
                asset_uid = a.get("user_id")
                if asset_uid is not None and int(asset_uid) != user_id:
                    continue  # Strict IDOR prevention
                candidates.append(a)
        else:
            candidates = self._retrieve_candidates(user_id, parsed_query, active_filters, warnings)

        total_candidates = len(candidates)
        matches: list[SearchMatch] = []

        # 4. Filter and Score Candidates
        for item in candidates:
            # Hard filter gate
            passed, _reason = apply_filters(item, active_filters)
            if not passed:
                continue

            # Build indexable representation
            indexed = build_indexable_file(item)

            # Evidence scoring
            match = score_file(indexed, parsed_query, preferences=preferences)
            if match is not None:
                # Privacy scrub on reasons and highlights
                match.reasons = [_mask_sensitive_text(r) for r in match.reasons]
                match.highlights = {k: _mask_sensitive_text(v) for k, v in match.highlights.items()}
                matches.append(match)

        # 5. Deterministic Sorting
        if sort_by == "newest":
            matches.sort(key=lambda m: (str(m.file_data.get("created_at") or ""), str(m.asset_id)), reverse=True)
        elif sort_by == "oldest":
            matches.sort(key=lambda m: (str(m.file_data.get("created_at") or ""), str(m.asset_id)), reverse=False)
        elif sort_by == "largest":
            matches.sort(key=lambda m: (m.file_data.get("file_size", 0) or 0, str(m.asset_id)), reverse=True)
        elif sort_by == "smallest":
            matches.sort(key=lambda m: (m.file_data.get("file_size", 0) or 0, str(m.asset_id)), reverse=False)
        elif sort_by == "name":
            matches.sort(key=lambda m: ((m.file_data.get("file_name") or "").lower(), str(m.asset_id)), reverse=False)
        else:  # relevance
            matches.sort(key=lambda m: (m.score, str(m.file_data.get("created_at") or ""), str(m.asset_id)), reverse=True)

        # 6. Pagination
        total_results = len(matches)
        paginated_items = matches[offset: offset + limit]

        exec_ms = (time.perf_counter() - start_time) * 1000.0

        return SearchResult(
            items=paginated_items,
            query=parsed_query.raw_query,
            total_candidates=total_candidates,
            total_results=total_results,
            execution_time_ms=exec_ms,
            strategy="deterministic_lexical_metadata",
            warnings=warnings,
            limit=limit,
            offset=offset,
        )

    def search_files(self, user_id: int, query: str, **kwargs: Any) -> SearchResult:
        """Alias for search()."""
        return self.search(user_id=user_id, query=query, **kwargs)

    def search_by_filename(self, user_id: int, filename: str, **kwargs: Any) -> SearchResult:
        """Search specifically targeting filename."""
        return self.search(user_id=user_id, query=filename, **kwargs)

    def search_by_extension(self, user_id: int, ext: str, **kwargs: Any) -> SearchResult:
        """Search files by extension (e.g. 'pdf', 'mp4')."""
        filters = kwargs.pop("filters", None) or SearchFilters()
        filters.extension = ext.lower().lstrip(".")
        return self.search(user_id=user_id, query="", filters=filters, **kwargs)

    def search_by_folder(self, user_id: int, folder_id: int, **kwargs: Any) -> SearchResult:
        """Search files inside a specific folder."""
        filters = kwargs.pop("filters", None) or SearchFilters()
        filters.folder_id = folder_id
        return self.search(user_id=user_id, query="", filters=filters, **kwargs)

    def search_by_metadata(self, user_id: int, key: str, value: Any, **kwargs: Any) -> SearchResult:
        """Search files matching a specific metadata filter attribute."""
        filters = kwargs.pop("filters", None) or SearchFilters()
        if hasattr(filters, key):
            setattr(filters, key, value)
        return self.search(user_id=user_id, query="", filters=filters, **kwargs)


# Module-level singleton
_default_service: SearchService | None = None


def get_search_service() -> SearchService:
    global _default_service
    if _default_service is None:
        _default_service = SearchService()
    return _default_service


def search(
    user_id: int,
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 25,
    offset: int = 0,
    sort_by: str = "relevance",
    assets: list[dict[str, Any]] | None = None,
    preferences: dict[str, Any] | None = None,
) -> SearchResult:
    """Convenience functional interface for search."""
    return get_search_service().search(
        user_id=user_id,
        query=query,
        filters=filters,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        assets=assets,
        preferences=preferences,
    )


def search_files(user_id: int, query: str, **kwargs: Any) -> SearchResult:
    """Convenience functional interface for search_files."""
    return get_search_service().search_files(user_id=user_id, query=query, **kwargs)
