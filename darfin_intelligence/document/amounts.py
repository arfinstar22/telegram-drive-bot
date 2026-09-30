"""Monetary and numerical amount extraction for Task 3C.

Deterministic parsing of Indonesian Rupiah (Rp, IDR) and foreign currencies ($, USD)
with safe handling of thousand-separator dots, decimal commas, and context labels.
"""

from __future__ import annotations

import re
from typing import Any

# Label regex patterns for monetary receipt fields
AMOUNT_LABEL_PATTERNS: list[tuple[str, str]] = [
    ("subtotal", r"\b(?:sub\s*total|sub-total)\b"),
    ("total", r"\b(?:grand\s+total|total\s+bayar|jumlah\s+bayar|total|jumlah)\b"),
    ("tax", r"\b(?:pajak|tax|ppn(?:\s*1[01]%)?|pb1)\b"),
    ("service_charge", r"\b(?:service\s+charge|service|biaya\s+layanan|layanan)\b"),
    ("discount", r"\b(?:discount|diskon|promo|hemat|potongan)\b"),
    ("paid_amount", r"\b(?:tunai\s+diterima|uang\s+tunai|bayar|tunai|cash|dibayar)\b"),
    ("change_amount", r"\b(?:kembalian|kembali|change)\b"),
]


def parse_money_value(raw_num: str, default_currency: str = "IDR") -> int | float | None:
    """Parse monetary string into clean int or float amount.

    Handles:
    - Indonesian dot thousand separators: '127.500' -> 127500, '1.250.000' -> 1250000
    - Indonesian comma decimals: '127.500,00' -> 127500, '12.500,50' -> 12500.5
    - Standard US format: '12,500.00' -> 12500, '12.99' -> 12.99
    - Simple digits: '127500' -> 127500
    """
    if not raw_num:
        return None

    s = raw_num.strip()
    # Strip currency prefixes if still attached
    s = re.sub(r"^(?:rp\.?|idr|\$|usd)\s*", "", s, flags=re.IGNORECASE).strip()

    if not s:
        return None

    # Case 1: Indonesian format with dot thousands and comma decimal, e.g. "127.500,00"
    if re.match(r"^\d{1,3}(?:\.\d{3})+,\d{2}$", s):
        clean = s.replace(".", "").replace(",", ".")
        val = float(clean)
        return int(val) if val.is_integer() else val

    # Case 2: Indonesian format with dot thousands, no decimal, e.g. "127.500" or "1.250.000"
    if re.match(r"^\d{1,3}(?:\.\d{3})+$", s):
        return int(s.replace(".", ""))

    # Case 3: Standard US format with comma thousands and dot decimal, e.g. "12,500.00"
    if re.match(r"^\d{1,3}(?:,\d{3})+\.\d{2}$", s):
        val = float(s.replace(",", ""))
        return int(val) if val.is_integer() else val

    # Case 4: Standard US format with comma thousands, no decimal, e.g. "12,500"
    if re.match(r"^\d{1,3}(?:,\d{3})+$", s):
        # In ID context with Indonesian currency, a single comma could sometimes be thousand in rare inputs,
        # but usually 12,500 is 12500
        return int(s.replace(",", ""))

    # Case 5: Decimal without thousands, e.g. "12.99"
    if re.match(r"^\d+\.\d{1,2}$", s):
        # In Indonesian receipt context, 3 digits after dot (e.g. 10.500) is thousand separator!
        # If default currency is IDR, check length of fractional part
        parts = s.split(".")
        if len(parts[1]) == 3 and default_currency == "IDR":
            return int(s.replace(".", ""))
        val = float(s)
        return int(val) if val.is_integer() else val

    # Case 6: Pure integer, e.g. "127500"
    if s.isdigit():
        return int(s)

    # Fallback: remove non-digit characters if reasonable
    cleaned = re.sub(r"[^\d.,]", "", s)
    if not cleaned:
        return None

    # Count dots and commas
    dots = cleaned.count(".")
    commas = cleaned.count(",")

    if dots > 1 and commas == 0:
        return int(cleaned.replace(".", ""))
    if commas > 1 and dots == 0:
        return int(cleaned.replace(",", ""))
    if dots == 1 and commas == 0:
        parts = cleaned.split(".")
        if len(parts[1]) == 3 and default_currency == "IDR":
            return int(cleaned.replace(".", ""))
        try:
            val = float(cleaned)
            return int(val) if val.is_integer() else val
        except ValueError:
            return None

    try:
        val = float(cleaned.replace(",", "."))
        return int(val) if val.is_integer() else val
    except ValueError:
        return None


def extract_labeled_amounts(text: str) -> list[dict[str, Any]]:
    """Scan text lines for labeled financial amounts."""
    if not text:
        return []

    labeled_results: list[dict[str, Any]] = []

    # Common money token pattern: optional Rp/$ followed by numbers with dots/commas
    money_regex = r"(?:(?:Rp\.?|IDR|\$|USD)\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+)\b"

    lines = text.split("\n")
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        lower_line = line_clean.lower()

        # Check which label matches this line
        matched_label: str | None = None
        for label_key, label_pat in AMOUNT_LABEL_PATTERNS:
            if re.search(label_pat, lower_line):
                matched_label = label_key
                break

        if not matched_label:
            continue

        # Currency detection on line
        curr = "USD" if ("$" in line or "usd" in lower_line) else "IDR"

        # Search for money values on this line
        # Pick the rightmost valid money amount (standard receipt column alignment)
        matches = list(re.finditer(money_regex, line_clean))
        if matches:
            last_match = matches[-1]
            raw_val = last_match.group(0).strip()
            amount = parse_money_value(raw_val, default_currency=curr)
            if amount is not None and amount > 0:
                labeled_results.append({
                    "label": matched_label,
                    "amount": amount,
                    "currency": curr,
                    "raw": raw_val,
                    "line": line_clean,
                })

    return labeled_results


def extract_all_standalone_amounts(text: str) -> list[dict[str, Any]]:
    """Extract explicit currency-prefixed amounts across text."""
    if not text:
        return []

    amounts: list[dict[str, Any]] = []
    # Requires explicit currency symbol (Rp, IDR, $, USD)
    explicit_pat = r"\b(Rp\.?|IDR|\$|USD)\s*([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|[0-9]+)\b"

    for m in re.finditer(explicit_pat, text, re.IGNORECASE):
        curr_symbol = m.group(1).upper()
        curr = "USD" if ("$" in curr_symbol or "USD" in curr_symbol) else "IDR"
        raw_val = m.group(2)
        amount = parse_money_value(raw_val, default_currency=curr)
        if amount is not None:
            amounts.append({
                "currency": curr,
                "amount": amount,
                "raw": m.group(0).strip(),
            })

    return amounts
