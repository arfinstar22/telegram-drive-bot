"""Date extraction and ISO normalization for Task 3C.

Supports Indonesian and English month names, standard numerical formats
(YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY), and labeled document dates.
"""

from __future__ import annotations

import re
from typing import Any

# Map Indonesian and English month names to 2-digit representation
MONTH_NAME_MAP: dict[str, str] = {
    "jan": "01", "januari": "01", "january": "01",
    "feb": "02", "februari": "02", "february": "02",
    "mar": "03", "maret": "03", "march": "03",
    "apr": "04", "april": "04",
    "mei": "05", "may": "05",
    "jun": "06", "juni": "06", "june": "06",
    "jul": "07", "juli": "07", "july": "07",
    "agu": "08", "agustus": "08", "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "okt": "10", "oktober": "10", "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "des": "12", "desember": "12", "dec": "12", "december": "12",
}

MONTH_REGEX_STR = (
    r"(?:jan(?:uari|uary)?|feb(?:ruari|ruary)?|mar(?:et|ch)?|apr(?:il)?|mei|may|"
    r"jun(?:i|e)?|jul(?:i|y)?|agust(?:us)?|aug(?:ust)?|sep(?:tember)?|"
    r"okt(?:ober)?|oct(?:ober)?|nov(?:ember)?|des(?:ember)?|dec(?:ember)?)"
)


def parse_iso_date(raw_text: str) -> str | None:
    """Attempt to parse date string into strict ISO YYYY-MM-DD."""
    if not raw_text:
        return None

    s = raw_text.strip()

    # 1. ISO: YYYY-MM-DD or YYYY/MM/DD
    m_iso = re.search(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", s)
    if m_iso:
        return f"{m_iso.group(1)}-{m_iso.group(2)}-{m_iso.group(3)}"

    # 2. Textual: DD [Month] YYYY, e.g. "30 September 2026", "30 Sep 2026", "15 Agustus 2026"
    m_textual = re.search(
        rf"\b(0?[1-9]|[12]\d|3[01])\s+({MONTH_REGEX_STR})\s+(20\d{{2}})\b",
        s,
        re.IGNORECASE,
    )
    if m_textual:
        d = int(m_textual.group(1))
        mon_str = m_textual.group(2).lower()[:3]
        mm = MONTH_NAME_MAP.get(mon_str, "01")
        y = m_textual.group(3)
        return f"{y}-{mm}-{d:02d}"

    # 3. Textual inverted: [Month] DD, YYYY (e.g. "September 30, 2026")
    m_inv = re.search(
        rf"\b({MONTH_REGEX_STR})\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b",
        s,
        re.IGNORECASE,
    )
    if m_inv:
        mon_str = m_inv.group(1).lower()[:3]
        mm = MONTH_NAME_MAP.get(mon_str, "01")
        d = int(m_inv.group(2))
        y = m_inv.group(3)
        return f"{y}-{mm}-{d:02d}"

    # 4. Standard Indonesian / European: DD-MM-YYYY or DD/MM/YYYY or DD.MM.YYYY
    m_dmy = re.search(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2})\b", s)
    if m_dmy:
        d = int(m_dmy.group(1))
        mm = int(m_dmy.group(2))
        y = m_dmy.group(3)
        return f"{y}-{mm:02d}-{d:02d}"

    # 5. Short 2-digit year: DD/MM/YY (common on retail receipts, e.g. "30/09/26")
    m_short = re.search(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](2[0-9])\b", s)
    if m_short:
        d = int(m_short.group(1))
        mm = int(m_short.group(2))
        yy = int(m_short.group(3))
        return f"20{yy:02d}-{mm:02d}-{d:02d}"

    return None


def extract_document_dates(text: str) -> list[str]:
    """Extract all valid dates from document text normalized to ISO."""
    if not text:
        return []

    dates: list[str] = []
    seen: set[str] = set()

    for line in text.split("\n"):
        iso = parse_iso_date(line)
        if iso and iso not in seen:
            seen.add(iso)
            dates.append(iso)

    return dates


def extract_labeled_date(text: str) -> str | None:
    """Extract the primary date associated with Date/Tanggal headers."""
    if not text:
        return None

    # Check lines starting with date headers
    header_pattern = r"^(?:tanggal|tgl|date|tgl\s+surat)[:\s]+(.+)$"
    for line in text.split("\n"):
        m = re.match(header_pattern, line.strip(), re.IGNORECASE)
        if m:
            candidate = m.group(1)
            iso = parse_iso_date(candidate)
            if iso:
                return iso

    # Fallback to the first valid date in the text
    all_dates = extract_document_dates(text)
    return all_dates[0] if all_dates else None
