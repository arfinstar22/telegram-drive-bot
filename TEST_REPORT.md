# AUTOMATED & MANUAL SECURITY TEST REPORT

## Darfin Storage — Telegram Cloud Storage & WebApp
**Date of Execution:** 2026-09-30  
**Status:** PASS (All 25 Automated Security Tests Passed)

---

## 1. Test Environment

| Component | Specification |
|---|---|
| Operating System | Linux (x86_64) |
| Python Runtime | Python 3.12.3 (CPython) |
| Web Framework | Tornado 6.5.10 |
| Telegram Bot Library | python-telegram-bot 21.11.1 |
| Database Client | supabase 2.31.0 / postgrest 2.31.0 |
| Test Framework | Python standard library `unittest` + `tornado.testing` |

---

## 2. Automated Security Test Results (`test_security.py`)

Execution command:
```bash
.venv/bin/python test_security.py
```

### Result Summary:
```text
Ran 25 tests in 1.648s
OK
```

### Detailed Test Matrix:

| Test Case Name | Category | Scenario / Vector | Result |
|---|---|---|:---:|
| `test_valid_init_data_passes` | Authentication | Valid Telegram `initData` with matching HMAC-SHA256 signature | **PASS** |
| `test_invalid_hash_rejected` | Authentication | Modified or forged `hash` parameter in `initData` | **PASS** |
| `test_tampered_user_id_rejected` | Authentication | Client tampering with `user` payload without valid secret key | **PASS** |
| `test_expired_init_data_rejected` | Authentication | Stale `auth_date` (> 24 hours old) | **PASS** |
| `test_missing_init_data_rejected` | Authentication | Null, empty, or whitespace `initData` string | **PASS** |
| `test_session_token_lifecycle` | Authentication | HMAC-signed session token creation, validation, and expiry | **PASS** |
| `test_dev_auth_only_when_explicitly_enabled` | Authentication | Dev auth mode rejection in prod; isolation when enabled | **PASS** |
| `test_filename_sanitization` | Input Security | Path traversal (`../../etc/passwd`), null bytes, HTML tags, control chars | **PASS** |
| `test_pin_hashing_and_verification` | Cryptography | PBKDF2-HMAC-SHA256 hashing, salting, and constant-time verify | **PASS** |
| `test_share_token_parsing_backward_compatibility` | Backward Compatibility | Parsing legacy metadata pipe tokens vs new clean tokens | **PASS** |
| `test_public_share_valid` | Public Share | Accessing active, unexpired public file with valid token | **PASS** |
| `test_public_share_trashed_file_denied` | Public Share | Attempting to access trashed file via public link (`NOT_FOUND`) | **PASS** |
| `test_public_share_expired_denied` | Public Share | Attempting to access file after expiration timestamp (`EXPIRED`) | **PASS** |
| `test_public_share_pin_protection` | Public Share | PIN challenge flow: missing PIN, wrong PIN, and correct PIN | **PASS** |
| `test_public_share_download_limit_exhausted` | Public Share | One-time / download limit link exhaustion (`LIMIT_EXHAUSTED`) | **PASS** |
| `test_get_file_for_user_prevents_idor` | Authorization | User A attempting to fetch User B's file ID (IDOR) | **PASS** |
| `test_get_folder_for_user_prevents_idor` | Authorization | User A attempting to inspect User B's folder ID (IDOR) | **PASS** |
| `test_circular_folder_prevention` | Relational Integrity | Moving folder into itself or into its own descendant | **PASS** |
| `test_recovery_code_generation_and_redemption` | Account Recovery | Generating `DREC-xxxx-xxxx`, redeeming, and blocking reuse | **PASS** |
| `test_unauthenticated_drive_rejected` | API Security | `GET /api/drive` without valid authentication header (401) | **PASS** |
| `test_client_supplied_user_id_ignored_and_rejected` | API Security | `GET /api/drive?user_id=victim` rejected (401, no spoofing) | **PASS** |
| `test_unauthenticated_post_endpoints_rejected` | API Security | POST to star, rename, folder, batch_delete, batch_move without auth (401) | **PASS** |
| `test_unauthenticated_media_rejected` | Media Security | Direct download and thumbnail proxy without auth token (401) | **PASS** |
| `test_health_and_ping_accessible` | Availability | `GET /api/ping` and `GET /health` responding 200 OK | **PASS** |
| `test_public_dropzone_info_invalid_token` | Dropzone | Querying non-existent dropzone token returns 404 | **PASS** |

---

## 3. WebApp & Bot Manual QA Checklist

| Component / Flow | Verified Items | Status |
|---|---|:---:|
| **WebApp Open (Telegram)** | Exchanges `initData` via `/api/auth/session`, obtains session token, populates drive | Verified |
| **WebApp Open (Raw Browser)** | Fails closed with glassmorphic `#unauthorizedOverlay`, blocks drive data load | Verified |
| **Folder Navigation** | Nested folder opening, breadcrumbs navigation, empty folder states | Verified |
| **Direct Web Upload** | Upload progress bar, Telegram cloud storage storage, quota & count validation | Verified |
| **File Operations** | Preview modal, audio streaming bar, rename, move, star, trash, permanent delete | Verified |
| **Batch Operations** | Selection mode, select all, batch star/unstar, batch move, batch delete | Verified |
| **Public Sharing** | Generate share link, copy URL, set PIN, set expiration, download limit, revoke | Verified |
| **Public Dropzone** | Guest upload to owner's folder, notification delivery, name sanitization | Verified |
| **Trash & Recovery** | View trashed items, restore file, empty trash permanently | Verified |
| **Duplicate Cleaner** | Scan duplicates by `file_unique_id`, clean duplicate copies to trash | Verified |
| **Telegram Bot Handlers** | All inline callbacks (`fi:`, `fdl:`, `fr:`, `fm:`, `fmt:`, `fx:`, `fxc:`, `fst:`) enforce ownership | Verified |
| **Account Recovery** | Owner generates `DREC-` code; new account redeems; username spoofing disabled | Verified |

---

## 4. Known Limitations & Operational Recommendations

1. **Per-Process In-Memory Rate Limiting:**
   - The rate limiter (`RateLimiter` in `webapp.py`) operates in-memory. For single-instance deployments (such as Render free/starter instances), this provides optimal low-latency protection without external dependencies. If scaling horizontally across multiple web nodes in the future, migrate to a Redis-backed rate limiter.
2. **Render Free Tier Spin-Down:**
   - Render free tier spins down after 15 minutes of inactivity. The background `keep_alive_worker()` sends periodic pings to `/api/ping` to prevent sleep during active hours. When restarting, Telegram Webhook tokens remain valid.
3. **Telegram 20MB Webhook Download Limit:**
   - Files uploaded directly via the Telegram Bot API over standard webhooks are subject to Telegram's 20MB file download limit for bots. Larger files (up to 50MB) are supported when running a local Telegram Bot API server.
