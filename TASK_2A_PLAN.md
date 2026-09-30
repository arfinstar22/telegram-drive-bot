# MASTER PLAN & ARCHITECTURE ROADMAP: DARFIN STORAGE INTELLIGENCE

> **Document Version:** 2.0 (Task 2A Active)  
> **Repository:** `arfinstar22/telegram-drive-bot` (/home/darfinstar/projectTelegram)  
> **Context Retention Notice:** This document serves as the persistent anchor for current and subsequent agent sessions. When resuming in a new chat, read this document first.

---

## 1. Project Background & System State

Darfin Storage is a hybrid Cloud Storage platform built with:
- **Telegram Bot Backend:** Python 3 + `python-telegram-bot` (handles file storage on Telegram servers, message interactions, Reply Keyboard).
- **Metadata Database:** Supabase PostgreSQL (`database.py` with files, folders, users, share links).
- **Web Interface:** Tornado web server (`webapp.py` with vanilla HTML/JS WebApp, REST APIs, Dropzone).
- **Security Hardening (Completed & Verified):**
  - Session authentication via Telegram WebApp initData HMAC-SHA256.
  - Ownership & IDOR protection on all endpoints (`/api/drive`, `/api/download`, `/api/batch_move`, etc.).
  - Security headers, CORS restrictions, path traversal guards, upload limit guards, and brute-force rate limiters.
  - 54 regression and adversarial tests continuously verified (`test_security.py`, `test_adversarial.py`).
- **Reply Keyboard & WebApp Launch Bridge (Verified):**
  - Permanent Reply Keyboard in Telegram chat: `[ 📱 Buka WebApp Drive ]`, `[ 📁 File Saya ]`, etc.
  - Clicking `[ 📱 Buka WebApp Drive ]` triggers `open_webapp_prompt` replying with an Inline Keyboard button with `web_app=WebAppInfo(...)`.
  - Zero URL parameter tampering, zero client-provided user_id trusting.

---

## 2. Intelligence Evolution Roadmap (No AI APIs, 100% Local & Deterministic)

The intelligence architecture runs completely offline using deterministic heuristics, signal engines, dictionaries, and rule-based models (zero LLMs, zero API keys, zero external SaaS):

| Phase | Module | Status | Description |
|---|---|---|---|
| **TASK 1** | `darfin_intelligence` Core | **COMPLETED (100%)** | Tokenizer, normalizer, dictionaries, media/generic parsers, 5-level signal engine, negative evidence, explain mode. 71 tests passing. |
| **TASK 2A** | `darfin_intelligence.classifier` | **COMPLETED (100%)** | Smart Domain Classifier: determines domain, category, confidence, ambiguity, and explanation based on `IntelligenceResult`. 44 tests passing. |
| **TASK 2B** | `darfin_intelligence.organizer` | **COMPLETED (100%)** | Smart Folder Mapping: pure read-only mapping of `ClassificationResult` to existing user folders with hierarchy, alias, ranking, and ambiguity. 34 tests passing. |
| **TASK 2C** | Safe File Organizer & Migration | **COMPLETED (100%)** | Safe Smart Organizer: dry-run plans, approval execution, security recheck, stale plan protection, audit logging. 34 tests passing. |
| **TASK 2D** | User Preferences & Feedback Engine | **COMPLETED (100%)** | Personal preferences, reusable pattern normalization, deterministic boost scaling, conflict resolution, stale folder safety, feedback API. 31 tests passing. |
| **TASK 3A** | Local OCR Core | **COMPLETED (100%)** | Local Tesseract OCR engine, BaseOCREngine abstraction, structured OCRResult, text cleaning, dimension/size limits, timeout. 34 tests passing. |
| **TASK 3B** | Screenshot Intelligence | **COMPLETED (100%)** | Deterministic screenshot classification, 13 categories, structured entities, multi-signal scoring, ambiguity dampening, privacy preservation. 38 tests passing. |
| **TASK 3C** | Receipt & Document Intelligence | **COMPLETED (100%)** | Local-only receipt & document intelligence core: conservative line items, total reconciliation, merchant detection, document fields, typo tolerance. 48 tests passing. |
| **TASK 4** | Search Intelligence Core | **COMPLETED (100%)** | Deterministic search intelligence: lexical token, exact, metadata, domain, folder context, OCR, Task 3B/3C entities, fuzzy, IDOR isolation. 65 tests passing. |
| **TASK 5** | Intelligent WebApp Features | PENDING | Visual badges, smart filters, domain views in WebApp UI. |

---

## 3. TASK 2A Technical Specification

### Objective
Build a modular domain classifier that takes `IntelligenceResult` (from Task 1) and outputs a structured `ClassificationResult`.

### Architecture Layout
```
darfin_intelligence/
├── __init__.py                # analyze, IntelligenceResult
├── models.py                  # Task 1 models
├── tokenizer.py               # Tokenizer
├── normalizer.py              # Canonical normalizer
├── dictionaries.py            # Extension, MIME, domain keywords
├── signals.py                 # Weighted evidence engine
├── parsers.py                 # Media, WhatsApp, generic parsers
├── analyzer.py                # Pipeline coordinator
└── classifier/                # TASK 2A MODULE
    ├── __init__.py            # classify, DomainClassifier, ClassificationResult
    ├── models.py              # ClassificationResult, Candidate
    ├── domain.py              # Domain definitions, word weights, category mappers
    └── scoring.py             # Score computation, candidate ranking, ambiguity, explain
```

### Supported Domains & Categories
- **`media`**: `movie`, `series`, `anime`, `tutorial`, `personal_video`, `unknown_video`.
- **`education`**: `academic`, `thesis`, `krs`, `assignment`, `exam`, `unknown_education`.
- **`office`**: `administrative`, `report`, `memo`, `contract`, `minutes`, `unknown_office`.
- **`finance`**: `invoice`, `receipt`, `tax`, `statement`, `payroll`, `unknown_finance`.
- **`identity`**: `id_card`, `passport`, `cv`, `license`, `certificate`, `unknown_identity`.
- **`health`**: `prescription`, `medical_record`, `lab_result`, `vaccine`, `unknown_health`.
- **`legal`**: `contract`, `permit`, `deed`, `court`, `unknown_legal`.
- **`project`**: `proposal`, `specification`, `documentation`, `wireframe`, `unknown_project`.
- **`personal`**: `personal_note`, `photo`, `recording`, `diary`, `unknown_personal`.
- **`unknown`**: Used when evidence is insufficient or completely ambiguous.

### Core Invariant & Evidence Hierarchy
$$\text{File Family} > \text{MIME / Extension} > \text{Technical Media Signals} > \text{Filename Structure} > \text{Domain Keywords}$$

- **Strong Keyword (+10):** `invoice`, `ktp`, `krs`, `sim`, `paspor`, `skripsi`.
- **Moderate Keyword (+6):** `kuliah`, `rapat`, `proposal`, `kontrak`, `dokter`.
- **Weak Keyword (+3):** `perusahaan`, `laporan`, `dokumen`, `rekap`.
- **Family Compatibility Bonus (+50 to +100):** If `family == 'video'` and media markers exist, `media` domain receives huge compatibility boost.
- **Family Conflict Penalty (-50):** Video files penalize non-media domains like `office`, ensuring `Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4` is classified as `media / movie`, NOT `office`.

### Ambiguity Decision Rule
If the difference between the top candidate score and second candidate score is smaller than the ambiguity threshold ($\Delta \le 3$ with low confidence), the result is set to:
```json
{
  "domain": null,
  "category": null,
  "status": "ambiguous",
  "candidates": [...]
}
```

---

## 4. Verification & Testing Strategy
1. **`test_classifier.py`**:
   - 30+ comprehensive unit and integration tests.
   - All 10 benchmark test cases from prompt Section 24.
   - Conflict resolution tests (`Laporan.Perusahaan...` -> `media`).
   - Ambiguity detection tests (`Project.2026.pdf` -> `ambiguous` or low confidence).
   - Image, audio, and archive categorization tests.
   - Benchmark test for 1,000 file classifications in < 0.2s.
2. **Regression Verification**:
   - All 54 security and adversarial tests (`test_security.py`, `test_adversarial.py`) must pass.
   - All 71 Task 1 intelligence tests (`test_intelligence.py`) must pass.
   - Combined total: 155+ passing tests.

---

## 5. Non-Negotiable Boundaries
- **NO file movement, renaming, deleting, or folder creation.**
- **NO database schema migration or mandatory write.**
- **NO changes to Telegram bot keyboard, chat handlers, or WebApp authentication.**
- **NO AI APIs or LLM dependencies.**
- **STOP immediately upon Task 2A completion and report.**
