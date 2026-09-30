"""Receipt parsing and arithmetic reconciliation engine for Task 3C.

Extracts merchant, transaction timestamps, receipt numbers, totals, taxes,
discounts, payment methods, change amounts, and reconciles arithmetic consistency.
"""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.document.amounts import extract_labeled_amounts, parse_money_value
from darfin_intelligence.document.dates import extract_document_dates, parse_iso_date
from darfin_intelligence.document.line_items import extract_line_items
from darfin_intelligence.document.models import ReceiptData, ReceiptItem
from darfin_intelligence.document.normalizer import clean_document_text

KNOWN_RETAIL_MERCHANTS: list[str] = [
    "indomaret", "alfamart", "alfamidi", "super indo", "superindo", "hypermart",
    "carrefour", "transmart", "starbucks", "mcdonalds", "mcdonald's", "kfc",
    "hokben", "shopee", "tokopedia", "lazada", "bukalapak", "blibli", "grab",
    "gojek", "kopi kenangan", "janji jiwa", "chatime", "j.co", "point coffee",
    "famima", "family mart", "circle k", "lawson", "rotio", "roti'o", "breadtalk",
]

PAYMENT_METHODS_MAP: list[tuple[str, str]] = [
    ("qris", r"\bqris\b"),
    ("cash", r"\b(?:tunai|cash)\b"),
    ("bank_transfer", r"\b(?:transfer|bca|mandiri|bni|bri|permata|cimb)\b"),
    ("debit_card", r"\bdebit\b"),
    ("credit_card", r"\b(?:credit|kredit|kartu\s+kredit|visa|mastercard)\b"),
    ("e_wallet", r"\b(?:gopay|ovo|dana|shopeepay|linkaja|e-wallet|ewallet)\b"),
]


def extract_merchant_name(lines: list[str]) -> str | None:
    """Extract retail brand or business name from top header lines."""
    if not lines:
        return None

    # 1. Search for known retail brands in top 6 lines
    for line in lines[:6]:
        lower = line.lower()
        for brand in KNOWN_RETAIL_MERCHANTS:
            if re.search(rf"\b{re.escape(brand)}\b", lower):
                # Format proper casing (e.g. Indomaret, Super Indo)
                return " ".join(w.capitalize() for w in brand.split())

    # 2. Structural heuristics for unknown merchants
    # Check for PT / CV / UD / Toko / Store / Mart / Cafe / Resto
    merchant_prefix_pat = r"^(?:pt\.?|cv\.?|ud\.?|toko|warung|store|mart|cafe|kopi|resto|restoran|kedai)\s+([A-Za-z0-9\s&'\-]{2,30})"
    for line in lines[:5]:
        m = re.match(merchant_prefix_pat, line, re.IGNORECASE)
        if m:
            return line.strip()

    # 3. First non-empty uppercase line that isn't a receipt header or address
    for line in lines[:4]:
        s = line.strip()
        if (
            len(s) >= 3
            and not re.search(r"\b(total|subtotal|jumlah|bayar|tunai|cash|kembalian|change|diskon|discount|promo|pajak|tax|ppn|invoice|nomor|no\.|struk|nota|receipt|selamat|welcome|order|table|meja|kasir|cashier|jl|jalan)\b", s, re.IGNORECASE)
            and not re.match(r"^[-=_*#\s]{3,}$", s)
        ):
            # Check if majority uppercase letters
            letters = [c for c in s if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= 0.7:
                return s

    return None


def extract_merchant_address(lines: list[str]) -> str | None:
    """Extract street address from top lines."""
    for line in lines[:8]:
        s = line.strip()
        if re.search(r"\b(?:jl\.?|jalan|gedung|mall|plaza|blok|rt\.?|rw\.?|kec\.?|kel\.?|lantai|lt\.?)\b", s, re.IGNORECASE):
            return s
    return None


def extract_receipt_number(text: str) -> str | None:
    """Extract invoice/receipt transaction number."""
    pat = r"\b(?:no\.?\s*(?:struk|receipt|transaksi|trx|order|inv)?|order\s*id|trx\s*#)[:\s]*([A-Za-z0-9\-_/]{4,25})\b"
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        val = m.group(1).strip()
        # Avoid matching common words
        if val.lower() not in ("struk", "receipt", "order", "cashier", "kasir"):
            return val
    return None


def extract_transaction_time(text: str) -> str | None:
    """Extract and normalize transaction time to HH:MM."""
    # 24-hour format: HH:MM or HH.MM (e.g. 14:35, 10.00)
    for m in re.finditer(r"(?:jam|pukul|time)?\s*\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text, re.IGNORECASE):
        h = int(m.group(1))
        min_val = int(m.group(2))
        return f"{h:02d}:{min_val:02d}"

    # 12-hour format: 10 AM, 10:30 PM
    for m in re.finditer(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b", text, re.IGNORECASE):
        h = int(m.group(1))
        min_val = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3).lower()
        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
        return f"{h:02d}:{min_val:02d}"

    return None


def extract_payment_method(text: str) -> str:
    """Identify payment method from text cues."""
    lower = text.lower()
    for method, pat in PAYMENT_METHODS_MAP:
        if re.search(pat, lower):
            return method
    return "unknown"


def parse_receipt_data(text: str) -> tuple[ReceiptData, list[str]]:
    """Parse structured receipt details and warnings from OCR text."""
    warnings: list[str] = []
    cleaned = clean_document_text(text)
    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]

    # 1. Merchant info
    merchant_name = extract_merchant_name(lines)
    merchant_address = extract_merchant_address(lines)

    # 2. Receipt metadata
    receipt_no = extract_receipt_number(cleaned)
    date_candidates = extract_document_dates(cleaned)
    trx_date = date_candidates[0] if date_candidates else None
    trx_time = extract_transaction_time(cleaned)

    # 3. Labeled monetary amounts
    labeled_amounts = extract_labeled_amounts(cleaned)
    subtotal: int | float | None = None
    total: int | float | None = None
    tax: int | float | None = None
    service_charge: int | float | None = None
    discount: int | float | None = None
    paid_amount: int | float | None = None
    change_amount: int | float | None = None
    detected_currency = "IDR"

    for item in labeled_amounts:
        lbl = item["label"]
        amt = item["amount"]
        curr = item["currency"]
        if curr:
            detected_currency = curr

        if lbl == "subtotal" and subtotal is None:
            subtotal = amt
        elif lbl == "total" and total is None:
            total = amt
        elif lbl == "tax" and tax is None:
            tax = amt
        elif lbl == "service_charge" and service_charge is None:
            service_charge = amt
        elif lbl == "discount" and discount is None:
            discount = amt
        elif lbl == "paid_amount" and paid_amount is None:
            paid_amount = amt
        elif lbl == "change_amount" and change_amount is None:
            change_amount = amt

    # 4. Line items
    items = extract_line_items(cleaned)

    # If subtotal not found but line items have valid totals, calculate sum
    if subtotal is None and items:
        item_totals = [it.total_price for it in items if it.total_price is not None]
        if len(item_totals) == len(items) and item_totals:
            subtotal = sum(item_totals)

    # If total still None, but subtotal exists and no tax/discount
    if total is None and subtotal is not None and tax is None and discount is None:
        total = subtotal

    # 5. Payment method
    payment_method = extract_payment_method(cleaned)
    if payment_method == "unknown" and (paid_amount is not None or change_amount is not None):
        payment_method = "cash"

    # 6. Total Reconciliation & Arithmetic Verification (Section 6)
    arithmetic_valid = True
    if total is not None:
        # Check subtotal calculation: subtotal + tax + service - discount ≈ total
        if subtotal is not None:
            calc_tax = tax or 0
            calc_service = service_charge or 0
            calc_discount = discount or 0
            expected_total = subtotal + calc_tax + calc_service - calc_discount

            tolerance = max(50, total * 0.02)
            if abs(expected_total - total) > tolerance:
                warnings.append(
                    f"Reconciliation conflict: subtotal ({subtotal}) + tax ({calc_tax}) - discount ({calc_discount}) = {expected_total} != total ({total})"
                )
                arithmetic_valid = False

        # Check cash payment change: paid_amount - total ≈ change_amount
        if paid_amount is not None and change_amount is not None:
            expected_change = paid_amount - total
            if abs(expected_change - change_amount) > max(50, total * 0.02):
                warnings.append(
                    f"Change conflict: paid ({paid_amount}) - total ({total}) = {expected_change} != change ({change_amount})"
                )
                arithmetic_valid = False

    # 7. Confidence Scoring (Section 15 & 16)
    confidence = 0.0
    signals_count = 0

    if total is not None:
        confidence += 0.35
        signals_count += 1
    if subtotal is not None:
        confidence += 0.15
        signals_count += 1
    if merchant_name:
        confidence += 0.20
        signals_count += 1
    if items:
        confidence += 0.15
        signals_count += 1
    if payment_method != "unknown":
        confidence += 0.10
        signals_count += 1
    if receipt_no:
        confidence += 0.10
        signals_count += 1

    # Penalize if arithmetic check failed
    if not arithmetic_valid:
        confidence = max(0.35, confidence - 0.25)

    # Ambiguity check: single total alone with no merchant or items
    if signals_count <= 1 and total is not None:
        confidence = min(0.45, confidence)

    receipt_obj = ReceiptData(
        merchant_name=merchant_name,
        merchant_address=merchant_address,
        receipt_number=receipt_no,
        transaction_date=trx_date,
        transaction_time=trx_time,
        subtotal=subtotal,
        tax=tax,
        service_charge=service_charge,
        discount=discount,
        total=total,
        paid_amount=paid_amount,
        change_amount=change_amount,
        payment_method=payment_method,
        items=items,
        currency=detected_currency,
        confidence=min(0.98, round(confidence, 2)),
    )

    return receipt_obj, warnings
