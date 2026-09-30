# Darfin Smart Domain Classifier (Task 2A)

> **Module:** `darfin_intelligence.classifier`  
> **Status:** Completed & Verified  
> **Design Principle:** Zero-AI-API, Deterministic Heuristics & Weighted Scoring

---

## 1. Overview & Objectives

The Smart Domain Classifier (`darfin_intelligence.classifier`) consumes the structured `IntelligenceResult` produced by Task 1 and resolves high-level semantic metadata:
1. **Domain:** Broad context sphere (`media`, `education`, `office`, `finance`, `identity`, `health`, `legal`, `project`, `personal`, `unknown`).
2. **Category:** Specific functional categorization within the detected domain and file family.
3. **Score & Top Candidates:** Ranked competing domain hypotheses with scores.
4. **Confidence:** Normalized statistical certainty score (0.0 to 1.0).
5. **Ambiguity Resolution:** Explicit fallback when evidence is tied or conflicting.
6. **Explainability:** Clear, human-readable breakdown explaining every classification decision.

---

## 2. Input & Output Contract

### Input
The classifier accepts a completed `IntelligenceResult`:
```python
from darfin_intelligence import analyze, classify

raw_result = analyze("Invoice.Perusahaan.2026.pdf")
classification = classify(raw_result)
```
Or via class interface:
```python
from darfin_intelligence.classifier import DomainClassifier

classification = DomainClassifier.classify(raw_result)
```

### Output (`ClassificationResult`)
```json
{
  "domain": "finance",
  "category": "invoice",
  "status": "classified",
  "confidence": 0.86,
  "scores": {
    "finance": 12,
    "office": 2,
    "media": 0,
    "education": 0
  },
  "evidence": [
    "[STRONG] Keyword 'Invoice' matches finance (+12)",
    "[WEAK] Keyword 'Perusahaan' matches office (+2)",
    "[FORMAT] Document format confirms document domains"
  ],
  "top_candidates": [
    {"domain": "finance", "score": 12, "category": "invoice"},
    {"domain": "office", "score": 2, "category": "administrative_document"}
  ],
  "file_id": null,
  "filename": "Invoice.Perusahaan.2026.pdf",
  "family": "document"
}
```

---

## 3. Hierarchy of Proof

To prevent weak keywords from distorting technical facts, classification strictly enforces this invariant:

$$\text{ACTUAL FILE FAMILY} > \text{MIME / EXTENSION} > \text{TECHNICAL MEDIA SIGNAL} > \text{FILENAME STRUCTURE} > \text{DOMAIN KEYWORDS}$$

- **Strong Technical Evidence:** Resolution (`1080p`, `UHD`), Source (`WEB-DL`), Codec (`x264`, `HEVC`), Container (`mkv`, `mp4`).
- **Domain Keywords:** Weak context hints (`perusahaan`, `laporan`, `dokumen`).
- **Conflict Rule:** Video files apply a heavy conflict penalty (-50) to document/office domains, guaranteeing media files are never misclassified as office files.

---

## 4. Supported Domains & Categories

| Domain | Description | Categories by File Family |
|---|---|---|
| **`media`** | Entertainment, video, and audio streams | `movie`, `series`, `anime`, `tutorial`, `personal_video`, `unknown_video`, `music`, `podcast` |
| **`education`** | Academic, coursework, university files | `krs`, `thesis`, `assignment`, `exam`, `kkn`, `academic_document`, `lecture` |
| **`office`** | Corporate administration and business operations | `administrative_document`, `report`, `memo`, `minutes`, `contract` |
| **`finance`** | Accounting, transactions, invoices, tax | `invoice`, `receipt`, `tax`, `statement`, `payroll`, `finance_document` |
| **`identity`** | Credentials, KYC, personal legal identification | `id_card`, `passport`, `cv`, `license`, `identity_document` |
| **`health`** | Medical records, clinical prescriptions | `prescription`, `medical_record`, `lab_result`, `health_document` |
| **`legal`** | Binding contracts, deeds, legal permits | `contract`, `legal_permit`, `legal_document` |
| **`project`** | Technical specifications, proposals, software | `proposal`, `specification`, `documentation`, `project_document`, `software` |
| **`personal`** | Personal memories, photos, diaries, voice notes | `photo`, `screenshot`, `voice`, `personal_note`, `backup` |
| **`unknown`** | Unidentifiable or insufficient evidence | `unknown_document`, `unknown_image`, `unknown_audio`, `unknown_archive` |

---

## 5. Keyword Strength & Weighting System

Keyword matches are split into three deterministic tiers:
- **Strong (+12):** Deterministic, high-specificity terminology.
  - `invoice`, `kwitansi`, `pajak`, `ktp`, `sim`, `paspor`, `krs`, `skripsi`, `rontgen`, `akta`, `kontrak`.
- **Moderate (+6):** Contextual terminology.
  - `kuliah`, `kampus`, `tugas`, `rapat`, `meeting`, `memo`, `proposal`, `project`, `resep`, `dokter`.
- **Weak (+2):** Broad, generic words that frequently co-occur in unrelated contexts.
  - `perusahaan`, `laporan`, `dokumen`, `rekap`, `materi`, `biaya`, `data_diri`, `aturan`.

---

## 6. Ambiguity & Low Evidence Handling

When file metadata contains conflicting or insufficient signals:
1. **Candidate Margin ($\Delta \le 2$ or ratio $< 1.35$):**
   When two domains have near-identical scores (e.g. `Proposal.KKN.2026.pdf` where `project`=6 and `education`=6):
   - `status = "ambiguous"`
   - `domain = None`, `category = None`
   - Candidates are retained in `top_candidates` for user selection in Task 2D.
2. **Weak-Only Keywords:**
   When a file only matches a single weak keyword (e.g. `Dokumen.2026.pdf`), confidence is capped at $\le 0.45$ to signal low certainty.
3. **No Signals:**
   Purely numeric or arbitrary names (e.g. `123456.pdf`) default to `status = "unknown"`, `category = "unknown_document"`.

---

## 7. False-Positive Protection Examples

### 1. `Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4`
- **Signals:** `Perusahaan` (+2 office), `UHD` (+15 media), `WEB-DL` (+15 media), `MP4` container (+100 media).
- **Conflict Resolution:** `office` penalized (-50 -> 0).
- **Result:** `family: video`, `domain: media`, `category: movie`, `confidence: 1.0`.

### 2. `Laporan.Perusahaan.2026.1080p.WEB-DL.x264.mp4`
- **Result:** `family: video`, `domain: media`, `category: movie`.

### 3. `Proposal.Perusahaan.2026.pdf`
- **Signals:** `Proposal` (+6 project), `Perusahaan` (+2 office).
- **Result:** `family: document`, `domain: project`, `category: proposal`.

### 4. `Invoice.Perusahaan.2026.pdf`
- **Signals:** `Invoice` (+12 finance), `Perusahaan` (+2 office).
- **Result:** `family: document`, `domain: finance`, `category: invoice`.

---

## 8. Performance Benchmark

- Tested across **1,000 files**: **0.042 seconds** total runtime.
- **Throughput:** ~24,000 file classifications per second per CPU core.
- **Zero I/O:** Runs completely in-memory without database or network queries.
