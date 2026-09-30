"""Text normalization and OCR error correction layer for Task 3C.

Deterministic token corrections for common OCR character substitutions
(0 for O, 1 for I/L, 4 for A, 8 for B) on high-confidence structural keywords.
"""

from __future__ import annotations

import re

# Deterministic OCR token replacement dictionary
OCR_TYPO_MAP: dict[str, str] = {
    # Receipt totals and payments
    "t0tal": "TOTAL",
    "subt0tal": "SUBTOTAL",
    "sub-t0tal": "SUBTOTAL",
    "kem8alian": "KEMBALIAN",
    "kem8ali": "KEMBALI",
    "tun4i": "TUNAI",
    "c4sh": "CASH",
    "k4sir": "KASIR",
    "d1skon": "DISKON",
    "pr0mo": "PROMO",
    "t4x": "TAX",
    "p4jak": "PAJAK",
    "ppn11": "PPN 11%",
    # Merchants
    "indom4ret": "INDOMARET",
    "alf4mart": "ALFAMART",
    "alf4midi": "ALFAMIDI",
    "st4rbucks": "STARBUCKS",
    # Document headers
    "n0mor": "NOMOR",
    "n0.": "NO.",
    "n0:": "NO:",
    "t4nggal": "TANGGAL",
    "per1hal": "PERIHAL",
    "l4mpiran": "LAMPIRAN",
    "1nvoice": "INVOICE",
    "inv0ice": "INVOICE",
    "kepad4": "KEPADA",
}


def normalize_ocr_typos(text: str) -> str:
    """Normalize common OCR misrecognitions for structural tokens.

    Preserves case and numbers across the rest of the text, only repairing
    known OCR substitution patterns on specific tokens.
    """
    if not text:
        return ""

    def replace_word(match: re.Match[str]) -> str:
        word = match.group(0)
        lower = word.lower()
        if lower in OCR_TYPO_MAP:
            return OCR_TYPO_MAP[lower]
        return word

    # Pattern matching alphanumeric words containing mixed digits/letters
    # e.g., T0TAL, SUBT0TAL, KEM8ALIAN
    pattern = r"\b[a-zA-Z0-9.:\-]{2,15}\b"
    return re.sub(pattern, replace_word, text)


def clean_document_text(text: str) -> str:
    """Perform basic spacing and OCR cleanup while preserving layout."""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Normalize weird unicode spaces
    text = re.sub(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ", text)
    text = text.replace("\u200b", "")

    # Apply OCR error normalization
    normalized = normalize_ocr_typos(text)

    # Trim spaces per line
    lines: list[str] = []
    for line in normalized.split("\n"):
        clean_line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(clean_line)

    return "\n".join(lines).strip()
