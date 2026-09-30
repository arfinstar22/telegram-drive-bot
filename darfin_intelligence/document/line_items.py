"""Conservative receipt line-item extraction for Task 3C.

Parses item name, quantity, unit price, and total price with arithmetic validation
(quantity * unit_price ≈ total_price). Never fabricates structured values when uncertain.
"""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.document.amounts import parse_money_value
from darfin_intelligence.document.models import ReceiptItem

# Keywords that indicate non-item lines (headers, footers, totals, metadata)
HEADER_FOOTER_KEYWORDS = frozenset({
    "total", "subtotal", "sub-total", "grand total", "total bayar", "jumlah bayar",
    "pajak", "tax", "ppn", "service", "service charge", "biaya layanan",
    "diskon", "discount", "promo", "hemat", "potongan",
    "tunai", "cash", "bayar", "kembalian", "kembali", "change",
    "qris", "debit", "kredit", "kartu", "bca", "mandiri", "bri", "bni",
    "kasir", "cashier", "no.", "no:", "struk", "receipt", "order", "table", "meja",
    "tanggal", "tgl", "date", "time", "jam", "wib", "wita", "wit",
    "alamat", "jl.", "jalan", "telp", "phone", "terima kasih", "thank you",
    "selamat datang", "welcome", "npwp", "pos", "terminal", "member",
})


def is_header_or_footer_line(line: str) -> bool:
    """Check if line is a metadata header, summary total, or receipt footer."""
    lower = line.strip().lower()
    if not lower or len(lower) < 2:
        return True

    # Check separator lines (e.g. ===, ---, ***)
    if re.match(r"^[-=_*#\s]{3,}$", lower):
        return True

    # Check if starts with or is dominated by header/footer keywords
    for kw in HEADER_FOOTER_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            return True

    return False


def validate_item_arithmetic(qty: float, unit: int | float, total: int | float) -> bool:
    """Validate quantity * unit_price ≈ total_price with small tolerance for rounding."""
    expected = qty * unit
    diff = abs(expected - total)
    # Allow 2% or 50 currency units tolerance for rounding/OCR noise
    tolerance = max(50, total * 0.02)
    return diff <= tolerance


def extract_line_items(text: str) -> list[ReceiptItem]:
    """Conservatively extract receipt line items from OCR text."""
    if not text:
        return []

    items: list[ReceiptItem] = []
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # Skip lines until after receipt header, and stop once reaching totals
    in_items_section = False
    past_header = False

    # Regex patterns for line items:
    # 1. Standard: "Indomie Goreng  3 x 3.500  10.500" or "Aqua 600ml 2 x 4.000 8.000"
    p1 = re.compile(
        r"^([A-Za-z0-9\s/.,\-()]+?)\s+([0-9]+(?:\.[0-9]+)?)\s*[xX*]\s*(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)$"
    )

    # 2. Prefix qty: "1x Susu Rp 18.000" or "2x Roti Rp 12.000"
    p2 = re.compile(
        r"^([0-9]+(?:\.[0-9]+)?)\s*[xX]\s+([A-Za-z0-9\s/.,\-()]+?)\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)(?:\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+))?$"
    )

    # 3. Space-delimited columns: "Indomie Goreng 3 3500 10500"
    p3 = re.compile(
        r"^([A-Za-z0-9\s/.,\-()]+?)\s+([1-9][0-9]?)\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)$"
    )

    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Check if line indicates arrival at totals/summary section
        lower_line = line.lower()
        if any(re.search(rf"\b{kw}\b", lower_line) for kw in ("subtotal", "sub-total", "total", "grand total", "total bayar", "tunai", "cash")):
            # We reached totals section, stop parsing line items
            break

        if is_header_or_footer_line(line):
            i += 1
            continue

        # Try Pattern 1: Name [qty] x [unit_price] [total_price]
        m1 = p1.match(line)
        if m1:
            name = m1.group(1).strip()
            qty = float(m1.group(2))
            unit_price = parse_money_value(m1.group(3))
            total_price = parse_money_value(m1.group(4))

            conf = 0.70
            if unit_price is not None and total_price is not None:
                if validate_item_arithmetic(qty, unit_price, total_price):
                    conf = 0.95

            items.append(
                ReceiptItem(
                    name=name,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=total_price,
                    confidence=conf,
                )
            )
            i += 1
            continue

        # Try Pattern 2: [qty]x Name [price] [optional total]
        m2 = p2.match(line)
        if m2:
            qty = float(m2.group(1))
            name = m2.group(2).strip()
            p_val1 = parse_money_value(m2.group(3))
            p_val2 = parse_money_value(m2.group(4)) if m2.group(4) else None

            if p_val2 is not None:
                unit_price = p_val1
                total_price = p_val2
            else:
                # If only one price given, check if qty is 1
                if qty == 1.0:
                    unit_price = p_val1
                    total_price = p_val1
                else:
                    unit_price = None
                    total_price = p_val1

            conf = 0.85 if (unit_price and total_price and validate_item_arithmetic(qty, unit_price, total_price)) else 0.70
            items.append(
                ReceiptItem(
                    name=name,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=total_price,
                    confidence=conf,
                )
            )
            i += 1
            continue

        # Try Pattern 3: Name [qty] [unit_price] [total_price]
        m3 = p3.match(line)
        if m3:
            name = m3.group(1).strip()
            qty = float(m3.group(2))
            unit_price = parse_money_value(m3.group(3))
            total_price = parse_money_value(m3.group(4))

            if unit_price is not None and total_price is not None:
                if validate_item_arithmetic(qty, unit_price, total_price):
                    items.append(
                        ReceiptItem(
                            name=name,
                            quantity=qty,
                            unit_price=unit_price,
                            total_price=total_price,
                            confidence=0.90,
                        )
                    )
                    i += 1
                    continue

        # Try Multi-line Pattern (Name on line 1, "3 x 3.500" on line 2, "10.500" on line 3)
        if i + 2 < n:
            next_line = lines[i + 1]
            third_line = lines[i + 2]
            m_qty_unit = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*[xX*]\s*(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)$", next_line)
            m_tot = re.match(r"^(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})*|[0-9]+)$", third_line)

            if m_qty_unit and m_tot and not is_header_or_footer_line(line):
                name = line.strip()
                qty = float(m_qty_unit.group(1))
                unit_price = parse_money_value(m_qty_unit.group(2))
                total_price = parse_money_value(m_tot.group(1))

                conf = 0.90 if (unit_price and total_price and validate_item_arithmetic(qty, unit_price, total_price)) else 0.65
                items.append(
                    ReceiptItem(
                        name=name,
                        quantity=qty,
                        unit_price=unit_price,
                        total_price=total_price,
                        confidence=conf,
                    )
                )
                i += 3
                continue

        # Conservative fallback: if line has a product-like name and a single price at the end
        # e.g., "Kopi Kenangan Mantan 18.000"
        m_single = re.match(r"^([A-Za-z0-9\s/.,\-()]{3,35})\s+(?:Rp\.?\s*)?([0-9]{1,3}(?:[.,][0-9]{3})+)$", line)
        if m_single and not is_header_or_footer_line(line):
            name = m_single.group(1).strip()
            total_price = parse_money_value(m_single.group(2))
            items.append(
                ReceiptItem(
                    name=name,
                    quantity=1.0,
                    unit_price=total_price,
                    total_price=total_price,
                    confidence=0.60,
                )
            )
            i += 1
            continue

        i += 1

    return items
