# Darfin Screenshot Intelligence Core (Task 3B)

> **Architectural Component:** `darfin_intelligence.screenshot`  
> **Status:** Completed & Verified  
> **Test Suite:** `test_screenshot_intelligence.py` (38 tests, 100% pass)  
> **Zero External Calls:** 100% Local, Deterministic Rule-Based Processing (Zero AI/LLMs)

---

## 1. Overview & Mission

Task 3B introduces the **Screenshot Intelligence Core** to Darfin Storage. Building on the extracted text output of the **Task 3A Local OCR Core** (`OCRResult`), Task 3B parses screenshot text content deterministically to extract structured entities, categorize screenshot intent, compute classification confidence, evaluate competing signals, and explain decisions.

```
+-----------------------------------------------------------+
|               TASK 3A: LOCAL OCR ENGINE                   |
| Image -> Validation -> Local Tesseract/Mock -> OCRResult  |
+-----------------------------------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|         TASK 3B: SCREENSHOT INTELLIGENCE CORE             |
|                                                           |
| 1. Entity Extraction:                                     |
|    - Dates (relative & ISO)                               |
|    - Times (HH:MM normalized)                             |
|    - Prices (IDR & USD structured amount)                 |
|    - URLs, Emails, Indonesian Phones                      |
|    - Merchant Brands & Chat Participants                  |
|    - Masked OTPs & Payment Card Detection                 |
|                                                           |
| 2. Signal Engine & Scoring:                               |
|    - 13 Distinct Screenshot Categories                    |
|    - Multi-signal co-occurrence validation                |
|    - Ambiguity detection (close competing scores)         |
|    - OCR quality confidence dampening                     |
|                                                           |
| 3. Structured Result & Explanation:                       |
|    - ScreenshotIntelligenceResult                         |
+-----------------------------------------------------------+
```

---

## 2. Input Contract

The analyzer accepts three flexible input shapes without reading binary image files directly:
1. **`OCRResult` instance:** Direct output from Task 3A containing `raw_text`, `normalized_text`, and `confidence`.
2. **`str`:** Raw or pre-cleaned OCR text string.
3. **`dict`:** Serialized dictionary containing OCR fields.

```python
from darfin_intelligence.screenshot import analyze_screenshot

# From Task 3A OCRResult
result = analyze_screenshot(ocr_result)

# Or directly from string
result = analyze_screenshot("Rapat besok pukul 10:00")
```

---

## 3. Output Schema (`ScreenshotIntelligenceResult`)

```json
{
  "status": "classified",
  "category": "reminder",
  "confidence": 0.95,
  "entities": {
    "dates": [
      {
        "type": "relative",
        "value": "tomorrow",
        "raw": "besok"
      }
    ],
    "times": ["10:00"],
    "prices": [],
    "urls": [],
    "emails": [],
    "phone_numbers": [],
    "merchant": null,
    "names": [],
    "codes": [],
    "payment_sensitive": false
  },
  "signals": [
    {
      "category": "reminder",
      "signal": "event 'rapat/meeting'",
      "weight": 8,
      "strength": "moderate",
      "matched_text": "rapat"
    },
    {
      "category": "reminder",
      "signal": "date expression",
      "weight": 8,
      "strength": "moderate",
      "matched_text": "besok"
    },
    {
      "category": "reminder",
      "signal": "time expression",
      "weight": 10,
      "strength": "moderate",
      "matched_text": "10:00"
    },
    {
      "category": "reminder",
      "signal": "date + time co-occurrence",
      "weight": 10,
      "strength": "strong",
      "matched_text": "besok 10:00"
    }
  ],
  "evidence": [
    "Date detected: besok",
    "Time detected: 10:00",
    "Date (besok) and Time (10:00) co-occurring"
  ],
  "explanation": [
    "Category identified as 'reminder' (score: 36)",
    "✓ event 'rapat/meeting' (moderate, +8)",
    "✓ date expression (moderate, +8)",
    "✓ time expression (moderate, +10)",
    "✓ date + time co-occurrence (strong, +10)",
    "• Date detected: besok",
    "• Time detected: 10:00",
    "• Date (besok) and Time (10:00) co-occurring"
  ],
  "raw_text": "Rapat besok pukul 10:00",
  "normalized_text": "Rapat besok pukul 10:00",
  "ocr_confidence": null,
  "category_scores": {
    "reminder": 36
  }
}
```

---

## 4. Supported Categories

| Category | Description | Primary Signals |
|---|---|---|
| `conversation` | Chat apps (WhatsApp, Telegram, iMessage) | Multi-speaker dialogue lines (`Name:`), status phrases |
| `reminder` | Event or task scheduling | Co-occurrence of date, time, event (`rapat`, `meeting`, `agenda`) |
| `receipt_candidate` | POS store receipts, cash register printouts | `TOTAL`, `SUBTOTAL`, `KASIR`, `KEMBALIAN`, currency prices, store brand |
| `shopping` | E-commerce product/cart screens | `checkout`, `keranjang`, `promo`, `diskon`, `ongkir`, `beli sekarang` |
| `education` | Academic portals, course listings | `KRS`, `KHS`, `semester`, `mata kuliah`, `NPM/NIM`, `dosen`, `ujian` |
| `finance_candidate` | Bank account, balance statements | `saldo`, `mutasi rekening`, `transfer ke`, bank names (`BCA`, `Mandiri`) |
| `social_media` | Social platform posts or profiles | `followers`, `likes`, `komentar`, platform names (`Instagram`, `TikTok`) |
| `webpage` | Browser window or mobile browser screenshots | URLs, address bar patterns, domain names |
| `code` | Code editors, terminal output, stack traces | `def`, `class`, `import`, `Traceback`, `TypeError`, SQL queries |
| `document` | Formal administrative letters or decrees | `Nomor:`, `Perihal:`, `Lampiran:`, `Kepada Yth`, `Dengan hormat` |
| `notification` | System banners, verification alerts, OTP | `OTP`, `kode verifikasi`, `security alert`, `login baru` |
| `contact` | Contact cards, business cards | Co-occurrence of valid phone number and email address |
| `screenshot_unknown` | Unrecognized or insufficient text | Score < 6 across all categories |

---

## 5. Structured Entity Extraction

All entities are extracted deterministically with strict validation:

### Dates (`extract_dates`)
- **Relative Dates:** Indonesian (`hari ini`, `besok`, `lusa`, `kemarin`) and English (`today`, `tomorrow`, `yesterday`). Values normalized to semantic keys (`today`, `tomorrow`, `day_after_tomorrow`, `yesterday`).
- **ISO Formats:** `YYYY-MM-DD` (e.g. `2026-09-30`).
- **European / Indonesian Formats:** `DD/MM/YYYY` or `DD-MM-YYYY` (e.g. `30/09/2026` -> `2026-09-30`).
- **Textual Dates:** `DD [Month] YYYY` (e.g. `30 Sep 2026`, `15 Agustus 2026` -> `2026-08-15`).

### Times (`extract_times`)
- **24-hour Notation:** `10:00`, `10.00`, `22:30` -> normalized to standard `HH:MM`.
- **12-hour Notation:** `10 AM` -> `10:00`, `10:30 PM` -> `22:30`, `12 PM` -> `12:00`, `12 AM` -> `00:00`.

### Prices (`extract_prices`)
- **Indonesian Rupiah:** `Rp 127.500`, `Rp127.500`, `Rp 1.250.000`, `IDR 127500` -> normalized integer amount `127500`, currency `"IDR"`.
- **US Dollar:** `$ 12.99`, `USD 100` -> normalized amount, currency `"USD"`.

### URLs & Contacts
- **URLs (`extract_urls`):** `http://`, `https://`, `www.` detected without network fetching or crawling. Trailing punctuation stripped.
- **Emails (`extract_emails`):** RFC-compliant email detection without sending capabilities.
- **Phone Numbers (`extract_phone_numbers`):** Indonesian standard formats `08...`, `+628...` normalized without external contact lookup.
- **Merchants (`extract_merchant`):** Common retail chains recognized (`Indomaret`, `Alfamart`, `Superindo`, `Starbucks`, `KFC`, etc.).

---

## 6. Privacy & Sensitive Data Safety

Task 3B handles sensitive personal information with strict data-leakage guards:

1. **OTP & Verification Codes:**
   - Raw OTP digits are **never logged** or saved in plaintext.
   - Values are masked immediately: `OTP: 123456` -> `OTP: ***456`.
   - Log capture tests verify that raw OTP digits never appear in system logging output.
2. **Payment Card Numbers:**
   - 13 to 19 digit card number sequences are detected via regex.
   - Text is flagged with `entities.payment_sensitive = True`.
   - Card numbers are **never stored** in entities, codes, or logs.

---

## 7. Multi-Signal Scoring & Confidence Dampening

### The Multi-Signal Invariant
A single isolated keyword will never produce high classification confidence:
- `"meeting"` alone: score = 8 -> confidence ~ 0.40.
- `"Perusahaan akan rapat besok"`: `rapat` (+8) + `besok` (+8) = 16 -> confidence = 0.44 (moderate, NOT high confidence).
- `"Rapat besok pukul 10:00"`: `rapat` (+8) + `besok` (+8) + `10:00` (+10) + co-occurrence (+10) = 36 -> confidence = 0.95 (high confidence).

### Ambiguity Preservation
When two categories have close competing scores:
- Criterion: $\Delta_{\text{score}} \le 4$ or ($\Delta_{\text{score}} \le 6$ and $\text{ratio} < 1.35$).
- Behavior: `status = "ambiguous"`, and classification confidence is dampened by 35% (`confidence * 0.65`).
- Example: `"Promo besok"` triggers `shopping` (promo +6) and `reminder` (besok +8). With $\Delta = 2$, status becomes `"ambiguous"` with confidence dampened to `0.26`.

### OCR Quality Awareness
When input originates from an `OCRResult` with low OCR confidence:
- If `ocr_confidence < 0.60`, the classification confidence is dampened proportionally:
  $$\text{final\_confidence} = \text{classification\_confidence} \times \max(0.40, \text{ocr\_confidence})$$
- Example: The same reminder text with `ocr_confidence = 0.95` yields `0.95`, while with `ocr_confidence = 0.40` yields `0.38`.

---

## 8. Performance Benchmark

- **Test:** 10,000 OCR text strings evaluated sequentially in memory.
- **Duration:** 0.932 seconds.
- **Throughput:** **10,733 items/second**.
- **External Dependencies:** Zero (zero network calls, zero database calls).

---

## 9. Known Limitations & Next Steps

1. **Host OCR Dependency:** Task 3B processes text outputs; image-to-text accuracy depends on Task 3A's underlying OCR engine.
2. **No Autonomous Persistence:** Task 3B does not perform file movements, folder creations, or database modifications (reserved for user-reviewed workflows).
3. **Receipt Line Item Parsing:** Task 3B classifies `receipt_candidate` and extracts total/merchant; granular per-item receipt table parsing belongs to future financial intelligence tasks.
