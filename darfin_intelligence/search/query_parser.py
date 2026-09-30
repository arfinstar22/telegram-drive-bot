"""Query parser for Darfin Search Intelligence Core.

Extracts explicit filter operators, date/amount entities, and search tokens.
"""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.search.models import SearchFilters, SearchQuery
from darfin_intelligence.search.normalizer import (
    normalize_search_string,
    parse_size_str,
    parse_amount_number,
)
from darfin_intelligence.search.tokenizer import tokenize_query

# Regex for key:value filter operators (supports quoted values e.g. folder:"Kuliah 5")
FILTER_REGEX = re.compile(r'\b([a-zA-Z_]+):(?:"([^"]+)"|([^\s]+))')


def parse_query(raw_query: str) -> SearchQuery:
    """Parse raw query string into structured SearchQuery with filters and tokens."""
    if not raw_query or not raw_query.strip():
        return SearchQuery(raw_query="", tokens=[], phrases=[], filters=SearchFilters())

    filters = SearchFilters()
    entities: dict[str, Any] = {}

    def _replace_filter(match: re.Match) -> str:
        key = match.group(1).lower()
        val = match.group(2) if match.group(2) is not None else match.group(3)
        val = val.strip()

        # Handle operators
        if key in ("ext", "extension"):
            filters.extension = val.lower().lstrip(".")
            return " "
        elif key in ("type", "family"):
            clean_val = val.lower().lstrip(".")
            if clean_val in ("pdf", "doc", "docx", "xls", "xlsx", "txt", "mp4", "mkv", "jpg", "png", "zip"):
                filters.extension = clean_val
            else:
                filters.family = clean_val
            return " "
        elif key == "folder":
            filters.folder_name = val
            return " "
        elif key == "domain":
            filters.domain = val.lower()
            return " "
        elif key in ("doc", "document", "document_type"):
            filters.document_type = val.lower()
            return " "
        elif key == "merchant":
            filters.merchant = val.lower()
            return " "
        elif key in ("method", "payment", "payment_method"):
            filters.payment_method = val.lower()
            return " "
        elif key == "ocr":
            filters.has_ocr = val.lower() in ("true", "1", "yes")
            return " "
        elif key == "date":
            # date:2026 or date:2026-09 or date:2026-09-30
            if re.match(r"^\d{4}$", val):
                filters.date_from = f"{val}-01-01"
                filters.date_to = f"{val}-12-31"
            elif re.match(r"^\d{4}-\d{2}$", val):
                filters.date_from = f"{val}-01"
                filters.date_to = f"{val}-31"
            else:
                filters.date_from = val
                filters.date_to = val
            return " "
        elif key in ("after", "from"):
            filters.date_from = val
            return " "
        elif key in ("before", "to"):
            filters.date_to = val
            return " "
        elif key == "size":
            if val.startswith(">"):
                filters.size_min = parse_size_str(val[1:])
            elif val.startswith("<"):
                filters.size_max = parse_size_str(val[1:])
            else:
                # default size:10mb -> max
                filters.size_max = parse_size_str(val)
            return " "

        # Unknown filter key: leave in search text so it doesn't crash or get lost
        return match.group(0)

    remaining_query = FILTER_REGEX.sub(_replace_filter, raw_query)
    remaining_clean = normalize_search_string(remaining_query)

    tokens, phrases = tokenize_query(remaining_clean)

    # Detect standalone amount expressions (e.g. "total 25000", "25.000", "Rp 25.000")
    for tok in list(tokens):
        amt = parse_amount_number(tok)
        if amt is not None and amt > 0:
            entities["amount"] = amt
            break

    # Detect standalone year/date in tokens (e.g. "2026")
    for tok in list(tokens):
        if re.match(r"^(19\d{2}|20\d{2})$", tok):
            entities["year"] = tok
            break

    return SearchQuery(
        raw_query=raw_query,
        tokens=tokens,
        phrases=phrases,
        filters=filters,
        entities=entities,
        normalized_query=remaining_clean,
    )
