# SECURITY MODEL & ARCHITECTURE SPECIFICATION

## Darfin Storage — Telegram Cloud Storage & WebApp

This document details the security architecture, threat model, trust boundaries, and authorization controls implemented in Darfin Storage.

---

## 1. High-Level Architecture & Trust Boundaries

```
[ Telegram Client / WebApp ]
        │
        ▼ (HTTPS)
┌─────────────────────────────────────────────────────────────┐
│ Tornado Web Server & API Layer (Tornado 6.5)                │
│                                                             │
│   ├── auth.py (HMAC-SHA256 initData validation)             │
│   │   ├── Session Token Generator / Verifier                │
│   │   └── require_authenticated_user()                      │
│   │                                                         │
│   ├── Private API Handlers (/api/drive, /api/rename, etc.)  │
│   │   └── Zero trust of client user_id                      │
│   │                                                         │
│   ├── Public Access Handlers (/s/{token}, /dropzone/{token})│
│   │   └── Central validate_public_share() & Dropzone guard  │
│   │                                                         │
│   └── Input & Upload Sanitizer                              │
│       └── Size guards, batch limits, filename sanitization  │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
┌─────────────────────────┐   ┌───────────────────────────────┐
│ Supabase PostgreSQL DB  │   │ Telegram Bot API / Cloud CDN  │
│ - user_id scoped queries│   │ - Telegram Media Storage      │
│ - Exact-match shares    │   │ - Bot Notifications           │
│ - Non-destructive schema│   │ - File Streaming Proxy        │
└─────────────────────────┘   └───────────────────────────────┘
```

---

## 2. Core Security Principles

1. **Authentication ≠ Authorization:** Identifying a user does not grant them access to an object. Every resource query verifies object ownership.
2. **Never Trust Client Identity:** The server never accepts `user_id` from client request bodies, query strings, or `initDataUnsafe`. User identity is derived exclusively from validated cryptographic proofs.
3. **Fail-Closed by Default:** Requests lacking valid authentication fail immediately with HTTP 401. If opened in a regular desktop or mobile browser without Telegram Mini App context, the WebApp displays an unauthorized screen and halts.
4. **Defense in Depth on Media Streams:** Private files, thumbnails, and audio/video streams are served through authenticated streaming proxy handlers with signed session tokens (`&auth=<token>`).
5. **No Opaque Metadata in Public Credentials:** Public share tokens are exact-match identifiers. Security controls (expiry, PIN, download limits) are checked server-side.
6. **No Username-Based Identity Transfer:** Usernames can change or be recycled; account recovery requires authenticated owner generation of one-time cryptographic recovery codes (`DREC-xxxx-xxxx`).

---

## 3. Subsystem Security Specifications

### 3.1. Authentication Layer (`auth.py`)

- **Signature Algorithm:** Official Telegram WebApp validation using HMAC-SHA256.
  $$\text{secret\_key} = \text{HMAC-SHA256}(\text{"WebAppData"}, \text{BOT\_TOKEN})$$
  $$\text{hash} = \text{HMAC-SHA256}(\text{secret\_key}, \text{data\_check\_string})$$
- **Staleness / Replay Protection:** `auth_date` must not be in the future (> 60s skew) and must not be older than `INIT_DATA_MAX_AGE_SECONDS` (default: 86,400s / 24 hours).
- **Session Tokens:** For `<img>`, `<video>`, `<audio>` tags and download links that cannot send custom HTTP headers, a tamper-proof session token is generated:
  $$\text{payload} = \text{user\_id} : \text{expires\_at} : \text{nonce}$$
  $$\text{token} = \text{payload} : \text{HMAC-SHA256}(\text{SESSION\_SECRET}, \text{payload})$$
- **Development Mode Isolation:** Development authentication (`DEV_AUTH_ENABLED=true`) requires explicit environment variable setting and is strictly disabled in production.

### 3.2. Authorization & Data Isolation (`database.py`)

Every sensitive database query enforces `user_id` as an atomic query constraint:

| Action | Dangerous Pattern (Eliminated) | Secure Implemented Pattern |
|---|---|---|
| Fetch File | `WHERE id = :file_id` | `WHERE id = :file_id AND user_id = :auth_user_id` |
| Rename File | `UPDATE files WHERE id = :id` | `UPDATE files WHERE id = :id AND user_id = :auth_user_id` |
| Move File | `UPDATE files SET folder_id = :fid` | Verifies `target_folder.user_id == auth_user_id` then updates scoped to `user_id` |
| Folder Move | Arbitrary parent assignment | Verifies `parent.user_id == auth_user_id`, blocks self-parenting, and prevents circular hierarchy |
| Delete File | Direct delete by ID | Marks `is_trashed = true` scoped to `user_id = :auth_user_id` |
| Trash Restore | Restore by file ID | `UPDATE files SET is_trashed = false WHERE id = :id AND user_id = :auth_user_id` |

### 3.3. Public File Sharing (`/s/{token}`)

- **Exact-Match Tokens:** Share tokens are matched exactly without prefix wildcards.
- **Server-Side Expiry:** Expired links return `EXPIRED` status regardless of client time.
- **PIN Protection:** PINs are hashed using PBKDF2-HMAC-SHA256 with 100,000 iterations and per-PIN cryptographic salt (`pbkdf2_sha256$<salt>:<hex>`). Comparison uses `secrets.compare_digest`.
- **Download Limits & Burn-After-Reading:** Links with download limits atomically increment `share_download_count`. When limit is reached, access is rejected.
- **Unified Security Verification:** Direct downloads (`/s/{token}?download=1`), previews, and web share views all invoke `validate_public_share()`. No bypass of PIN or expiry is possible.

### 3.4. Public Dropzone (`/dropzone/{token}`)

- **Folder Scoping:** Dropzone links allow guest file uploads strictly into the folder designated by the owner.
- **Input Sanitization:** Uploaders' sender names and filenames are sanitized against HTML, path traversal, control characters, and length limits.
- **Upload Guards:**
  - Maximum single file size: `MAX_UPLOAD_FILE_SIZE_MB` (default 50 MB)
  - Maximum files per batch: `MAX_UPLOAD_BATCH_FILES` (default 20 files)
  - Maximum batch payload: `MAX_UPLOAD_BATCH_MB` (default 100 MB)
- **Rate Limiting:** Dropzone upload attempts are throttled by client IP (default: 30 requests per minute).

### 3.5. Account Recovery Redesign

- **Threat Eliminated:** Old username-matching auto-recovery allowed anyone claiming an abandoned or recycled Telegram username to hijack entire drives.
- **Secure Redesign:**
  1. Authenticated user generates a recovery code via `/settings` -> "Kunci Pemulihan".
  2. Server generates `DREC-xxxx-xxxx` (high-entropy cryptographic token, valid for 15 minutes).
  3. SHA-256 hash of the code is stored with expiration timestamp.
  4. From new Telegram account, user submits the code via bot prompt or `/recover DREC-...`.
  5. Code is verified, redeemed once, and invalidated immediately.
  6. All folders and files are transferred atomically to the new Telegram user ID.

---

## 4. Threat Matrix & Mitigations

| Threat | Impact | Mitigation Implemented |
|---|---|---|
| IDOR / Horizontal Privilege Escalation | Cross-user data theft or modification | Strict `user_id` validation in every endpoint and database query |
| Client-side identity forgery | Unauthorized drive access | Complete elimination of client `user_id`; Telegram HMAC validation |
| Public share PIN bypass | Unauthorized access to protected links | Centralized `validate_public_share()` on all web, download, and bot paths |
| PIN Brute Force | PIN enumeration | In-memory attempt tracking, delay lockouts, and generic error responses |
| Direct Download Policy Bypass | Downloading without PIN or after expiry | Download routes pass through `validate_public_share()` before file delivery |
| Upload Memory Exhaustion / DoS | Server crash / high resource bills | Multi-tier file size, file count, and batch byte limits |
| Stored XSS | Script injection via filenames, folders, notes | Comprehensive `escape_html()` in Python and `escapeHtml()` in frontend templates |
| Directory Traversal | File path exploitation | `sanitize_filename()` strips `..`, `/`, `\`, null bytes, and control characters |
| Secret Leakage | Credential theft | Secrets loaded from environment; zero secrets in logs, client code, or git |
