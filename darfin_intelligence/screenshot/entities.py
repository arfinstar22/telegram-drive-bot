"""Entity extraction algorithms for Screenshot Intelligence (Task 3B).

Deterministic extraction for:
- Dates (relative and absolute)
- Times (normalized to HH:MM)
- Prices (structured currency and integer amounts)
- URLs
- Emails
- Phone numbers (Indonesian and international format)
- Merchants / Brands
- Codes (OTP / verification code, strictly masked for privacy)
- Sensitive card pattern detection
"""

from __future__ import annotations

import re
from typing import Any

from darfin_intelligence.screenshot.models import (
    ExtractedDate,
    ExtractedEntities,
    ExtractedPrice,
)

# Indonesian and English month name mapping
MONTH_MAP: dict[str, str] = {
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

# Known Indonesian and global retail / merchant brands
KNOWN_MERCHANTS: list[str] = [
    "indomaret", "alfamart", "alfamidi", "superindo", "hypermart", "carrefour",
    "transmart", "starbucks", "mcdonalds", "mcdonald's", "kfc", "hokben",
    "shopee", "tokopedia", "lazada", "bukalapak", "blibli", "grab", "gojek",
    "traveloka", "tiket.com", "kopi kenangan", "janji jiwa",
]


def extract_dates(text: str) -> list[ExtractedDate]:
    """Extract relative and absolute dates from text."""
    if not text:
        return []

    dates: list[ExtractedDate] = []
    seen: set[str] = set()

    # 1. Relative dates (Indonesian & English)
    rel_patterns = [
        (r"\b(hari\s+ini|today)\b", "today"),
        (r"\b(besok|tomorrow)\b", "tomorrow"),
        (r"\b(lusa|day\s+after\s+tomorrow)\b", "day_after_tomorrow"),
        (r"\b(kemarin|yesterday)\b", "yesterday"),
    ]
    for pattern, val in rel_patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            raw = m.group(1)
            key = f"rel:{val}"
            if key not in seen:
                seen.add(key)
                dates.append(ExtractedDate(type="relative", value=val, raw=raw))

    # 2. ISO format: YYYY-MM-DD
    for m in re.finditer(r"\b(20\d{2})[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12]\d|3[01])\b", text):
        y, mm, d = m.group(1), m.group(2), m.group(3)
        iso = f"{y}-{mm}-{d}"
        if iso not in seen:
            seen.add(iso)
            dates.append(ExtractedDate(type="absolute", value=iso, raw=m.group(0)))

    # 3. European / Indonesian format: DD-MM-YYYY or DD/MM/YYYY
    for m in re.finditer(r"\b(0[1-9]|[12]\d|3[01])[-/.](0[1-9]|1[0-2])[-/.](20\d{2})\b", text):
        d, mm, y = m.group(1), m.group(2), m.group(3)
        iso = f"{y}-{mm}-{d}"
        if iso not in seen:
            seen.add(iso)
            dates.append(ExtractedDate(type="absolute", value=iso, raw=m.group(0)))

    # 4. Textual format: DD [Month] YYYY (e.g. "30 Sep 2026", "15 Agustus 2026")
    month_regex = r"(?:jan(?:uari|uary)?|feb(?:ruari|ruary)?|mar(?:et|ch)?|apr(?:il)?|mei|may|jun(?:i|e)?|jul(?:i|y)?|agust(?:us)?|aug(?:ust)?|sep(?:tember)?|okt(?:ober)?|oct(?:ober)?|nov(?:ember)?|des(?:ember)?|dec(?:ember)?)"
    for m in re.finditer(rf"\b(0?[1-9]|[12]\d|3[01])\s+({month_regex})\s+(20\d{{2}})\b", text, re.IGNORECASE):
        d_str, mon_str, y_str = m.group(1), m.group(2).lower()[:3], m.group(3)
        mm = MONTH_MAP.get(mon_str, "01")
        d_fmt = f"{int(d_str):02d}"
        iso = f"{y_str}-{mm}-{d_fmt}"
        if iso not in seen:
            seen.add(iso)
            dates.append(ExtractedDate(type="absolute", value=iso, raw=m.group(0)))

    return dates


def extract_times(text: str) -> list[str]:
    """Extract and normalize times to HH:MM format."""
    if not text:
        return []

    times: list[str] = []
    seen: set[str] = set()

    # 1. 24-hour format: HH:MM or HH.MM (e.g. 10:00, 10.00, 22:30, pukul 10:00)
    for m in re.finditer(r"(?:pukul|jam)?\s*\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", text, re.IGNORECASE):
        h = int(m.group(1))
        m_val = int(m.group(2))
        normalized = f"{h:02d}:{m_val:02d}"
        if normalized not in seen:
            seen.add(normalized)
            times.append(normalized)

    # 2. 12-hour format with AM/PM (e.g. 10 AM, 10:30 PM, 8 am)
    for m in re.finditer(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b", text, re.IGNORECASE):
        h = int(m.group(1))
        m_val = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3).lower()
        if meridiem == "pm" and h < 12:
            h += 12
        elif meridiem == "am" and h == 12:
            h = 0
        normalized = f"{h:02d}:{m_val:02d}"
        if normalized not in seen:
            seen.add(normalized)
            times.append(normalized)

    return times


def extract_prices(text: str) -> list[ExtractedPrice]:
    """Extract structured currency prices (IDR and USD)."""
    if not text:
        return []

    prices: list[ExtractedPrice] = []
    seen: set[str] = set()

    # 1. Indonesian Rupiah: Rp 127.500, Rp127.500, Rp 1.250.000, IDR 127500
    rp_pattern = r"\b(?:Rp\.?|IDR)\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?|[0-9]+)\b"
    for m in re.finditer(rp_pattern, text, re.IGNORECASE):
        raw_num = m.group(1)
        # Strip thousand separator dot
        clean_num = raw_num.split(",")[0].replace(".", "")
        try:
            amount = int(clean_num)
            raw_str = m.group(0).strip()
            key = f"IDR:{amount}"
            if key not in seen:
                seen.add(key)
                prices.append(ExtractedPrice(currency="IDR", amount=amount, raw=raw_str))
        except ValueError:
            continue

    # 2. US Dollar: $ 127.50, $12.99, USD 100
    usd_pattern = r"(?:\$|USD)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+)\b"
    for m in re.finditer(usd_pattern, text, re.IGNORECASE):
        raw_num = m.group(1).replace(",", "")
        try:
            amount = float(raw_num) if "." in raw_num else int(raw_num)
            raw_str = m.group(0).strip()
            key = f"USD:{amount}"
            if key not in seen:
                seen.add(key)
                prices.append(ExtractedPrice(currency="USD", amount=amount, raw=raw_str))
        except ValueError:
            continue

    return prices


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text without fetching or crawling."""
    if not text:
        return []

    urls: list[str] = []
    seen: set[str] = set()

    # http://, https://, and www.
    url_pattern = r"(?:https?://[^\s<>'\"{}|\\^`]+|www\.[a-zA-Z0-9\-\._~:/?#\[\]@!$&'()*+,;=]+)"
    for m in re.finditer(url_pattern, text, re.IGNORECASE):
        u = m.group(0)
        # Strip trailing sentence punctuation
        u = re.sub(r"[.,;:!?)\]]+$", "", u)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)

    return urls


def extract_emails(text: str) -> list[str]:
    """Extract email addresses from text."""
    if not text:
        return []

    emails: list[str] = []
    seen: set[str] = set()

    email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    for m in re.finditer(email_pattern, text):
        e = m.group(0).lower()
        if e not in seen:
            seen.add(e)
            emails.append(e)

    return emails


def extract_phone_numbers(text: str) -> list[str]:
    """Extract Indonesian and international phone numbers."""
    if not text:
        return []

    phones: list[str] = []
    seen: set[str] = set()

    # +62 8xx or 08xx with optional hyphens/spaces
    phone_pattern = r"(?:\+62\s?|0)8[1-9][0-9\-\s]{7,12}\b"
    for m in re.finditer(phone_pattern, text):
        raw = m.group(0)
        # Normalize digits
        clean = re.sub(r"[\-\s]", "", raw)
        if 10 <= len(clean) <= 15 and clean not in seen:
            seen.add(clean)
            phones.append(clean)

    return phones


def extract_merchant(text: str) -> str | None:
    """Identify retail store or service merchant brand if present."""
    if not text:
        return None

    lower = text.lower()
    for brand in KNOWN_MERCHANTS:
        # Match as whole word
        if re.search(rf"\b{re.escape(brand)}\b", lower):
            # Return proper case (e.g. "Indomaret")
            return brand.capitalize()

    return None


def extract_codes_and_sensitive(text: str) -> tuple[list[str], bool]:
    """Extract verification/OTP codes (masked for privacy) and check credit card patterns."""
    if not text:
        return [], False

    codes: list[str] = []
    payment_sensitive = False

    # 1. OTP / verification code detection
    # Privacy rule: NEVER expose raw OTP in output or logs!
    otp_pattern = r"\b(?:otp|kode\s+verifikasi|verification\s+code|kode\s+otp)(?:[^\d\n]{0,30}?)\b([0-9]{4,8})\b"
    for m in re.finditer(otp_pattern, text, re.IGNORECASE):
        raw_code = m.group(1)
        # Mask code: e.g. "123456" -> "***456"
        masked = "*" * (len(raw_code) - 3) + raw_code[-3:] if len(raw_code) > 3 else "***"
        codes.append(f"OTP: {masked}")

    # 2. Payment card detection: 13 to 19 digits formatted or unformatted
    card_pattern = r"\b(?:\d{4}[ -]?){3}\d{1,4}\b"
    for m in re.finditer(card_pattern, text):
        clean_digits = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(clean_digits) <= 19:
            payment_sensitive = True
            break

    return codes, payment_sensitive


IGNORED_WORDS = frozenset({
    "http", "https", "jam", "pukul", "tanggal", "date", "time", "exp",
    "total", "subtotal", "qty", "harga", "price", "discount", "diskon",
    "nomor", "no", "perihal", "lampiran", "kepada", "status", "note", "notes",
    "card", "card number", "rekening", "kasir", "cashier", "merchant",
    "phone", "telepon", "email", "invoice", "reference", "ref", "otp",
    "kode", "code", "id", "transaksi", "penerima", "pengirim", "nominal",
    "saldo", "transfer", "tujuan", "sumber", "error", "typeerror", "valueerror",
    "syntaxerror", "nameerror", "attributeerror", "keyerror", "indexerror",
    "runtimeerror", "exception", "traceback", "file", "line", "warning",
    "info", "debug", "bank", "bca", "mandiri", "bri", "bni",
})


def extract_chat_names(text: str) -> list[str]:
    """Detect participant names in conversation/dialog screenshots."""
    if not text:
        return []

    names: list[str] = []
    seen: set[str] = set()

    # Lines starting with "Name:" or "Name :" (common chat transcript format)
    dialog_pattern = r"^[ \t]*([A-Z][a-zA-Z0-9_\-\s]{1,18}):"
    for line in text.splitlines():
        m = re.match(dialog_pattern, line)
        if m:
            name = m.group(1).strip()
            # Ignore common non-name headers, key-value labels, and stack traces
            words = name.lower().split()
            if not any(w in IGNORED_WORDS for w in words):
                if name not in seen:
                    seen.add(name)
                    names.append(name)

    return names


def extract_all_entities(text: str) -> ExtractedEntities:
    """Execute all entity extractors and return structured ExtractedEntities object."""
    dates = extract_dates(text)
    times = extract_times(text)
    prices = extract_prices(text)
    urls = extract_urls(text)
    emails = extract_emails(text)
    phones = extract_phone_numbers(text)
    merchant = extract_merchant(text)
    names = extract_chat_names(text)
    codes, payment_sensitive = extract_codes_and_sensitive(text)

    return ExtractedEntities(
        dates=dates,
        times=times,
        prices=prices,
        urls=urls,
        emails=emails,
        phone_numbers=phones,
        merchant=merchant,
        names=names,
        codes=codes,
        payment_sensitive=payment_sensitive,
    )
