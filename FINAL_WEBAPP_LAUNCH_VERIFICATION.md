# Final WebApp Launch Architecture Verification Report
## Darfin Storage — Secure WebApp Launch Architecture

### Executive Summary
This document records the architectural fix resolving Telegram WebApp authentication failures without removing the permanent bottom Reply Keyboard, without loosening server security, without trusting client-supplied `user_id`, and without hardcoded fallbacks.

---

### Architectural Diagram

```
Reply Keyboard (Persistent at Bottom)
    ↓ (User taps "📱 Buka WebApp Drive")
Text Message sent to Bot
    ↓
Bot catches text message via MessageHandler
    ↓
Bot replies with Inline WebApp button [ 🚀 Buka Drive ]
    ↓ (User taps "🚀 Buka Drive")
Telegram Inline Mini App opens (keyboardButtonWebView)
    ↓
Telegram client generates cryptographic initData (HMAC-SHA256 signed with Bot Token)
    ↓
WebApp sends raw initData to POST /api/auth/session
    ↓
Server strictly validates HMAC-SHA256 signature, auth_date staleness & integrity
    ↓
Server extracts authenticated user_id from verified Telegram payload
    ↓
Server generates cryptographic signed session token & issues HTTP-only cookie
    ↓
Frontend calls /api/drive with authenticated session
    ↓
Ownership-Scoped Private Drive displayed smoothly (Zero false lockouts)
```

---

### 1. Old Flow
1. User opened Telegram bot.
2. Bottom Reply Keyboard contained `KeyboardButton("📱 Buka WebApp Drive", web_app=WebAppInfo(url=WEBAPP_URL))`.
3. User pressed the Reply Keyboard button.
4. Telegram opened a Simple WebView (`keyboardButtonSimpleWebView`).
5. WebApp tried to read `window.Telegram.WebApp.initData`.

---

### 2. Why Old Flow Was Incompatible with Authenticated Mini App
- Under the official Telegram Bot API specification, a `KeyboardButton` with `web_app` in a `ReplyKeyboardMarkup` uses `keyboardButtonSimpleWebView`.
- In Simple WebView mode, the Telegram client **does not transmit cryptographic `initData`** (it is empty `""`).
- Because cryptographic `initData` was empty, the hardened backend correctly rejected unverified requests.
- Attempting client-side fallbacks (e.g., passing unverified `user_id`, `initDataUnsafe`, query parameters, or default IDs) violated application security principles and left the system vulnerable to impersonation and IDOR.
- In contrast, an `InlineKeyboardButton` with `web_app` triggers `keyboardButtonWebView`, which **always** provides authenticated Telegram user context and cryptographic HMAC-SHA256 signature in `initData`.

---

### 3. New Flow
1. **Permanent Reply Keyboard Retained:**
   Bottom Reply Keyboard remains permanently visible with `resize_keyboard=True`:
   ```
   ┌────────────────────────────────────┐
   │      📱 Buka WebApp Drive          │
   ├───────────────────┬────────────────┤
   │ 📁 File Saya      │ 📤 Upload      │
   ├───────────────────┼────────────────┤
   │ ⭐ Favorit        │ 🕐 Terbaru      │
   ├───────────────────┼────────────────┤
   │ 🔍 Cari           │ ⚙️ Pengaturan  │
   └───────────────────┴────────────────┘
   ```
2. **Plain Text Reply Button:**
   The button `"📱 Buka WebApp Drive"` is now a standard text `KeyboardButton` without `web_app` and without URL parameters.
3. **Bot Bridge Response:**
   When pressed, Telegram sends the message `"📱 Buka WebApp Drive"` to the bot.
   The bot matches the message and responds with:
   ```
   📂 Darfin Storage

   Klik tombol di bawah untuk membuka Drive Anda.
   [ 🚀 Buka Drive ]
   ```
4. **Inline Mini App Launch:**
   The `[ 🚀 Buka Drive ]` button is an `InlineKeyboardButton(text="🚀 Buka Drive", web_app=WebAppInfo(url=WEBAPP_URL))`.
5. **Cryptographic Validation & Session:**
   Telegram opens the Inline Mini App with valid `initData`. The server verifies HMAC-SHA256 with `BOT_TOKEN`, issues a secure signed session cookie/token, and displays the authenticated Drive.

---

### 4. Files Changed

| File | Changes Made |
| :--- | :--- |
| `keyboards.py` | Converted `"📱 Buka WebApp Drive"` in `main_menu()` from WebApp button to plain text button. Added `inline_webapp_button()` helper returning InlineKeyboardMarkup with `web_app=WebAppInfo(url=WEBAPP_URL)`. |
| `handlers/menu.py` | Added `open_webapp_prompt()` handler that responds to `"📱 Buka WebApp Drive"` with the inline WebApp button. Cleaned `_send_welcome_screen()` to maintain persistent menu without `ReplyKeyboardRemove`. |
| `bot.py` | Registered MessageHandler for `^📱 (Buka WebApp Drive\|Open WebApp Drive)$` routed to `menu.open_webapp_prompt`. |
| `webapp.py` | Completely removed client-side fallback authentication in `ApiAuthSessionHandler.post()`. Strictly enforced 400 MISSING_DATA if `not init_data` and 401 INVALID_SIGNATURE if HMAC validation fails. |
| `templates/webapp.html` | Removed all `fallback_user`, `tgUser`, `fallbackUserId`, `1166479771`, and query parameter identity hacks from `initSession()`. Added `#browserNoticeCard` that shows an informational page when opened directly in a browser without Telegram context, without locking out or showing raw errors. |
| `test_adversarial.py` | Added comprehensive test cases verifying: (1) body `user_id` spoofing rejection, (2) `fallback_user` spoofing rejection, (3) direct browser 401 on private endpoints, (4) Reply Keyboard text-only button, (5) Inline Keyboard web_app configuration, and (6) `open_webapp_prompt` bridge execution. |

---

### 5. Authentication Flow
- **Client:** Reads `window.Telegram.WebApp.initData`.
- **Transport:** POST `/api/auth/session` with `{"init_data": initData}`.
- **Server:**
  1. Checks presence of `init_data` (HTTP 400 if missing).
  2. Parses query string format and separates `hash`.
  3. Reconstructs `data_check_string` sorted alphabetically.
  4. Computes `secret_key = HMAC_SHA256("WebAppData", bot_token)`.
  5. Computes `expected_hash = HMAC_SHA256(secret_key, data_check_string)`.
  6. Compares hashes with constant-time `hmac.compare_digest`.
  7. Validates `auth_date` against `INIT_DATA_MAX_AGE_SECONDS`.
  8. Deserializes `user` JSON and extracts verified `user_id`.
  9. Signs session token with `SECRET_KEY` and sets HTTP-only cookie `tma_session`.

---

### 6. Reply Keyboard Flow
- Bottom keyboard remains visible after every interaction.
- Clicking `"📱 Buka WebApp Drive"` sends a text message to the bot.
- No `ReplyKeyboardRemove` is used; bottom buttons remain accessible for 1-click access to File Saya, Upload, Favorit, Terbaru, Cari, and Pengaturan.

---

### 7. Inline WebApp Flow
- The bot sends an inline message containing `[ 🚀 Buka Drive ]`.
- User taps `[ 🚀 Buka Drive ]`.
- Telegram launches the Mini App inside Telegram with full user context and signed `initData`.
- No `user_id` or secret is appended to the URL.

---

### 8. Security Verification
- **No Client-Controlled Identity:** Server never inspects `user_id` in request body or query parameter for private operations.
- **Strict Ownership Scoping:** All private endpoints (`/api/drive`, `/api/download`, `/api/thumbnail`, `/api/rename`, `/api/star`, `/api/create_folder`, etc.) enforce ownership matching the session identity.
- **Direct Browser Protection:** Opening `/webapp` directly in a browser without Telegram context displays a clean informational card ("DARFIN STORAGE: Aplikasi ini harus dibuka melalui Telegram") and prevents loading any private user data.
- **No Hardcoded Accounts:** No fallback default users exist in code.

---

### 9. Test Results

#### Test Suite 1: `test_adversarial.py`
- Tests run: 29
- Passed: 29
- Failed: 0
- Skipped: 0
- Verified:
  - Valid Telegram `initData` authentication (200 OK)
  - Tampered hash rejection (401 Unauthorized)
  - Tampered user ID in `initData` rejection (401 Unauthorized)
  - Stale `auth_date` (>24h) rejection (401 Unauthorized)
  - Missing `init_data` rejection (400 Bad Request)
  - POST body `user_id` spoofing rejection (400 Bad Request)
  - POST body `fallback_user` spoofing rejection (400 Bad Request)
  - Direct unauthenticated browser access to `/api/drive`, `/api/download`, `/api/thumbnail` blocked (401 Unauthorized)
  - Reply Keyboard `main_menu()` contains text-only button without `web_app`
  - Inline Keyboard `inline_webapp_button()` contains `web_app` with `WEBAPP_URL`
  - `open_webapp_prompt` handler returns inline launcher without removing Reply Keyboard
  - IDOR cross-user protection on file rename, move, delete, star, batch operations
  - Circular folder hierarchy prevention
  - Rate limiting & security headers

#### Test Suite 2: `test_security.py`
- Tests run: 25
- Passed: 25
- Failed: 0
- Skipped: 0
- Verified:
  - Cryptographic validation of Telegram WebApp signatures
  - Dev auth security configuration
  - Folder & file ownership enforcement
  - Relational hierarchy integrity
  - Public share PIN hashing, rate limiting, burn-after-reading, download limit exhaustion
  - Filename XSS and path traversal sanitization

#### Summary
- **Total Tests:** 54
- **Passed:** 54
- **Failed:** 0
- **Skipped:** 0

---

### 10. Remaining Limitations & Operating Notes
- Users must click the inline button `[ 🚀 Buka Drive ]` sent by the bot to launch the WebApp with Telegram cryptographic context. This is by design according to the Telegram Bot API architecture (Simple WebView vs Mini App WebView).
- Direct browser visits to the WebApp URL outside of Telegram will not display any Drive data and will instruct the user to open the bot via Telegram.
