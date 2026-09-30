# DARFIN Standalone Browser UX & Responsive Experience

## 1. Overview
DARFIN operates as a unified cloud file system supporting both:
- **Telegram Mini App (TMA)**: Direct access within Telegram client using Telegram WebApp initData HMAC authentication.
- **Standalone Web Browser**: Direct access via normal web browsers (`https://<DOMAIN>/`) powered by Telegram OpenID Connect (OIDC) PKCE authentication, secure HttpOnly cookie sessions, and responsive UI architecture.

The existing DARFIN Drive WebApp (`templates/webapp.html`) is reused completely. No duplicate browser dashboard was created.

---

## 2. Standalone Browser UX & Design Principles
- **Modern Cloud Storage Interface**: High-contrast, clean dark theme (`--bg-primary: #0a0e17`, `--accent: #38ef7d`) matching professional cloud storage platforms.
- **Unified Surface**: Unauthenticated users see a minimal, focused landing card; authenticated users see their full Drive with folders, files, search, intelligence badges, and safe organizer suggestions.
- **No Clutter**: Stripped unnecessary marketing boilerplate, extraneous buttons, and fake status counters.

---

## 3. Responsive Breakpoints & Device Support
CSS media queries adapt the interface dynamically across 5 tiers:
1. **Compact Mobile (320px - 375px)**:
   - Header title, search bar, and user pill shrink padding gracefully without text truncation.
   - Action buttons wrap without horizontal overflow (`overflow-x: hidden`).
   - Touch targets maintain minimum 44px hit-box.
2. **Standard Mobile (376px - 640px)**:
   - Full-width container (`width: 100%`).
   - File actions and intelligence panels present as accessible bottom sheets.
   - 2-column folder grid, single-column file list.
3. **Tablet (641px - 1024px)**:
   - Max width expands to `860px`.
   - Modals transition from bottom sheets to centered floating dialogs (`border-radius: 20px`, backdrop blur).
   - 3-column folder grid.
4. **Desktop (1025px - 1439px)**:
   - Max width expands to `1200px`.
   - 4-column folder grid with roomy file rows.
   - Enhanced hover states and subtle elevations.
5. **Ultrawide Desktop (>= 1440px)**:
   - Max width scales to `1380px`.
   - High visual density with clean whitespace balance.

---

## 4. Standalone Login Flow
1. **Unauthenticated Request**: User accesses `https://<DOMAIN>/`.
2. **Landing State**: Server delivers `templates/webapp.html`. Frontend checks authentication:
   - Inside Telegram Mini App: Authenticates via `initData` with `/api/auth/session`.
   - Standalone Browser: Calls `/api/auth/me`. If unauthenticated (`authenticated: false`), hides Drive UI and displays `#standaloneLandingCard`:
     - DARFIN Cloud Logo
     - Title: "DARFIN Cloud Storage"
     - Subtitle: "Sistem penyimpanan awan pribadi berbasis Telegram"
     - Action Button: **"Masuk dengan Telegram"** linking directly to `/auth/telegram/start`.
3. **No Credential Fields**: No email, password, or third-party OAuth forms exist. All authentication routes through Telegram OIDC.
4. **Authorization**: Browser navigates to Telegram OIDC provider with PKCE code challenge and cryptographically signed state cookie.
5. **Callback & Bootstrap**: Telegram redirects to `/auth/telegram/callback`. On token verification, server sets HttpOnly `tma_session` and `tma_csrf` cookies and redirects back to `/`.
6. **Authenticated Drive Display**: `/api/auth/me` returns `authenticated: true` with user profile. `#standaloneLandingCard` is hidden and `#driveView` is rendered immediately.

---

## 5. Header & Profile Menu
- **User Pill (`#userPill`)**:
  - Displays user avatar initial/icon, user display name, and dropdown indicator chevron.
  - Fully accessible button (`role="button"`, `aria-haspopup="true"`, `aria-expanded="false"`, `tabindex="0"`).
- **Profile Dropdown (`#userProfileDropdown`)**:
  - Large avatar badge with user initial.
  - Full Name (`#userDropdownFullName`).
  - Username handle (`#userDropdownUsername`).
  - Verification badge: `Telegram Verified`.
  - Accessible Logout Button (`#logoutBtn`, `role="menuitem"`).
- **Interaction Polish**:
  - Toggle on click/keyboard Enter.
  - Dismiss automatically on click outside or when pressing `Escape`.

---

## 6. Logout UX & Session Termination
1. **Trigger**: User clicks "Keluar" in profile menu.
2. **Action**: Frontend submits `POST /auth/logout` with `tma_csrf` header.
3. **Backend Clears Session**: Server clears `tma_session` and `tma_csrf` cookies with expired headers.
4. **Immediate Client Cleanup**:
   - `currentUser = null`, `authToken = null`, `driveData = null`.
   - Active modals and dropdowns closed.
   - Memory caches wiped.
5. **Landing Screen with Notice**:
   - Browser redirects to `/?logged_out=1`.
   - Landing card renders `#browserNoticeCard`: "Anda telah berhasil keluar dari DARFIN."
6. **Back/Forward Cache Defense**:
   - `WebAppPageHandler` and `BaseApiHandler` enforce `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` and `Pragma: no-cache`.
   - Browser back button after logout will not render cached private Drive data.

---

## 7. Session Expiry UX
- **401 Unauthorized Interception**: Centralized `authFetch()` wrapper intercepts all HTTP 401 responses.
- **Graceful Termination**: Invokes `handleSessionExpired()`.
  - Clears in-memory user credentials and drive data.
  - Closes all active modals.
  - Renders warning banner in `#browserNoticeCard`:
    `⚠️ Sesi Anda telah berakhir. Silakan masuk kembali dengan Telegram.`
  - Prevents infinite retry loops or silent desynchronization.

---

## 8. Search Integration (Task 5 Preservation)
- **Backend-Authoritative**: Reuses `SearchService` via `/api/search`.
- **Search Debounce & Stale Protection**:
  - 300ms debounce prevents flooding backend on typing.
  - Incremental `searchRequestId` counter discards outdated responses if a newer request resolves earlier.
- **Filters & Sorting**:
  - Filter by file category (Document, Image, Audio, Video, Other).
  - Sort by relevance, newest, oldest, name, or size.
- **Rich Results**: Displays matched files, snippets, OCR matches, highlighted badges, and matched folder names.

---

## 9. Intelligence Presentation (Task 5 Preservation)
- **Badges**:
  - Domain / category badge (e.g., 🎓 Pendidikan, 🧾 Keuangan, 📄 Dokumen, 📸 Tangkapan Layar).
  - OCR indicator badge (e.g., 📝 Teks Terdeteksi).
  - Conditional rendering prevents empty badge wrapper tags.
- **Details Panel**:
  - Overview: File name, formatted size, folder path, upload date.
  - Intelligence Section: Classification status, confidence level ("Tinggi", "Sedang", "Perlu ditinjau"), explanation.
  - OCR Text Preview: Masked sensitive digits/identifiers with HTML escaping.
  - Screenshot & Receipt Metadata: Merchant name, date, total amount (if detected).
  - Action buttons: Unduh, Bagikan, Pindahkan, Bintang, Sampah.

---

## 10. Organizer & Feedback Integration
- **Safe Organizer (Task 2C)**:
  - "Saran Penataan" section displays AI/rule-suggested moves without automatic execution.
  - [ Tinjau ] opens target folder preview.
  - [ Pindahkan ] invokes `/api/organizer/execute` with server-side validation.
- **Feedback Loop (Task 2D)**:
  - [✓ Cocok] and [✕ Bukan] buttons trigger `/api/preferences/feedback` to train personal heuristics.

---

## 11. Security & Hard Boundaries
- **Strictly No Passwords / Email / External OAuth**: Only Telegram OIDC is supported for standalone browser authentication.
- **PKCE & State/Nonce Integrity**: Prevents authorization code interception and CSRF injection.
- **HttpOnly Cookies**: Session tokens cannot be accessed via JavaScript (`document.cookie`).
- **CSRF Token Validation**: State-changing POST endpoints require matching CSRF token headers.
- **HTML Sanitization**: All file names, folder names, OCR snippets, and user profile fields are strictly escaped with `escapeHtml()` before DOM insertion.
- **No LocalStorage Auth Storage**: Sensitive identity tokens are never stored in `localStorage`.

---

## 12. Verification & Testing
- **New Task 6B Test Suite (`test_browser_ux.py`)**: 45 tests covering:
  - Login UI (5 tests)
  - Responsive layout (5 tests)
  - Search UX & debounce (6 tests)
  - Intelligence presentation & masking (6 tests)
  - Security & XSS defenses (8 tests)
  - Session lifecycle & logout (5 tests)
  - Accessibility & keyboard navigation (10 tests)
- **Regression Suite**: 621 tests total across Tasks 1, 2A-D, 3A-C, 4, 5, 6A, 6B:
  - 620 Passed
  - 1 Skipped (Tesseract OCR native binary optional environment check)
  - 0 Failures

---

## 13. Browser Tooling & Testing Report
- **Category A (DOM / API / Unit Testing)**: Fully verified and passed (45/45 tests green).
- **Category B (Automated Headless Browser Automation)**:
  - Host environment check: Neither `google-chrome`, `chromium`, `chromium-browser`, `firefox`, nor `playwright` packages are installed in the Linux development environment.
  - Automated browser-level screenshot / WebP recordings could not run natively on host.
- **Category C (Live Production Login Verification)**:
  - Awaiting real Telegram OIDC application credentials configuration and live Render deployment by user.
