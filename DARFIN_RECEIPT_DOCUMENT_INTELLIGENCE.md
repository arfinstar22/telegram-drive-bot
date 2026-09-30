# Darfin Receipt & Document Intelligence Core (Task 3C)

> **Architectural Component:** `darfin_intelligence.document`  
> **Status:** Completed & Verified  
> **Test Suite:** `test_document_intelligence.py` (48 tests, 100% pass)  
> **Zero External Calls:** 100% Local, Deterministic Rule-Based Processing (Zero AI/LLMs/Cloud APIs)

---

## 1. Overview & Mission

Task 3C introduces the **Receipt & Document Intelligence Core** to Darfin Storage. Building on the extracted text output of the **Task 3A Local OCR Core** (`OCRResult`) and signals from the **Task 3B Screenshot Intelligence Core** (`ScreenshotIntelligenceResult`), Task 3C extracts rich, structured metadata from retail receipts and formal documents.

```
+-----------------------------------------------------------+
|               TASK 3A: LOCAL OCR ENGINE                   |
| Image -> Validation -> Local Tesseract/Mock -> OCRResult  |
+-----------------------------------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|         TASK 3B: SCREENSHOT INTELLIGENCE CORE             |
| OCRResult -> Category (e.g. receipt_candidate, document)  |
+-----------------------------------------------------------+
                             |
                             v
+-----------------------------------------------------------+
|     TASK 3C: RECEIPT & DOCUMENT INTELLIGENCE CORE         |
|                                                           |
| 1. Receipt Parsing:                                       |
|    - Merchant & Address (known retail + structure)        |
|    - Timestamps, Receipt Number                           |
|    - Monetary Extraction: Subtotal, Tax, Service Charge,  |
|      Discount, Total, Paid Amount, Change                 |
|    - Conservative Line Items (Name, Qty, Unit, Total)     |
|    - Arithmetic Validation & Total Reconciliation         |
|    - Payment Method Normalization                         |
|                                                           |
| 2. Formal Document Parsing:                               |
|    - Document Type Scoring (10 types)                     |
|    - Document Number (Nomor Surat, Invoice No, etc.)      |
|    - ISO Dates, Subject/Perihal, Attachment/Lampiran      |
|    - Recipient (Kepada Yth), Sender, Organization         |
|    - Contact Info (Emails, Phones)                        |
|                                                           |
| 3. Robust Local Normalization:                            |
|    - Deterministic OCR Typo Repair (T0TAL, KEM8ALIAN)     |
|    - Strict Privacy Masking (OTPs, PANs, credentials)     |
|    - Anti-Hallucination: No textual evidence -> None      |
|                                                           |
| 4. Output Data Structure:                                 |
|    - DocumentIntelligenceResult                           |
+-----------------------------------------------------------+
```

---

## 2. Module Architecture

Located in `darfin_intelligence/document/`:

| Module | Responsibility |
|---|---|
| [`models.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/models.py) | Dataclasses: `ReceiptItem`, `ReceiptData`, `DocumentData`, `DocumentIntelligenceResult` |
| [`normalizer.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/normalizer.py) | OCR typo replacement dictionary (`T0TAL` -> `TOTAL`, etc.) & whitespace cleaning |
| [`amounts.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/amounts.py) | Indonesian & US number/currency parser, labeled amount extractor |
| [`dates.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/dates.py) | Multi-format date parser (Indonesian & English textual months, numeric formats) |
| [`line_items.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/line_items.py) | Conservative receipt line-item parser with arithmetic verification |
| [`receipt_parser.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/receipt_parser.py) | Receipt entity extractor, merchant heuristics, payment method, total reconciliation |
| [`document_parser.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/document_parser.py) | Document classification and field extractor (`Nomor`, `Perihal`, `Kepada`, etc.) |
| [`analyzer.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/analyzer.py) | High-level facade integrating Task 3A & Task 3B inputs |
| [`__init__.py`](file:///home/darfinstar/projectTelegram/darfin_intelligence/document/__init__.py) | Clean exports of public functions and dataclasses |

---

## 3. Data Models

All models are `@dataclass` instances serializable to dictionaries using `as_dict()` or `dataclasses.asdict()`.

### `ReceiptItem`
- `name: str | None`
- `quantity: float | None`
- `unit_price: int | float | None`
- `total_price: int | float | None`
- `confidence: float`

### `ReceiptData`
- `merchant_name: str | None`
- `merchant_address: str | None`
- `receipt_number: str | None`
- `transaction_date: str | None`
- `transaction_time: str | None`
- `subtotal: int | float | None`
- `tax: int | float | None`
- `service_charge: int | float | None`
- `discount: int | float | None`
- `total: int | float | None`
- `paid_amount: int | float | None`
- `change_amount: int | float | None`
- `payment_method: str | None`
- `items: list[ReceiptItem]`
- `currency: str | None`
- `confidence: float`

### `DocumentData`
- `document_type: str | None`
- `document_number: str | None`
- `date: str | None`
- `subject: str | None`
- `sender: str | None`
- `recipient: str | None`
- `organization: str | None`
- `attachment: str | None`
- `names: list[str]`
- `reference_numbers: list[str]`
- `important_dates: list[str]`
- `important_amounts: list[dict]`
- `emails: list[str]`
- `phone_numbers: list[str]`
- `confidence: float`

### `DocumentIntelligenceResult`
- `status: str` (`"complete"`, `"partial"`, `"ambiguous"`, `"unknown"`, `"empty"`)
- `document_type: str` (`"receipt"`, `"official_letter"`, `"invoice"`, `"academic_document"`, etc.)
- `receipt: ReceiptData | None`
- `document: DocumentData | None`
- `warnings: list[str]`
- `confidence: float`
- `explanation: str`

---

## 4. Extraction Mechanics

### A. Receipt Parsing & Labeled Amounts
- Supports standard Indonesian financial labels:
  - Subtotal: `SUBTOTAL`, `SUB TOTAL`
  - Total: `TOTAL`, `GRAND TOTAL`, `TOTAL BAYAR`, `JUMLAH BAYAR`, `TAGIHAN`
  - Tax: `TAX`, `PAJAK`, `PPN`, `PB1`
  - Service: `SERVICE`, `SERVICE CHARGE`, `BIAYA LAYANAN`
  - Discount: `DISCOUNT`, `DISKON`, `PROMO`, `HEMAT`, `POTONGAN`
  - Paid: `TUNAI`, `CASH`, `BAYAR`, `DIBAYAR`, `TUNAI DITERIMA`
  - Change: `KEMBALIAN`, `KEMBALI`, `CHANGE`
- Monetary Normalization: Handles dot-thousands (`127.500`), comma-decimals (`12.500,00`), standard US (`12,500.00`), and integer values. Context and label proximity prevent arbitrary numeric strings from being interpreted as currency.

### B. Conservative Line-Item Extraction
- Multi-column and multi-line detection:
  - `Indomie Goreng 3 x 3.500 10.500`
  - `Aqua 600ml 2 x 4.000 8.000`
  - `1x Susu Kotak Rp 18.000`
- Arithmetic verification: checks `abs((quantity * unit_price) - total_price) <= max(1.0, total_price * 0.05)`.
- **Anti-fabrication invariant:** If an item name cannot be cleanly segregated, only textual evidence is stored as `name`, with `quantity`, `unit_price`, and `total_price` set to `None`.

### C. Total Reconciliation Engine
- Verifies arithmetic consistency:
  $$\text{subtotal} + \text{tax} + \text{service} - \text{discount} \approx \text{total}$$
  $$\text{paid\_amount} - \text{total} \approx \text{change\_amount}$$
- When values conflict:
  - Extracted values are preserved (no silent overwriting).
  - Explicit warning added to `warnings` list.
  - Overall confidence score is dampened.

### D. Merchant & Payment Method Recognition
- Known retail dictionary: Indomaret, Alfamart, Alfamidi, Hypermart, Carrefour, Transmart, Super Indo, Shopee, Tokopedia, Lazada, Blibli, KFC, McDonald's, Starbucks, etc.
- Heuristic fallback: Non-header uppercase tokens matching business naming conventions (`PT`, `CV`, `UD`, `Toko`, `Store`, `Mart`, `Cafe`).
- Payment method normalization: `cash`, `qris`, `bank_transfer`, `debit_card`, `credit_card`, `e_wallet`, or `unknown`.

### E. Document Field Extraction
- Recognized document types: `official_letter`, `invoice`, `academic_document`, `bank_document`, `proposal`, `certificate`, `form`, `contract`, `report`, `receipt`, `unknown`.
- Structural pattern extraction:
  - Document Number: `Nomor:`, `No:`, `Nomor Surat:`, `Invoice:`, `Invoice Number:`, `Reference:`, `Ref:`
  - Dates: `Tanggal:`, `Date:`, `Due Date:`
  - Subject: `Perihal:`, `Subject:`, `Hal:`
  - Attachment: `Lampiran:`, `Attachment:`
  - Recipient: `Kepada:`, `Kepada Yth:`, `To:`
  - Sender: `Dari:`, `From:`

---

## 5. Security & Privacy Protections

1. **Card Number Masking:** Payment card numbers detected via Luhn-compatible 16-digit patterns are scrubbed or masked (`**** 4567`). Never logged or exposed.
2. **OTP Redaction:** One-time passwords are never logged or stored.
3. **No Network / External API Calls:** All parsing runs on in-memory regex and string primitives.
4. **Denial of Service Guard:** Hard limits on input string size and regex execution.

---

## 6. Public API Reference

```python
from darfin_intelligence.document import (
    analyze_document,
    analyze_receipt,
    parse_receipt,
    parse_document,
    extract_line_items,
    DocumentIntelligenceAnalyzer,
)

# Comprehensive document analysis with optional Task 3A & Task 3B signals
result = analyze_document(
    ocr_result=ocr_result,
    screenshot_result=screenshot_result,
)

# Standalone receipt parsing
receipt_data = parse_receipt(raw_or_clean_text)

# Standalone document parsing
doc_data = parse_document(raw_or_clean_text)

# Standalone line item extraction
items = extract_line_items(text)
```
