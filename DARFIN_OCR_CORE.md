# Darfin Storage — Local OCR Core Architecture (Task 3A)

## 1. OCR Architecture

The Local OCR Core provides deterministic, 100% on-premise text extraction from local image files.
It operates with **zero cloud APIs, zero LLMs, zero embedding services, and zero external network calls**.

```
Local Image File
       │
Format & Security Validation
 (Extension, Size, Dimensions, DecompressionBomb Guard)
       │
Optional Preprocessing (Grayscale, Contrast)
       │
Local OCR Engine (Tesseract CLI / Mock Engine)
       │
Raw Text Extraction & TSV Confidence Parsing
       │
Text Normalization (clean_ocr_text)
 (Preserves currency, numbers, dates, punctuation)
       │
Structured OCRResult
 (status, raw_text, normalized_text, confidence, blocks, error_code)
```

---

## 2. Engine Abstraction

The OCR engine is abstracted behind `BaseOCREngine` to allow engine swapping without touching client code:
- **`BaseOCREngine`**: Abstract base class declaring `is_available()`, `get_version()`, `get_supported_languages()`, and `extract()`.
- **`LocalTesseractEngine`**: Calls the native `tesseract` binary directly via Python standard library `subprocess.run(..., timeout=...)`.
  - Captures TSV output format: parses words, line numbers, composite bounding boxes, and word-level confidences.
  - No bloated third-party wrapper dependencies.
- **`MockOCREngine`**: Deterministic in-memory engine for unit testing, offline CI, and predictable fixture validation.
- **`LocalOCREngine` / `OCRService`**: Orchestrator handling file existence, format verification, size limits, dimension limits, hash generation, and fail-safe execution.

---

## 3. Supported Input

- **Supported File Formats:** `JPG`, `JPEG`, `PNG`, `WEBP` (case-insensitive).
- **Unsupported Formats:** `PDF`, `MP4`, `TXT`, `DOCX`, etc.
  - Return: `status="unsupported_format"`, `error_code="UNSUPPORTED_FORMAT"`.
  - Never raises unhandled exceptions.
- **Input Source:** Pure local filesystem path (`image_path`). Zero implicit Telegram downloads.

---

## 4. Output: Structured `OCRResult` Model

```python
@dataclass
class OCRBlock:
    text: str
    confidence: float                  # Line confidence (0.0 to 100.0)
    line_num: int | None = None
    bbox: tuple[int, int, int, int] | None = None  # (left, top, width, height)

@dataclass
class OCRResult:
    status: str                        # "success" | "failed" | "rejected" | "timeout" | "unsupported_format"
    raw_text: str = ""                 # Exact original output
    normalized_text: str = ""          # Cleaned whitespace, preserved numbers/currency
    language: str = "eng"
    confidence: float | None = None    # Composite OCR confidence (0.0 to 1.0)
    engine: str = "tesseract"
    engine_version: str | None = None
    processing_time_ms: int = 0
    error_code: str | None = None      # Standardized safe error code
    error_message: str | None = None
    blocks: list[OCRBlock]             # Per-line bounding boxes and confidence
    image_hash: str | None = None      # SHA-256 for caching/tracking
    dimensions: tuple[int, int] | None = None
    file_size_bytes: int = 0
```

---

## 5. Preprocessing (Optional)

Preprocessing is controlled by `preprocess: bool = False` (default is False):
- Grayscale conversion: `image.convert("L")`
- Contrast enhancement: `ImageEnhance.Contrast(gray).enhance(1.4)`
- Preserves the original file on disk; operates via temporary files cleaned up in `finally` blocks.

---

## 6. Language Support

- Default language: `eng` (configurable via `OCR_DEFAULT_LANGUAGE` or parameter).
- Additional language packs (e.g. `ind` for Indonesian, `osd` for orientation/script) are supported when installed in the Tesseract data directory.
- `engine.get_supported_languages()` inspects installed language models via `tesseract --list-langs`.

---

## 7. Confidence & Text Cleaning

### Confidence Scoring
- Tesseract TSV output yields individual word confidences (0 to 100).
- Overall document confidence is computed as the average word confidence scaled to `0.0 - 1.0`.
- If an image contains no text, confidence is `None` or `0.0`.
- Confidence is strictly labeled **OCR confidence**, never AI confidence.

### Text Cleaning & Normalization (`clean_ocr_text`)
Strict non-aggressive preservation rules (Section 12):
- Normalizes CRLF / CR to `\n`.
- Normalizes non-breaking unicode spaces (`\u00a0`, `\u200b`, `\u3000`) to ASCII spaces.
- Collapses multiple horizontal spaces into a single space per line.
- Collapses 3+ consecutive newlines to 2, preserving paragraph breaks.
- **Strictly preserves:** numbers, currency strings (e.g. `"TOTAL Rp 127.500"` stays `"TOTAL Rp 127.500"`), dates, hyphens, colons, and punctuation.
- **Dual text output:** `raw_text` retains raw engine output; `normalized_text` provides standardized text for downstream tasks.

---

## 8. Resource Control & Limits

| Control | Default Setting | Action when Exceeded |
| :--- | :--- | :--- |
| **Max File Size** | 20 MB (`MAX_OCR_IMAGE_SIZE_MB`) | Status: `rejected`, `error_code="OCR_IMAGE_TOO_LARGE"` |
| **Max Dimension** | 10,000 px (`MAX_OCR_IMAGE_DIMENSION`) | Status: `rejected`, `error_code="OCR_IMAGE_DIMENSIONS_TOO_LARGE"` |
| **Max Pixels** | 25,000,000 px (`MAX_IMAGE_PIXELS`) | Status: `rejected`, `error_code="OCR_IMAGE_DIMENSIONS_TOO_LARGE"` |
| **Execution Timeout** | 15 seconds (`OCR_TIMEOUT_SECONDS`) | Status: `timeout`, `error_code="OCR_TIMEOUT"` |

---

## 9. Error Codes

All errors return structured codes without exposing raw internal tracebacks:
- `OCR_UNAVAILABLE`: Local OCR engine binary is not installed or available.
- `UNSUPPORTED_FORMAT`: File is not a supported image format.
- `OCR_IMAGE_TOO_LARGE`: Image exceeds maximum allowed file size.
- `OCR_IMAGE_DIMENSIONS_TOO_LARGE`: Image width, height, or pixel count exceeds bounds.
- `OCR_TIMEOUT`: OCR execution exceeded timeout limit.
- `OCR_ENGINE_ERROR`: Internal OCR binary or subprocess failure.
- `INVALID_IMAGE`: Corrupt, unreadable, or missing image file.

---

## 10. Security & Isolation

- **Telegram & Database Independent:** The OCR module has zero knowledge of Telegram users, Supabase schemas, folders, or share links.
- **Failure Boundary:** OCR is strictly a secondary background process. An OCR failure or timeout never breaks file uploads, Telegram message handling, or WebApp drive browsing.
- **DecompressionBomb Protection:** Pillow `MAX_IMAGE_PIXELS` limits memory allocation before pixel decompression.

---

## 11. Deployment Requirements

1. **Host System Package:**
   ```bash
   sudo apt-get update && sudo apt-get install -y tesseract-ocr tesseract-ocr-ind
   ```
2. **Python Environment:**
   ```bash
   pip install Pillow
   ```
3. **Configuration:**
   Set `OCR_ENABLED=true` in `.env` once Tesseract is installed. If Tesseract is not installed, `ocr_available()` cleanly returns `False` and storage continues uninterrupted.

---

## 12. Future Task Integration

- **Task 3B (Screenshot Intelligence):** Will parse `normalized_text` from `OCRResult` to identify chat receipts, notifications, and meeting reminders.
- **Task 3C (Receipt & Financial Parser):** Will parse structured lines, totals, dates, and merchant names from `OCRResult.blocks` and `normalized_text`.
