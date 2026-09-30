# Darfin Intelligence Core — Documentation

> **Status:** Task 1 Foundation Complete  
> **Engine Type:** Deterministic / Rule-Based Intelligence Engine (NO AI API, NO LLM, NO External Dependencies)

---

## 1. Architecture

Darfin Intelligence Core (`darfin_intelligence`) is a lightweight, zero-dependency, local analysis library engineered specifically for Darfin Storage. It processes incoming file metadata, tokenizes filenames, extracts structural tokens, resolves domain dictionaries, aggregates weighted evidence signals, and determines structured entity metadata without requiring any internet connection, GPU resources, or external AI APIs.

### Design Principles:
- **Zero AI Dependency:** Pure Python 3 standard library (`re`, `dataclasses`, `time`, `logging`).
- **Deterministic & Auditable:** Every decision produces a transparent, verifiable evidence chain.
- **Fail-Safe & Non-Blocking:** Errors in analysis never crash uploads or block user storage operations.
- **Strictly Read-Only in Task 1:** No automatic moving, renaming, or deleting of user files.
- **Null Over Guessing:** If evidence for an entity (e.g., resolution, codec, year) is insufficient, the field is left as `None`.

---

## 2. Processing Pipeline

The intelligence pipeline executes sequentially across ten stages:

```
File Upload (Telegram / WebApp)
       │
       ▼
1. Extract Extension & MIME
       │
       ▼
2. Filename Tokenization (Preserving compound tokens: WEB-DL, H.264, etc.)
       │
       ▼
3. Token Normalization (Resolving aliases & canonical representations)
       │
       ▼
4. FileTypeInfo Construction (Mapping MIME & Extension)
       │
       ▼
5. Evidence Signal Collection (Levels 1 to 5)
       │
       ▼
6. Negative Evidence & Contradiction Suppression
       │
       ▼
7. Signal Scoring & Confidence Computation
       │
       ▼
8. Family Classification Determination
       │
       ▼
9. Specialized Entity Parsing (Media / WhatsApp / Generic)
       │
       ▼
10. Final IntelligenceResult (with Explain / Evidence Chain)
```

---

## 3. File Type Detection

File families are mapped using a strict multi-tier hierarchy:
1. **Magic Bytes / File Signature (Level 5, +100):** Raw binary verification when payload stream is available.
2. **MIME Type (Level 4, +80):** Canonical MIME families (`video/`, `image/`, `audio/`, `application/pdf`, etc.).
3. **Telegram Message Type (Level 3.5, +35):** Telegram API primitive category (`video`, `photo`, `audio`, `document`).
4. **Extension Family (Level 3, +30):** Normalized extension lookup against 60+ known extensions.
5. **Technical Filename Markers (Level 2, +15):** Markers such as `1080p`, `WEB-DL`, `x264`.

MIME and strong technical signals strictly override misleading filename tokens (e.g., `report.pdf.mp4` with `video/mp4` MIME correctly classifies as `video`).

---

## 4. Filename Tokenizer & Normalizer

### Tokenizer (`tokenizer.py`)
- Splits on common separators: `.`, `_`, `-`, ` `, `[`, `]`, `(`, `)`, `{`, `}`.
- **Compound Token Protection:** Protects compounds such as `WEB-DL`, `Blu-Ray`, `H.264`, `x265`, `TrueHD`, `Dolby-Digital`, `Dolby-Atmos` from being split into fragments.
- Isolates file extensions accurately without stripping embedded dots in release titles.

### Normalizer (`normalizer.py`)
Provides deterministic canonicalization:
- **Resolutions:** `4k`, `uhd`, `2160p` → `2160p`; `1080p`, `fhd` → `1080p`; `720p`, `hd` → `720p`.
- **Sources:** `webdl`, `web-dl` → `WEB-DL`; `bluray`, `blu-ray` → `BluRay`; `webrip` → `WEBRip`.
- **Video Codecs:** `h264`, `h.264`, `avc` → `H.264`; `h265`, `h.265`, `hevc` → `HEVC`; `x264` → `x264`.
- **Audio Codecs:** `aac` → `AAC`; `ac3` → `AC3`; `eac3`, `e-ac3` → `EAC3`; `dts` → `DTS`; `flac` → `FLAC`.

---

## 5. Dictionary Architecture

Dictionaries are organized in `dictionaries.py` by specialized domains:
- **`EXTENSION_FAMILIES`**: Comprehensive mapping of media, documents, archives, and binaries.
- **`MIME_FAMILY_MAP`**: Complete mapping of standard MIME types to families.
- **`MEDIA_TECHNICAL_SIGNALS`**: Set of recognized scene and release markers.
- **`DOMAIN_KEYWORDS`**:
  - `education`: `kuliah`, `tugas`, `krs`, `skripsi`, `tesis`, `praktikum`, `kkn`, `proposal`, etc.
  - `office`: `perusahaan`, `kantor`, `pegawai`, `rapat`, `kontrak`, `notulen`, `brief`, etc.
  - `finance`: `invoice`, `kwitansi`, `receipt`, `pajak`, `faktur`, `gaji`, `mutasi`, etc.
  - `identity`: `ktp`, `sim`, `paspor`, `npwp`, `kk`, `skck`, `cv`, `resume`, etc.
  - `health`: `resep`, `dokter`, `rontgen`, `vaksin`, `swab`, `pcr`, etc.
  - `media`: `movie`, `film`, `series`, `episode`, `season`, `drakor`, `anime`, etc.

---

## 6. Signal & Evidence Engine

### Signal Model:
Each signal represents an atomic unit of proof:
- `source`: `"mime"`, `"extension"`, `"telegram_type"`, `"technical_marker"`, `"domain_keyword"`, `"negative_evidence"`.
- `category`: Target file family or domain.
- `value`: Original token or string that triggered the signal.
- `weight`: Signed integer score.
- `level`: Hierarchy tier (1 to 5).

### Strong vs. Weak Signals:
- Strong signals (MIME, container, technical markers) represent definitive container/format proof.
- Weak signals (domain keywords like `"perusahaan"`, `"tugas"`) represent semantic context.
- **Core Invariant:** Weak signals never override strong format evidence.

### Negative Evidence:
When strong media evidence (e.g. `video` score ≥ 30 from markers and container) is present, contradictory domain keywords (like `"perusahaan"` or `"kuliah"`) generate a negative penalty signal (`negative_evidence`, weight = -3), suppressing false positive document classifications while preserving the semantic marker as `weak`.

---

## 7. Parsers

### Media Filename Parser (`parse_media_filename`)
Parses standard scene and media release patterns:
- Walks tokens left-to-right.
- Everything preceding the first technical marker or release year is extracted as `title`.
- Extracts `year`, `resolution`, `source`, `codec`, `audio_codec`, `season`, `episode`, and `release_group`.

### WhatsApp & Device Parser (`parse_whatsapp_filename`)
Recognizes automated camera and messaging formats:
- `VID_YYYYMMDD_WAxxxx` → WhatsApp Video (with captured date/year).
- `IMG_YYYYMMDD_WAxxxx` → WhatsApp Photo.
- `AUD-YYYYMMDD-WAxxxx` → WhatsApp Audio.
- `Screenshot_YYYYMMDD_xxxx` → Screenshot.

### Generic Document Parser (`parse_generic_filename`)
Handles clean document naming, separating human title from embedded calendar years.

---

## 8. Confidence Scoring & Explain Mode

### Confidence Calculation:
Normalized probability distribution across competing file families:
$$\text{confidence}[family] = \frac{\text{score}[family]}{\sum \text{family\_scores}}$$

### Explain Mode (`result.explain()`):
Generates a human-readable audit trail showing:
1. Detected family and parser.
2. Full evidence chain with weights and hierarchy levels.
3. Score totals per category.
4. Extracted structured entities.
5. Confidence percentages.

---

## 9. Examples

### Example 1: Standard Media Release
- **Input:** `Ku.Pilih.Jalur.Langit.2026.1080p.WEB-DL.x264.AAC.mkv`
- **Family:** `video` (Confidence: 1.0)
- **Entities:**
  - Title: `Ku Pilih Jalur Langit`
  - Year: `2026`
  - Resolution: `1080p`
  - Source: `WEB-DL`
  - Codec: `x264`
  - Audio: `AAC`
  - Container: `mkv`

### Example 2: False Positive Protection (The Critical Benchmark)
- **Input:** `Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4`
- **Family:** `video` (Strong technical markers + MP4 container outweigh "Perusahaan" and "PDF")
- **Entities:**
  - Title: `Perusahaan Corporat PDF`
  - Year: `2026`
  - Resolution: `2160p`
  - Source: `WEB-DL`
- **Signals:** `office/weak` retained for semantic search without corrupting file family.

### Example 3: Academic / Corporate Document
- **Input:** `Proposal.Perusahaan.2026.pdf`
- **Family:** `document`
- **Entities:** Title: `Proposal Perusahaan`, Year: `2026`
- **Domain Signals:** `proposal` (`education/strong`), `perusahaan` (`office/strong`).

---

## 10. Real Project Integration (Task 1: Read-Only)

Integrated non-blockingly into:
1. **WebApp Upload Pipeline (`webapp.py` → `ApiUploadHandler`):**
   Runs right after file and metadata are committed to storage.
2. **Telegram Bot Pipeline (`handlers/files.py` → `save_file` batch handler):**
   Executes analysis immediately upon message receipt.

**Failure Isolation:**
The analysis is wrapped in `try/except Exception`. If analysis fails or encounters an unhandled format, the upload completes with status **SUCCESS**, and a warning is logged without leaking credentials or interrupting storage.

---

## 11. Extension Points for Task 2

The `IntelligenceResult` schema is built specifically to power upcoming modules:
- **Task 2 (Smart Organizer):** Consume `result.file_type.family`, `result.domain_signals`, and `result.confidence` to suggest or apply folder destinations.
- **Task 3 (OCR & Content Extraction):** Populate document entities with full-text signals.
- **Task 4 (Search Index):** Ingest `result.tokens`, `result.entities.title`, and `result.domain_signals` into local search indexes.

---

## 12. Known Limitations

1. **Purely Filename & MIME Based in Task 1:** Does not read file payload content (PDF text, ID3 tags, or video container headers).
2. **Ambiguous Numeric Names:** A standalone numeric token like `1984` in `George.Orwell.1984.pdf` requires content inspection to distinguish publication year from title.
3. **No Automatic Organization in Task 1:** Files remain in their target upload folder without automated moving or renaming.
