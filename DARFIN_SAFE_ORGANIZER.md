# Darfin Safe Smart Organizer (Task 2C)

> **Module:** `darfin_intelligence.organizer.safe_organizer`  
> **Status:** Completed & Verified  
> **Design Principle:** Zero-AI-API, Deterministic Heuristics, Safe Defaults (Suggest-Only), Recheck Verification

---

## 1. Overview & Objectives

The Safe Smart Organizer (`SafeOrganizer`) bridges intelligence and action:
```
File Metadata (DB)
       |
       v
Task 1: Universal File Analyzer
       |
       v
Task 2A: Smart Domain Classifier
       |
       v
Task 2B: Smart Folder Mapping
       |
       v
Task 2C: Safe Organization Plan (Dry Run)
       |
       v
User Review & Approval (WebApp UI)
       |
       v
Security Recheck (Ownership, Trash, Stale Plan, Destination)
       |
       v
Safe Database Move & Audit Trail
```

### Core Safety Rules:
1. **Safe Default (`SUGGEST_ONLY`):** `AUTO_ORGANIZE_ENABLED = False`. Without explicit user activation, files are never automatically moved.
2. **Sensitive Category Protection:** Sensitive domains (`identity`, `health`, `legal`, `finance`) NEVER auto-move, regardless of confidence score. Always marked for explicit user confirmation.
3. **Dry-Run by Default:** Plan generation (`create_plan`, `preview`) is a pure in-memory calculation that never mutates the database.
4. **Strict Security Recheck:** Approval requests are re-verified on the server against current database records (file ownership, existence, destination folder ownership, trash state, and stale plan detection).
5. **No Destructive Operations:** The organizer only updates `folder_id`. No auto-delete, no auto-trash, no auto-rename.

---

## 2. Organization Plan & Item Model

### `OrganizationItem`
Each planned reorganization candidate contains:
```json
{
  "file_id": 102,
  "filename": "Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4",
  "source_folder_id": 10,
  "source_path": "Inbox",
  "target_folder_id": 25,
  "target_folder_name": "Film",
  "target_path": "Film",
  "confidence": 0.98,
  "decision": "suggest",
  "status": "planned",
  "domain": "media",
  "category": "movie",
  "family": "video",
  "reasons": [
    "Folder 'Film' exact alias match for category 'movie' (+100)",
    "Folder 'Film' matches file family 'video' (+20)"
  ],
  "stale_fingerprint": {
    "file_id": 102,
    "source_folder_id": 10,
    "updated_at": "2026-09-30T10:00:00Z"
  }
}
```

### Status & Decision Matrix

| Status | Decision | Trigger Condition |
| :--- | :--- | :--- |
| `planned` | `auto` | `auto_organize_enabled=True`, `confidence >= 0.95`, non-sensitive domain |
| `planned` | `suggest` | `confidence >= 0.50` (or sensitive domain with valid target folder) |
| `already_in_target` | `skip` | File's current `folder_id` matches recommended `target_folder_id` |
| `in_trash` | `skip` | File has `is_trashed=True` |
| `no_match` | `skip` | No user folder matches category or domain (never auto-creates folders) |
| `ambiguous` | `review` | Multiple user folders tied in ranking (e.g. `Film` vs `Movies`) |
| `low_confidence` | `review` | Combined confidence is below `0.50` |
| `stale_plan` | `skip/fail` | File's `folder_id` changed after plan generation |
| `unauthorized` | `fail` | File or destination folder does not belong to authenticated user |

---

## 3. Server-Side Security Recheck

When a user clicks **"Pindahkan"** or submits an approved batch, the server executes `SafeOrganizer.execute_item()`:

1. **Session-Derived Identity:** `user_id` is extracted strictly from the authenticated session, never trusted from client request parameters.
2. **File Existence & Ownership:** Queries `db.get_file(file_id, user_id=user_id)`. Rejects foreign or missing files.
3. **Trash Protection:** Rechecks `file.is_trashed`. Rejects moves for files in trash.
4. **Destination Ownership:** Queries `db.get_folder(target_folder_id, user_id=user_id)`. Rejects foreign destination folders.
5. **Idempotency Check:** If `file.folder_id == target_folder_id`, returns success (`already_in_target`) without issuing a redundant DB write.
6. **Stale Plan Detection:** Compares `source_folder_id` with current `file.folder_id`. If the file was moved elsewhere in the interim, the move is rejected (`stale_plan`).
7. **Scoped Move:** Executes `db.move_file(file_id, target_folder_id, user_id=user_id)`.

---

## 4. Batch Operations & Partial Result Reporting

Batch requests (`/api/organizer/execute`) evaluate each item independently:
```json
{
  "ok": false,
  "success": [
    {"file_id": 101, "target_folder_id": 26, "status": "executed"}
  ],
  "failed": [],
  "skipped": [
    {"file_id": 104, "target_folder_id": 30, "status": "already_in_target"}
  ],
  "unauthorized": [
    {"file_id": 201, "target_folder_id": 26, "status": "unauthorized"}
  ],
  "summary": {
    "total": 3,
    "moved": 1,
    "skipped": 1,
    "unauthorized": 1,
    "failed": 0
  }
}
```
If any item in the batch is unauthorized or failed, `"ok"` is set to `False` to prevent deceptive batch success indications.

---

## 5. Audit Logging

Every successful move is logged with:
- `timestamp`: UTC ISO timestamp
- `user_id`: Authenticated user ID
- `file_id`: Moved file ID
- `filename`: Clean sanitized filename
- `source_folder_id`: Original folder ID
- `target_folder_id`: New folder ID
- `confidence`: Match confidence score
- `reasons`: Explanation bullet points

**Zero Secret Leakage:** Authentication session tokens, PIN hashes, passwords, and bot tokens are strictly excluded from audit logs.

---

## 6. WebApp UI Integration

Minimal, non-intrusive integration in the existing storage toolbar:
- Header button: `[ 🧠 Organize ]` beside `[ Duplikat ]`.
- Interactive bottom sheet modal: shows eligible suggestions with confidence percentage and target folder.
- Action buttons: single-item `[ Pindahkan ]` and batch `[ Pindahkan Semua ]`.
- Automatic refresh on execution completion.
