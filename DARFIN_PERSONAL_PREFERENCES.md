# Darfin Storage — Personal Preferences & User Feedback Engine (Task 2D)

## 1. Overview
The Personal Preferences & User Feedback Engine learns from explicit user decisions in the WebApp Drive interface to personalize future folder suggestions. The entire learning pipeline is **100% deterministic local Python logic** with **zero AI, zero LLM, and zero external services**.

```
System Suggestion
       │
User Review (WebApp)
  ├── [ Pindahkan ] (accepted)
  ├── [ ✕ ]         (rejected)
  └── [ Pilih Folder Lain ] (corrected)
       │
Record Feedback (user-scoped, HMAC authenticated)
       │
Extract Clean Reusable Semantic Pattern
       │
Compute Positive/Negative Consensus & Confidence
       │
Apply Personalized Boost to Future Suggestions
```

---

## 2. Feedback Actions
Users provide feedback via the WebApp organization cards or preview modals:
- `accepted`: User confirms the system suggestion. Target folder receives `+1` positive count.
- `rejected`: User dismisses the system suggestion. Target folder receives `+1` negative count.
- `corrected`: User manually selects a different destination folder. Correct folder receives `+1` positive count.

> **CRITICAL RULE (Section 11 & 30):** Recording feedback NEVER moves files. File moves strictly require user approval via the Task 2C secure execution flow (`POST /api/organizer/execute`).

---

## 3. Pattern Normalization
To ensure learned preferences generalize across varied filenames while rejecting noisy numbers or version tags, `extract_reusable_patterns(filename)` strips extensions, removes noise tokens (`final`, `revisi`, `draft`, `copy`, `v1`, `v2`, `pt`, `cv`), and produces clean keyword tokens:

| Raw Input Filename | Extracted Reusable Patterns |
| :--- | :--- |
| `Proposal_KKN_Desa_Waindawula_Final_Revisi_3.pdf` | `['proposal', 'kkn', 'proposal kkn']` |
| `Invoice_Perusahaan_PT_ABC_2026.pdf` | `['invoice', 'perusahaan', 'invoice perusahaan']` |
| `KRS_Semester_Ganjil_2025.pdf` | `['krs', 'semester', 'ganjil', 'krs semester', 'semester ganjil']` |

Entire filenames are **never** stored as raw patterns.

---

## 4. Personal Preference Data Model
User preferences are stored in the lightweight `user_classification_preferences` table, scoped strictly by `user_id`:

```python
@dataclass
class UserPreference:
    user_id: int
    pattern: str
    target_folder_id: int
    domain: str | None = None
    category: str | None = None
    positive_count: int = 1
    negative_count: int = 0
    confidence: float = 0.50
    is_stale: bool = False
    id: int | str | None = None
    created_at: str
    updated_at: str
```

### Deterministic Boost Scaling
Confidence and score boosts scale deterministically with consistent positive feedback:

| Repetitions | Ratio Requirement | Confidence | Preference Boost |
| :--- | :--- | :--- | :--- |
| **1 choice** | `pos >= 1` | `0.40 - 0.60` | **+10** |
| **3 choices** | `pos >= 3, ratio >= 0.75` | `0.75` | **+20** |
| **5+ choices** | `pos >= 5, ratio >= 0.85` | `0.90` | **+30** |
| **Rejections** | `pos <= neg` | `0.0` | **+0 (No Boost)** |

---

## 5. Conflict Resolution
When a user has conflicting past choices for the same pattern (e.g. `proposal -> Kuliah` vs `proposal -> Projects`):
1. **Equal / Balanced Choices (Section 29):**
   - Example: `proposal -> Kuliah = 5`, `proposal -> Projects = 5`
   - Consensus ratio: `5 / 10 = 0.50 <= 0.60`.
   - **Result:** Preference is flagged as weak/ambiguous. Boost is dampened to `+0`. The suggestion engine refuses to pick aggressively, preserving ambiguity.
2. **Dominant Choices (Section 10):**
   - Example: `proposal -> Kuliah = 10`, `proposal -> Projects = 1`
   - Consensus ratio for Kuliah: `10 / 11 = 0.909 >= 0.80`.
   - **Result:** Kuliah receives full `+30` boost; Projects receives `+0`.

---

## 6. Strict Safety & Technical Hierarchy
Personal preferences can guide and break ties among destination folders, but **CAN NEVER override technical evidence or file family invariants**:

```
ACTUAL FILE TYPE
      >
TECHNICAL EVIDENCE
      >
CLASSIFICATION
      >
FOLDER MATCH
      >
USER PREFERENCE
```

### Inviolable Safety Checks
- Video files (`mp4`, `mkv`, `avi`, `mov`) can **never** be routed into `Office`, `Kantor`, or `Dokumen Kantor` folders, even with a strong user preference on `"perusahaan"`.
- Photo files (`jpg`, `png`, `webp`) can **never** be routed into `Film` or `Movie` folders.
- Audio files (`mp3`, `flac`, `wav`) can **never** be routed into `Office` or `Cinema` folders.
- Document files (`pdf`, `docx`, `xlsx`) can **never** be routed into `Film` or `Bioskop` folders.

---

## 7. Stale Folder Handling (Section 13)
If a user deletes a folder that was previously stored as a preference target:
1. `apply_preferences()` cross-references `target_folder_id` against the user's active folder tree.
2. Missing folders are flagged with `pref.is_stale = True` and skipped without raising exceptions.
3. The suggestion engine gracefully falls back to the next best candidate or marks `no_match`.

---

## 8. User Isolation & Privacy (Section 1, 16 & 23)
- **User-Scoped:** Preferences for User A (`proposal -> Kuliah`) and User B (`proposal -> Projects`) exist in completely separate tenant partitions. Neither user's preferences leak or influence the other.
- **HMAC Authentication:** All preference feedback requires an authenticated session (`Authorization: Bearer <token>` or `tma_session` cookie).
- **IDOR Defense:** Submitting feedback requires verifying both **file ownership** (`db.get_file(file_id, user_id=user_id)`) and **destination folder ownership** (`db.get_folder(target_folder_id, user_id=user_id)`). Foreign file IDs or folder IDs return `403 Forbidden`.
- **Zero Public Exposure:** Preferences are never exposed via Dropzone tokens, public share links, or unauthenticated endpoints.

---

## 9. Non-Mutation & No Self-Modifying Code (Section 18 & 19)
- Global dictionaries (`TASK_1_CORE_DICTIONARY`, `dicts._DOCUMENT_EXTS`, etc.) are immutable at runtime.
- No dynamic Python code generation, `eval()`, or `exec()` is ever used. User preferences exist purely as structured data records.

---

## 10. Human-Facing Explanations (Section 22)
When user preferences influence a folder suggestion, the reason is presented using clear, friendly Indonesian phrasing without mentioning "AI" or "machine learning":
- `"Personal preference: Kebiasaan folder Anda memilih 'Kuliah' untuk pola 'proposal' (+30)"`
