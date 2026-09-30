# Darfin Search Intelligence Core (Task 4)

> **Architectural Component:** `darfin_intelligence.search`  
> **Status:** Completed & Verified  
> **Test Suite:** `test_search_intelligence.py` / `tests/test_search_intelligence.py` (65 tests, 100% pass)  
> **Zero External Calls:** 100% Local, Deterministic Lexical + Metadata Search (Zero AI/LLMs, Zero Vector DBs, Zero Elasticsearch/Meilisearch)

---

## 1. Overview & Honest Search Positioning

Task 4 implements the **Deterministic Search Intelligence Core** for Darfin Storage.

### What This Engine IS:
- A high-speed, local, multi-evidence search engine combining lexical token matching, exact filename scoring, folder hierarchy context, Task 1 technical media signals, Task 2A domain classifications, Task 3A/3B OCR and screenshot signals, Task 3C receipt and document structured metadata, deterministic fuzzy fallback, and user IDOR isolation.
- Fully transparent and explainable: every match reports exact score breakdowns, matched fields, and reasons.
- Lightweight: runs in < 15 ms across 500 candidate files on standard CPU, with < 1 MB memory overhead, ideal for Render Free 512 MB RAM environments.

### What This Engine IS NOT:
- **NOT an "AI Semantic Search"**: Does not call OpenAI, Gemini, Claude, OpenRouter, or external embedding endpoints.
- **NOT a "Vector Search"**: Does not run vector similarity algorithms or query Pinecone/Weaviate/pgvector.
- **NOT an external search cluster**: Does not require Elasticsearch, Opensearch, or Meilisearch.

---

## 2. Module Architecture

Package location: `darfin_intelligence/search/`

```
darfin_intelligence/search/
├── __init__.py           # Public exports (search, search_files, SearchService, models)
├── models.py             # Serializable dataclasses: SearchQuery, SearchFilters, SearchMatch, SearchResult
├── normalizer.py         # NFKC Unicode, lowercase, punctuation, media & semantic aliases, size/amount parsing
├── tokenizer.py          # Quoted phrase extraction, technical word boundary preservation
├── query_parser.py       # Key:value filter extraction (ext:, type:, folder:, domain:, date:, etc.)
├── filters.py            # Hard inclusion/exclusion evaluation gates (extension, family, domain, folder, size, date)
├── fuzzy.py              # SequenceMatcher ratio matching with length & similarity thresholds (min 0.80)
├── index.py              # IndexableFile pre-processor consolidating file attributes, notes, tags, metadata
├── scorer.py             # Multi-signal evidence accumulation and explainable scoring engine
└── service.py            # SearchService orchestrator with strict user scoping, IDOR protection, sorting & pagination
```

---

## 3. Query Syntax & Supported Filters

Users and programmatic clients can search with natural keywords or explicit deterministic operators:

| Operator | Example | Description |
|---|---|---|
| `ext:<ext>` | `ext:pdf`, `ext:mp4` | Matches file extension strictly |
| `type:<val>` | `type:video`, `type:document` | Matches file family or format |
| `folder:<val>` | `folder:Film`, `folder:"Semester 5"` | Matches folder name or nested folder path |
| `domain:<val>` | `domain:finance`, `domain:education` | Matches Task 2A classification domain |
| `document:<val>` | `document:invoice`, `document:academic_document` | Matches Task 3C document type |
| `merchant:<val>` | `merchant:indomaret` | Matches Task 3C extracted merchant name |
| `method:<val>` | `method:cash`, `method:qris` | Matches Task 3C payment method |
| `date:<val>` | `date:2026`, `date:2026-09`, `date:2026-09-30` | Matches created or document date |
| `after:<val>` | `after:2026-09-01` | Filters files created on or after date |
| `before:<val>` | `before:2026-10-01` | Filters files created on or before date |
| `size:<expr>` | `size:>10mb`, `size:<500kb` | Filters by file size range |
| `ocr:<bool>` | `ocr:true`, `ocr:false` | Filters files with or without OCR text |
| `"quoted phrase"` | `"Kupilih Jalur Langit"` | Exact phrase matching across filename, folder, or OCR |

Unknown filter expressions do not crash the engine; they are retained as normal search tokens.

---

## 4. Evidence Scoring & Ranking Formula

Every matching candidate receives a transparent evidence score:

$$\text{Score} = S_{\text{filename}} + S_{\text{folder}} + S_{\text{metadata}} + S_{\text{domain}} + S_{\text{document}} + S_{\text{ocr}} + S_{\text{fuzzy}} + S_{\text{coverage}} + S_{\text{recency}} + S_{\text{pref}} - P_{\text{conflict}}$$

### Baseline Field Weights:
- **Exact Filename Match:** `+100.0` (query matches filename stem exactly)
- **Multi-Token Query Substring:** `+65.0` (full multi-word query is substring of filename)
- **Quoted Phrase Match:** `+60.0` (in filename), `+40.0` (in folder), `+25.0` (in OCR)
- **Filename Token Match:** `+50.0` (exact token match), `+45.0` (punctuation-variant match e.g. `web-dl` ~ `web.dl`), `+35.0` (substring)
- **Folder Match:** `+45.0` (exact folder name), `+35.0` (folder path)
- **Tags & Notes:** `+40.0` (tag match), `+25.0` (note match)
- **Task 3C Document / Receipt Fields:** `+40.0` (merchant, receipt number, document number, subject, total amount)
- **Task 2A Domain Context:** `+35.0` (domain exact or domain keyword)
- **Task 3B Screenshot Category:** `+35.0` (reminder, conversation, webpage, code, etc.)
- **Extension / Family Match:** `+30.0`
- **OCR Text Match:** `+20.0 \times \min(1.0, \text{ocr\_confidence})` (dampened for low OCR quality)
- **Deterministic Fuzzy Match:** `+15.0 \text{ to } +25.0` (strictly below exact matches; only active when token has zero exact matches)
- **Multi-Token Coverage Bonus:** `+25.0` (all query tokens matched), `+15.0` (>= 70% coverage)
- **Recency Bonus:** `+4.0` (<= 7 days old), `+2.0` (<= 30 days old)
- **User Preference Bonus:** `+8.0` (matches Task 2D preferred folder or domain)
- **Conflict Penalty:** `-30.0` (e.g. query specifies `video` but file is `document`)

---

## 5. Security & Privacy Guarantees

1. **Strict User Isolation (IDOR Proof):**
   - Every search requires an authenticated integer `user_id > 0`.
   - Client-supplied `user_id` inside query strings or request bodies is strictly ignored.
   - Cross-user assets and cross-user folders are completely invisible.
2. **Sensitive Value Scrubbing:**
   - 13 to 19 digit credit card numbers are masked (`**** ****`).
   - OTP codes and verification tokens are never logged or exposed in highlights.
3. **Trash Protection:**
   - Trashed files (`is_trashed=True`) are excluded by default unless explicitly requested.

---

## 6. Sorting & Pagination

- **Sorting Modes:**
  - `relevance` (default): `(score DESC, created_at DESC, asset_id DESC)`
  - `newest`: `(created_at DESC, asset_id DESC)`
  - `oldest`: `(created_at ASC, asset_id ASC)`
  - `largest`: `(file_size DESC, asset_id DESC)`
  - `smallest`: `(file_size ASC, asset_id ASC)`
  - `name`: `(file_name ASC, asset_id ASC)`
- **Pagination:**
  - `limit`: clamped between 1 and 100 (default 25).
  - `offset`: non-negative integer.

---

## 7. Public API Usage

```python
from darfin_intelligence.search import search, search_files, SearchFilters, SearchService

# 1. Standard search for authenticated user
result = search(
    user_id=1001,
    query="invoice september ext:pdf",
    limit=25,
)

for match in result.items:
    print(match.asset_id, match.score, match.reasons)

# 2. Search with explicit programmatic filters
filters = SearchFilters(
    domain="finance",
    size_min=1024,
    size_max=10 * 1024 * 1024,
)
result = search(
    user_id=1001,
    query="laporan",
    filters=filters,
    sort_by="relevance",
)
```
