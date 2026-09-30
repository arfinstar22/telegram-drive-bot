# DARFIN Standalone Browser Authentication (Task 6A)

> "Telegram Mini App authentication and browser Telegram OIDC authentication are two entry paths to the same DARFIN account."

---

## 1. Overview & Architecture

DARFIN provides secure standalone browser access (`https://DARFIN_DOMAIN/`) allowing users to interact with their personal cloud storage without opening Telegram first.

Standalone browser authentication uses official **Telegram OpenID Connect (OIDC)** via Authorization Code + PKCE (S256).

### Unified Account Resolution
Both login vectors resolve to the identical Telegram numeric User ID and Supabase account:

```
Source A: Telegram Mini App
     ↓
telegram.WebApp.initData (HMAC-SHA256 signature verified against BOT_TOKEN)
     ↓
Telegram User ID (e.g. 123456789)
     ↓
DARFIN Canonical Principal

Source B: Standalone Web Browser
     ↓
Telegram OIDC Authorization Code + PKCE S256 + State/Nonce verification
     ↓
Signed ID Token (RS256 verified against https://oauth.telegram.org/.well-known/jwks.json)
     ↓
Telegram User ID (claims["sub"] / claims["id"], e.g. 123456789)
     ↓
DARFIN Canonical Principal
```

Both authentication channels yield identical ownership:
- Identical files and folders
- Identical stars and tags
- Identical dropzones and shares
- Identical preferences and search history

---

## 2. OIDC Authentication Flow

```
1. Browser (Unauthenticated)
   → GET /
   ← Renders login card with [ Continue with Telegram ]

2. User clicks [ Continue with Telegram ]
   → GET /auth/telegram/start?next=/drive
   * Generates cryptographically secure `state` (32 bytes urlsafe)
   * Generates PKCE `code_verifier` (64 bytes urlsafe)
   * Computes PKCE S256 `code_challenge` = base64url(SHA256(code_verifier))
   * Generates replay `nonce` (32 bytes urlsafe)
   * Sets signed HttpOnly cookie: `tg_oidc_state` (HMAC-SHA256 with max_age=300s)
   ← HTTP 302 Redirect to https://oauth.telegram.org/auth

3. Telegram Authorization
   * User logs in / approves in Telegram Web
   ← HTTP 302 Redirect to https://DARFIN_DOMAIN/auth/telegram/callback?code=...&state=...

4. Callback Processing
   → GET /auth/telegram/callback?code=...&state=...
   * Verifies `state` matches cryptographically signed `tg_oidc_state` cookie
   * Extracts `code_verifier` and expected `nonce` from cookie
   * Clears `tg_oidc_state` cookie
   * Exchanges code server-side: POST https://oauth.telegram.org/token
     (code, client_id, client_secret, code_verifier, redirect_uri)
   * Retrieves & caches Telegram JWKS from https://oauth.telegram.org/.well-known/jwks.json
   * Validates ID token (RS256 signature, issuer, audience, expiration, nonce, sub)
   * Resolves numeric Telegram User ID from verified `sub` claim
   * Safely registers/upserts user in database (`db.upsert_user`)
   * Issues DARFIN session token in HttpOnly `tma_session` cookie
   * Issues random CSRF token in `tma_csrf` cookie
   ← HTTP 302 Redirect to safe sanitized destination (default: `/`)

5. Authenticated Browser Experience
   * Browser fetches `/api/auth/me` and `/api/drive` with `tma_session` cookie
   * WebApp renders full cloud drive interface
```

---

## 3. Cryptographic Guardrails

### 3.1 PKCE (RFC 7636)
- **Verifier:** 64-byte high-entropy URL-safe random string (`secrets.token_urlsafe(64)`).
- **Challenge:** S256 method: `base64url(SHA256(code_verifier)).rstrip("=")`.
- **Protection:** `code_verifier` exists exclusively in the server-side HMAC-signed state cookie and is sent only in the backchannel POST to Telegram's token endpoint. Never exposed to browser JavaScript.

### 3.2 State & Nonce Protection
- **State Cookie:** `state:nonce:verifier:next_path:exp_str:signature`.
- **HMAC Signature:** Calculated with SHA256 using server session secret.
- **Expiry:** Strict 5-minute lifespan (`max_age=300`).
- **Single-Use:** Cookie cleared immediately upon processing callback.

### 3.3 ID Token Verification
- Signature verified using PyJWT against official Telegram JWKS keys (`RS256`).
- Issuer verified: `https://oauth.telegram.org`.
- Audience verified: configured `TELEGRAM_OIDC_CLIENT_ID`.
- Expiry (`exp`) strictly enforced with PyJWT leeway=0.
- Nonce verified: must exactly match the nonce generated in `/auth/telegram/start`.
- Identity claim: `sub` must be a positive integer. Usernames and display names are never trusted for identity.

### 3.4 JWKS Key Management
- Cached in-memory with a 1-hour TTL (`_JWKS_CACHE_TTL_SECONDS = 3600`).
- Unknown Key ID (`kid`) triggers an immediate cache refresh.
- GZIP decompression handled transparently for Telegram's endpoints.
- Outbound requests enforce a 10.0s network timeout.

---

## 4. Session & Cookie Security

| Cookie Name | Purpose | HttpOnly | Secure | SameSite | Path | Lifespan |
|---|---|---|---|---|---|---|
| `tma_session` | DARFIN Session Token | **Yes** | **Yes** (prod) | **Lax** | `/` | 24 Hours |
| `tma_csrf` | CSRF Token | No (Readable by JS) | **Yes** (prod) | **Lax** | `/` | 24 Hours |
| `tg_oidc_state` | OIDC Transaction State | **Yes** | **Yes** (prod) | **Lax** | `/auth/telegram` | 5 Minutes |

---

## 5. CSRF Defense Strategy

DARFIN supports two distinct authentication contexts with tailored CSRF models:

1. **Telegram Mini App Context:**
   - Authenticated via `Authorization: Bearer <session_token>` or `X-Telegram-Init-Data: <init_data>`.
   - Custom HTTP headers cannot be attached in standard cross-site HTML form submissions or unauthorized browser navigations. Exempt from CSRF token requirements.

2. **Standalone Browser Context:**
   - Authenticated via HttpOnly `tma_session` cookie.
   - For state-changing operations (`POST`, `PUT`, `DELETE`, `PATCH`), the client JavaScript reads `tma_csrf` cookie and sends it in the `X-CSRF-Token` header.
   - Server validates `hmac.compare_digest(header_csrf, cookie_csrf)`. If missing or mismatched, returns `HTTP 403 Forbidden` (`CSRF_ERROR`).

---

## 6. Open Redirect Protection

Parameter `?next=` is sanitized by `oidc.sanitize_redirect_path`:
- Absolute URLs (`https://evil.com`), protocol-relative URLs (`//evil.com`), backslashes (`/\evil.com`), and javascript schemes (`javascript:...`) are rejected.
- Any invalid or external path falls back to `/`.

---

## 7. BotFather Configuration Guide

To enable Telegram OpenID Connect for your DARFIN instance:

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send command: `/mybots` and choose your DARFIN bot.
3. Select **Bot Settings** → **Domain** (or **Transfer/OIDC Configuration** depending on Telegram client version).
4. Set the authorized web domain:
   ```
   your-darfin-domain.onrender.com
   ```
5. Obtain the **OIDC Client ID** and **OIDC Client Secret** generated by BotFather.
6. Set the redirect URI in BotFather to:
   ```
   https://your-darfin-domain.onrender.com/auth/telegram/callback
   ```

---

## 8. Environment Variables

Add the following to your server configuration / `.env`:

```bash
# Telegram OpenID Connect (OIDC) - Standalone Browser Login
TELEGRAM_OIDC_CLIENT_ID=your_telegram_oidc_client_id_here
TELEGRAM_OIDC_CLIENT_SECRET=your_telegram_oidc_client_secret_here
TELEGRAM_OIDC_REDIRECT_URI=https://your-darfin-domain.onrender.com/auth/telegram/callback

# Optional overrides (defaults to official Telegram endpoints)
TELEGRAM_OIDC_ISSUER=https://oauth.telegram.org
TELEGRAM_OIDC_SCOPES=openid profile
```

---

## 9. Manual Production Verification Checklist

1. **Direct Browser Visit:**
   - Open Chrome / Firefox / Safari in Incognito mode to `https://DARFIN_DOMAIN/`.
   - Verify unauthenticated notice card appears: "DARFIN Cloud Storage" with button `[ Continue with Telegram ]`.
2. **OIDC Initiation:**
   - Click `[ Continue with Telegram ]`.
   - Verify browser redirects to `https://oauth.telegram.org/auth?...`.
   - Inspect network headers: verify `tg_oidc_state` cookie set with `HttpOnly` and `SameSite=Lax`.
3. **Telegram Approval:**
   - Log in and confirm authorization on Telegram OAuth screen.
4. **Callback & Session Establishment:**
   - Telegram redirects to `/auth/telegram/callback?code=...&state=...`.
   - Server exchanges code and validates ID token.
   - Browser is redirected to `/` with `tma_session` and `tma_csrf` cookies set.
   - WebApp dashboard loads automatically.
5. **Account Integrity:**
   - Verify file list matches files uploaded via Telegram Mini App.
   - Verify file search, download, rename, and star function normally.
6. **Logout:**
   - Click the user header badge and choose **Logout**.
   - Verify `tma_session` and `tma_csrf` cookies are cleared.
   - Verify browser is returned to unauthenticated login card.
7. **Mini App Regression:**
   - Open DARFIN inside Telegram Mini App.
   - Verify Mini App still authenticates automatically via `initData` without prompt.

---

## 10. Limitations & Boundaries

- Task 6A implements browser authentication core only.
- Full UI visual redesign deferred to subsequent phases.
- PWA service workers and mobile app packaging are not part of Task 6A.
- User accounts are exclusively anchored to Telegram numeric identities. No email, password, or third-party OAuth providers are enabled.
