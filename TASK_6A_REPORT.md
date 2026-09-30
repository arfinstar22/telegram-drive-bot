# TASK 6A — DARFIN STANDALONE BROWSER AUTHENTICATION CORE REPORT

## 1. Status
**COMPLETE.**
Direct browser authentication via official Telegram OpenID Connect (OIDC) Authorization Code + PKCE (S256) is implemented, secured, integrated, and verified with 0 regressions. Telegram Mini App authentication remains 100% backward-compatible and functional.

---

## 2. Existing Authentication Audit
Prior to Task 6A, DARFIN supported two authentication methods:
- **Telegram Mini App `initData`:** Frontend passes `telegram.WebApp.initData` via `X-Telegram-Init-Data` header or JSON body to `POST /api/auth/session`. Server validates HMAC-SHA256 signature using `BOT_TOKEN` (`auth.validate_telegram_init_data`).
- **Session Tokens:** Server generates signed timestamped session token (`create_session_token`), cached or sent in `Authorization: Bearer <token>` or `tma_session` cookie.
- **Audited Paths:** Private handlers in `webapp.py` utilize `require_authenticated_user(self)` and `get_authenticated_user(self)` in `auth.py`.
- **Finding:** Mini App requests relied on explicit headers (`Authorization: Bearer` or `X-Telegram-Init-Data`), making them immune to classic CSRF. Adding standalone browser sessions via cookies required a defense-in-depth CSRF mechanism for state-changing endpoints without breaking Mini App clients.

---

## 3. OIDC Architecture
- **Provider:** Telegram OpenID Connect (`https://oauth.telegram.org`).
- **Flow:** Authorization Code + PKCE (RFC 7636) with `S256` code challenge.
- **Scopes:** `openid profile`. (Least privilege: no phone or bot access requested).
- **Core Axiom:**
  > "Telegram Mini App authentication and browser Telegram OIDC authentication are two entry paths to the same DARFIN account."
- Both vectors map to the identical canonical numeric Telegram User ID and Supabase account.

---

## 4. Files Created
1. `oidc.py`: Core OIDC helper module (PKCE generation, state/nonce HMAC cookie creation & validation, JWKS retrieval with gzip support, code exchange, ID token validation, Telegram identity resolution, redirect sanitization).
2. `test_browser_auth.py`: 66 unit, integration, security, and robustness tests.
3. `DARFIN_BROWSER_AUTHENTICATION.md`: Complete architectural documentation, security specification, and BotFather setup guide.
4. `TASK_6A_REPORT.md`: This comprehensive report.

---

## 5. Files Modified
1. `config.py`: Added Telegram OIDC configuration constants with fallback defaults.
2. `.env.example`: Added Telegram OIDC configuration section placeholders.
3. `auth.py`: Implemented CSRF validation (`validate_csrf_token`) checking `X-CSRF-Token` against `tma_csrf` cookie for cookie-based state-changing requests, preserving exemptions for Bearer/initData headers.
4. `webapp.py`: Added handlers (`OidcStartHandler`, `OidcCallbackHandler`, `OidcLogoutHandler`, `ApiAuthMeHandler`), updated `ApiAuthSessionHandler` to issue CSRF cookies, imported `auth` & `config`, and registered all new routes.
5. `templates/webapp.html`: Integrated standalone login landing card (`#browserNoticeCard`), `[ Continue with Telegram ]` link, error alert banner (`#authErrorAlert`), header logout button, `/api/auth/me` bootstrap, and automatic CSRF header attachment in `authFetch()`.

---

## 6. Routes Added
- `GET /auth/telegram/start`: Generates PKCE challenge, state, nonce, sets signed cookie, and redirects browser to Telegram OAuth.
- `GET /auth/telegram/callback`: Validates state, exchanges code for tokens, validates ID token signature/claims, provisions/upserts user, sets session and CSRF cookies, redirects to destination.
- `POST /auth/logout`: Clears session and CSRF cookies, redirects to `/?logged_out=1`.
- `GET /api/auth/me`: Safe endpoint returning authentication status and profile without exposing sensitive tokens.

---

## 7. Environment Variables
Added to `.env.example`:
```bash
# Telegram OpenID Connect (OIDC) - Standalone Browser Login
TELEGRAM_OIDC_CLIENT_ID=
TELEGRAM_OIDC_CLIENT_SECRET=
TELEGRAM_OIDC_REDIRECT_URI=https://YOUR_DARFIN_DOMAIN/auth/telegram/callback
TELEGRAM_OIDC_ISSUER=https://oauth.telegram.org
TELEGRAM_OIDC_SCOPES=openid profile
```

---

## 8. PKCE Implementation
- **Verifier:** 64-byte cryptographically secure random string (`secrets.token_urlsafe(64)`).
- **Challenge:** `base64url(SHA256(verifier)).rstrip("=")`.
- **Method:** `S256`.
- **Security:** Verifier is stored exclusively in the server-side HMAC-signed `tg_oidc_state` cookie and sent only in the backchannel POST to Telegram's token endpoint. Never exposed in HTML or client JS.

---

## 9. State Protection
- Cryptographically random state (`secrets.token_urlsafe(32)`).
- Stored inside HMAC-SHA256 signed `tg_oidc_state` cookie with 5-minute lifespan (`max_age=300`).
- Checked via constant-time string comparison (`hmac.compare_digest`).
- Single-use: cookie is immediately cleared upon callback consumption.

---

## 10. Nonce Protection
- Cryptographically random nonce (`secrets.token_urlsafe(32)`).
- Bound to the state transaction and validated against the `nonce` claim in the verified ID token.

---

## 11. ID Token Validation
- Decoded and validated via PyJWT against Telegram's public JWKS.
- **Signature Algorithm:** Verified against official Telegram RSA/EC keys.
- **Issuer:** Enforced `https://oauth.telegram.org`.
- **Audience:** Enforced configured `TELEGRAM_OIDC_CLIENT_ID`.
- **Expiration:** Enforced without leeway.
- **Subject:** `sub` must parse to a positive integer.

---

## 12. JWKS Caching
- Outbound fetch to `https://oauth.telegram.org/.well-known/jwks.json`.
- Automatic handling of `gzip` Content-Encoding.
- Cached in-memory with a 1-hour TTL (`_JWKS_CACHE_TTL_SECONDS = 3600`).
- Key refresh triggered dynamically if an unmapped `kid` is encountered.
- 10.0-second network timeout on outbound calls.

---

## 13. Telegram Identity Mapping
- Canonical user identity is derived strictly from verified numeric `sub` / `id` claim in the ID token.
- Usernames and display names are stored as untrusted profile metadata only and **never** used to resolve accounts or authorize access.

---

## 14. Session Architecture
- Reuses existing DARFIN signed session tokens (`auth.create_session_token(user_id)`).
- Session token is stored in an HttpOnly cookie (`tma_session`).
- Tokens rotated upon successful login to prevent session fixation.

---

## 15. Cookie Security
- `tma_session`: `HttpOnly`, `Path=/`, `SameSite=Lax`, `Secure` in production.
- `tma_csrf`: `Path=/`, `SameSite=Lax`, `Secure` in production, accessible to JS for CSRF header construction.
- `tg_oidc_state`: `HttpOnly`, `Path=/auth/telegram`, `SameSite=Lax`, `Secure` in production, 5-minute max-age.

---

## 16. CSRF Protection
- **Mini App:** Header-based auth (`Authorization: Bearer` / `X-Telegram-Init-Data`) is inherently CSRF-protected; exempt from CSRF token requirement.
- **Browser Cookies:** State-changing requests (`POST`, `PUT`, `DELETE`, `PATCH`) require `X-CSRF-Token` header matching the `tma_csrf` cookie value.
- GET/HEAD requests are exempt from CSRF validation.

---

## 17. Logout Behavior
- `POST /auth/logout` explicitly clears `tma_session` and `tma_csrf` cookies with expired cookies (`expires=Thu, 01 Jan 1970 GMT; Path=/`).
- Client UI clears non-sensitive local display cache and redirects to `/?logged_out=1`.

---

## 18. Mini App Compatibility
- Telegram Mini App continues using `window.Telegram.WebApp.initData` and `POST /api/auth/session`.
- Header `X-Telegram-Init-Data` and `Authorization: Bearer` continue to function without modification.
- Existing Mini App test suites remain 100% green.

---

## 19. Database Changes
- **Zero schema changes.**
- Existing `users` table is used directly via `database.upsert_user(user_id, username, full_name)` and `database.get_or_create_inbox_folder(user_id)`.
- No duplicate user tables or split account records created.

---

## 20. Dependencies Added
- **Zero new external packages installed.**
- Reused existing pre-installed packages: `PyJWT` (v2.15.0), `cryptography` (v50.0.1), and `httpx` (v0.28.1).

---

## 21. Security Test Count
- **66 new tests** in `test_browser_auth.py` covering:
  - Configuration: 5 tests
  - PKCE: 5 tests
  - State & Nonce: 8 tests
  - Open Redirect: 6 tests
  - ID Token Validation: 9 tests
  - Identity Resolution: 6 tests
  - OIDC Endpoints: 8 tests
  - CSRF Protection: 5 tests
  - Auth Me Endpoint: 3 tests
  - Account Consistency & Robustness: 11 tests

---

## 22. Full Regression Result
- **Ran 576 tests across entire test suite** (`test_*.py`):
  - Result: `Ran 576 tests in 6.004s - OK (skipped=1)`.
  - **Zero failures. Zero errors. Zero regressions.**

---

## 23. Browser Testing Result
- System environment audit checked for Chrome, Chromium, Firefox, and Playwright.
- Headless browser binaries are not installed in the Linux environment (`which google-chrome chromium firefox playwright` exited 1).
- Per Prompt Section 41: Reported explicitly. DOM structure and template rendering tests are validated in Python (`test_landing_page_renders_browser_login_button` and `test_landing_page_displays_auth_error_alert`).

---

## 24. Manual Production Test Status
- Production checklist prepared in `DARFIN_BROWSER_AUTHENTICATION.md` Section 9.
- Awaiting domain registration and real client ID/secret configuration via BotFather.

---

## 25. Performance Results
Measured local execution times:
- **PKCE + State Creation:** `0.007 ms`
- **State Cookie Verification:** `0.004 ms`
- **Session Token Creation:** `0.004 ms`
- **Session Token Verification:** `0.003 ms`
- **ID Token RS256 Verification:** `0.066 ms`
- **JWKS Cache Hit:** `0.0001 ms`
- **Login Page Render (`GET /`):** `2.85 ms`
- **Auth Start Route (`GET /auth/telegram/start`):** `0.79 ms`
- **Auth Me Route (`GET /api/auth/me`):** `0.67 ms`
*(Note: External OIDC network latency to Telegram is separate and depends on ISP/datacenter network round-trips).*

---

## 26. Known Limitations
- Task 6A encompasses browser authentication core only.
- Visual redesign of the full dashboard deferred to Task 6B.
- Accounts remain strictly anchored to Telegram numeric identities (no password or external OAuth).

---

## HARD STOP NOTICE
Task 6A is complete. Task 6B has **not** been started.
