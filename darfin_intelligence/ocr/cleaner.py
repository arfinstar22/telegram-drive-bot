"""Text cleaning and normalization for Local OCR Core (Task 3A).

Preserves:
- Numbers and digits
- Dates and timestamps
- Currency symbols (Rp, $, €, ¥, etc.)
- Special codes, document numbers, hyphens, colons, and punctuation
- Line and paragraph breaks

Does NOT perform aggressive semantic mutation or interpretation.
"""

from __future__ import annotations

import re


def clean_ocr_text(raw_text: str | None) -> str:
    """Normalize extracted OCR text while strictly preserving numbers, currency, and dates.

    Rules:
    - Normalizes CRLF and CR to LF (\\n)
    - Normalizes non-breaking and unusual unicode spaces to standard ASCII space
    - Collapses multiple horizontal spaces/tabs into a single space per line
    - Strips leading and trailing whitespace from each line
    - Collapses 3+ consecutive newlines into 2 (preserving paragraph breaks)
    - Leaves case, numbers, currency strings ("Rp 127.500"), and punctuation intact
    """
    if not raw_text:
        return ""

    # 1. Normalize line endings
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # 2. Normalize unicode spacing
    # Non-breaking spaces (\u00a0), zero-width space (\u200b), en/em space (\u2002-\u200a), ideographic space (\u3000)
    text = re.sub(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ", text)
    text = text.replace("\u200b", "")  # strip zero-width spaces

    # 3. Line by line horizontal whitespace collapsing
    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        clean_line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(clean_line)

    result = "\n".join(cleaned_lines)

    # 4. Collapse 3 or more consecutive newlines into 2
    result = re.sub(r"\n{3,}", "\n\n", result)

    # 5. Trim leading and trailing outer whitespace
    return result.strip()
