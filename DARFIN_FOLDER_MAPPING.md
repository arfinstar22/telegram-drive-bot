# Darfin Smart Folder Mapping (Task 2B)

> **Module:** `darfin_intelligence.organizer`  
> **Status:** Completed & Verified  
> **Design Principle:** Zero-AI-API, Deterministic Heuristics, Read-Only, Pure Memory Calculation

---

## 1. Architecture

The Smart Folder Mapping engine (`darfin_intelligence.organizer`) maps a file's `ClassificationResult` (from Task 2A) against an authenticated user's existing folder hierarchy.

```
+-----------------------------------+
|      Task 2A Classification       |
| (domain, category, family, tokens)|
+-----------------+-----------------+
                  |
                  v
+-----------------+-----------------+       +--------------------------+
|          Folder Mapper            | <==== | User Existing Folders    |
|   (darfin_intelligence.organizer) |       | (list[dict] / hierarchy) |
+-----------------+-----------------+       +--------------------------+
                  |
                  v
+-----------------+-----------------+
|         FolderSuggestion          |
| status, target, candidates, why   |
+-----------------------------------+
```

### Core Architecture Rules:
- **Read-Only / Pure Memory:** No database calls inside mapper core (`map_folder`). No file moves, no renames, no auto folder creation.
- **Existing Folder Reuse:** Reuses user's actual folders instead of forcing hardcoded English defaults.
- **User Isolation:** Folder list passed in must belong strictly to authenticated user.
- **Zero AI API:** 100% deterministic local standard library logic.

---

## 2. Input Contract

The folder mapper takes:
1. `classification`: `ClassificationResult` (or dict) containing `domain`, `category`, `family`, `filename`, `confidence`.
2. `folders`: `list[dict]` of user folders, or a pre-indexed `dict` via `build_folder_index(folders)`.
3. `context_tokens`: Optional set or list of token strings from filename (auto-extracted if omitted).

Folder schema:
```json
[
  { "id": 1, "name": "Film", "parent_id": null },
  { "id": 2, "name": "Kuliah", "parent_id": null },
  { "id": 3, "name": "Pemrograman Web", "parent_id": 2 }
]
```

---

## 3. Output Contract (`FolderSuggestion`)

```json
{
  "status": "matched",
  "target_folder_id": 3,
  "target_folder_name": "Pemrograman Web",
  "display_path": "Kuliah / Pemrograman Web",
  "confidence": 0.96,
  "candidates": [
    {
      "folder_id": 3,
      "name": "Pemrograman Web",
      "display_path": "Kuliah / Pemrograman Web",
      "score": 195,
      "reasons": [
        "Inherited domain match from parent 'Kuliah' (education)",
        "Context token match: 'pemrograman', 'web' (+95)",
        "Semantic category match: course (+40)"
      ]
    },
    {
      "folder_id": 2,
      "name": "Kuliah",
      "display_path": "Kuliah",
      "score": 100,
      "reasons": [
        "Exact normalized match to canonical alias (+100)"
      ]
    }
  ],
  "reasons": [
    "Domain 'education' matches folder 'Kuliah'",
    "Context tokens matched nested folder 'Pemrograman Web'"
  ]
}
```

Status outcomes:
- `"matched"`: Clear highest-scoring candidate selected.
- `"ambiguous"`: Two or more top candidates have near-identical confidence/scores.
- `"no_match"`: No user folder qualifies above minimum relevance threshold (score < 20).

---

## 4. Folder Name Normalization

Before matching, folder names are normalized deterministically:
1. **Emoji & Symbol Stripping:** Removes emojis, folder icon decorations (e.g., `📁 Film` -> `Film`).
2. **Case Normalization:** Folders are lowercased and stripped of leading/trailing whitespace.
3. **Punctuation Clean-up:** Replaces dots, underscores, dashes with single spaces.
4. **Duplicate Deduplication:** Duplicate folders (`Film`, `film`, `FILM`) are collapsed to keep candidate lists clean and stable.

---

## 5. Alias Dictionary System

The matcher maps normalized folder names and tokens to semantic categories across languages (Indonesian & English):

- **MEDIA (Movie):** `film`, `movie`, `movies`, `film collection`, `kumpulan film`, `bioskop`, `cinema`
- **MEDIA (Series):** `series`, `tv series`, `serial`, `drama series`, `drakor`, `anime`
- **EDUCATION:** `kuliah`, `kampus`, `college`, `academic`, `pendidikan`, `skripsi`, `tugas`, `krs`, `kkn`
- **FINANCE:** `finance`, `keuangan`, `uang`, `financial`, `invoice`, `pajak`, `rekening`, `tagihan`
- **OFFICE:** `office`, `kantor`, `pekerjaan`, `work`, `laporan`, `kerjaan`, `dokumen kantor`
- **PROJECT:** `project`, `proyek`, `projects`, `tugas besar`, `source code`
- **PERSONAL / IDENTITY:** `personal`, `pribadi`, `identity`, `identitas`, `ktp`, `sim`, `paspor`
- **HEALTH:** `health`, `kesehatan`, `medical`, `medis`, `rekam medis`, `obat`
- **LEGAL:** `legal`, `hukum`, `dokumen hukum`, `kontrak`, `perjanjian`

---

## 6. Ranking & Scoring Weights

Each folder candidate is scored through layered semantic criteria:

| Match Layer | Points | Criteria |
| :--- | :--- | :--- |
| **Exact Normalized Match** | +100 | Clean folder name exactly equals category/alias term |
| **Canonical Alias Match** | +60 | Multi-word folder name matches canonical alias phrase |
| **Semantic Category Match**| +40 | Folder name matches category-specific alias |
| **Domain Match** | +25 | Folder name matches broader domain alias |
| **Family Compatibility** | +20 | File family (video, audio, document) aligns with folder purpose |
| **Token Partial Match** | +10 | Sub-token inside multi-word folder matches category tokens |
| **Nested Context Token** | +95 | Child folder matches specific filename tokens (e.g. course name) |
| **Parent Domain Alignment**| +30 | Child folder inherits parent's domain qualification |
| **Generic Substring Coincidence** | +2 | Low-value token match without semantic verification |

---

## 7. Confidence Calculation

Confidence score (0.00 to 1.00) is derived from:
1. Absolute candidate score normalized against a 120-point ceiling: `min(1.0, score / 120.0)`.
2. Input classification confidence multiplier: `final_confidence = round(folder_conf * classification_confidence, 2)`.

---

## 8. Ambiguity Resolution

If the user possesses multiple equally valid target folders (e.g., both `Film` and `Movies` for a movie video):
- If top candidate score difference <= 5 and score ratio < 1.15:
  - `status = "ambiguous"`
  - `target_folder_id = None`
  - All qualifying candidates returned in `candidates` sorted by deterministic criteria.
- Task 2C or WebApp UI will prompt the user to make the final selection.

---

## 9. Nested Folder Hierarchy

The engine parses the complete parent-child folder tree:
- **Display Path Generation:** Generates canonical display paths (e.g., `Kuliah / Pemrograman Web`).
- **Domain Context Inheritance:** Child folders inherit domain legitimacy from their parent.
- **Specific Child Priority:** A course subfolder (`Kuliah / Pemrograman Web`) scores higher than the generic root folder (`Kuliah`) when filename contains course tokens.
- **Root vs Child Disambiguation:** A child folder `Kuliah / Finance` will not blindly capture company invoices if the classification is corporate finance, recognizing parent context.

---

## 10. User-Specific Folder Reuse

The mapper strictly adheres to existing user folders:
- **User A** has `📁 Film`: media/movie maps to `Film`.
- **User B** has `📁 Movies`: media/movie maps to `Movies`.
- **Never Hardcode English Names:** The engine never forces "Movies" or "Finance" when Indonesian counterparts exist in user folders.
- **Never Auto-Create:** When no matching folder exists, engine outputs `no_match` and `target_folder_id = null`.

---

## 11. False-Positive Protection

Filename keyword spillover is prevented by strictly relying on Task 2A `ClassificationResult`:
- **Example File:** `Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4`
- Task 2A classifies as `media / movie` (video family).
- Available Folders: `Office`, `Film`.
- **Protection Rule:** Folder mapper strictly excludes `Office` because `video` family conflicts with document/office folders.
- **Result:** Correctly selects `Film`.

---

## 12. Complete Usage Examples

### Example A: Direct Exact Match
```python
from darfin_intelligence.organizer import map_folder
from darfin_intelligence.classifier.models import ClassificationResult

classification = ClassificationResult(
    domain="finance",
    category="invoice",
    confidence=0.90,
    file_family="document"
)

folders = [
    {"id": 1, "name": "Film", "parent_id": None},
    {"id": 2, "name": "Keuangan", "parent_id": None}
]

suggestion = map_folder(classification, folders)
# suggestion.status -> "matched"
# suggestion.target_folder_name -> "Keuangan"
```

### Example B: Nested Course Disambiguation
```python
classification = ClassificationResult(
    domain="education",
    category="course",
    confidence=0.95,
    filename="Materi_Pemrograman_Web_Pertemuan_1.pdf",
    file_family="document"
)

folders = [
    {"id": 10, "name": "Kuliah", "parent_id": None},
    {"id": 11, "name": "Pemrograman Web", "parent_id": 10},
    {"id": 12, "name": "Basis Data", "parent_id": 10}
]

suggestion = map_folder(classification, folders)
# suggestion.status -> "matched"
# suggestion.target_folder_id -> 11
# suggestion.display_path -> "Kuliah / Pemrograman Web"
```

### Example C: No Match Fallback
```python
classification = ClassificationResult(
    domain="health",
    category="medical_record",
    confidence=0.85,
    file_family="document"
)

folders = [
    {"id": 1, "name": "Film", "parent_id": None},
    {"id": 2, "name": "Kuliah", "parent_id": None}
]

suggestion = map_folder(classification, folders)
# suggestion.status -> "no_match"
# suggestion.target_folder_id -> None
```
