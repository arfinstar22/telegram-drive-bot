# DARFIN WebApp Intelligence Integration

Documentation for Task 5: WebApp Presentation and Interaction layer for Darfin Storage Intelligence.

---

## 1. WebApp Architecture Overview

The DARFIN WebApp operates strictly as a Presentation and Interaction layer:

```
Telegram WebApp Client (HTML5 / Vanilla JS / CSS)
       │
       ▼ (authFetch: HMAC-SHA256 initData or Bearer token)
Tornado API Layer (webapp.py)
       │
       ├─► /api/search           ──► darfin_intelligence.search (Task 4)
       ├─► /api/file_intelligence ──► darfin_intelligence (Tasks 1, 2A, 2B, 3A, 3B, 3C)
       ├─► /api/organizer/preview ──► SafeOrganizer.preview (Task 2C)
       ├─► /api/organizer/execute ──► SafeOrganizer.execute_batch (Task 2C)
       └─► /api/preferences/feedback ──► PreferenceEngine (Task 2D)
```

### Architectural Principles:
1. **Zero Duplicate Logic**: All intelligence decisions (classification, folder mapping, OCR parsing, screenshot entity recognition, search scoring) run exclusively in Python backend modules. JavaScript performs zero parsing or heuristic guessing.
2. **Deterministic Processing**: 100% local rule-based inference. Zero external AI APIs, zero LLM calls, zero vector databases, zero Elasticsearch/Meilisearch.
3. **Stateless Frontend**: The client maintains UI state (current query, active filters, selected items, pagination cursor) while the backend remains authoritative.

---

## 2. Authentication & Authorization Flow

- **Path**: Telegram Mini App remains the current authoritative authentication channel.
- **Header**: Requests transmit Telegram WebApp initialization data via `X-Telegram-Init-Data` header or Bearer session token.
- **Security Invariants**:
  - `user_id` is never accepted from query strings, URL parameters, body payloads, or localStorage.
  - Client attempts to forge `user_id` are strictly ignored; identity is resolved solely from cryptographically verified HMAC-SHA256 signature against `BOT_TOKEN`.
  - All file and folder endpoints enforce strict user ownership checks (`user_id = eq.<authenticated_user>`). Cross-user access returns 404 or 403.
  - Browser standalone authentication (Telegram Login widget, OIDC) is deferred to future phases and not started here.

---

## 3. SearchService Integration

### Endpoints
- `GET /api/search?q=<query>&limit=25&offset=0&sort_by=relevance`
- `POST /api/search` (supports JSON body for structured filter payloads)

### Capabilities
- **Debounced Input**: Client enforces 300ms debounce before executing queries, preventing keystroke spam.
- **Lexical and Token Search**: Multi-token keywords, quoted exact phrases (`"tugas semester 5"`), and field prefixes.
- **Search Operators**:
  - `ext:<extension>` (e.g. `ext:pdf`, `ext:jpg`)
  - `type:<family>` (e.g. `type:video`, `type:document`)
  - `folder:<name>` or scoped `folder_id`
  - `domain:<domain>` (e.g. `domain:education`, `domain:finance`)
  - `document:<type>` (e.g. `document:receipt`, `document:invoice`)
  - `merchant:<name>` (e.g. `merchant:indomaret`)
  - `ocr:true` / `has_ocr=true`
- **Relevance and Reasons**:
  - Backend returns match reasons and highlights.
  - Client displays compact explanations (`Cocok: filename token: indomaret • ocr text: indomaret`).
  - Search score formulas remain private on server.

---

## 4. File Intelligence Detail Modal

Opening any file card fetches `/api/file_intelligence?file_id=<id>`:

1. **Classification Card**:
   - Family (document, image, video, audio)
   - Domain (finance, education, office, media, system)
   - Human-readable confidence label:
     - `>= 0.75`: `Tinggi` (High)
     - `>= 0.50`: `Sedang` (Medium)
     - Ambiguous status: `Perlu ditinjau` (Needs Review)
     - `< 0.50`: `Rendah` (Low)
   - Explain text from Task 2A classifier.
2. **Smart Organizer Suggestion Card**:
   - Suggests target folder with human-readable confidence label.
   - Provides instant feedback buttons: `✓ Cocok` (accept) and `✕ Bukan` (reject).
   - Allows direct move execution through authenticated backend API.
3. **Local OCR Card**:
   - Displays extracted text preview when OCR is available.
   - Truncated safely with ellipsis at 300 characters.
4. **Screenshot Intelligence Card**:
   - Displays screenshot category (e.g. `receipt_candidate`, `transfer_candidate`, `chat`).
   - Surfaces extracted entities: dates, prices, merchant names, URLs.
5. **Receipt & Document Details Card**:
   - Receipts: merchant name, transaction date, formatted total (IDR), payment method.
   - Formal documents: document type, document number, subject, sender, recipient.

---

## 5. Privacy & Sensitive Data Masking

- **Credit Card Numbers**: 16-digit card numbers in OCR text and search highlights are masked (e.g. `**** **** **** 4444`).
- **OTP Codes**: 4 to 8 digit verification codes are masked (e.g. `***219`).
- **Backend Masking**: Enforcement happens at backend serialization in `webapp.py` and `darfin_intelligence.search.service._mask_sensitive_text`. Frontend never receives raw credentials.

---

## 6. XSS Prevention & Escaping

- All untrusted backend data (file names, folder names, notes, OCR snippets, merchant names, search reasons, search highlights) are passed through `escapeHtml()` before insertion into DOM.
- `escapeHtml()` sanitizes `&`, `<`, `>`, `"`, and `'`.
- Safe DOM methods (`innerText`, `textContent`, template strings with `escapeHtml`) prevent script injection vulnerabilities.

---

## 7. Pagination & Performance

- **Pagination**: Default 25 items, max 100 items per request.
- **Load More**: Bottom pagination button dynamically appends items without clearing existing list.
- **Stale Request Dropping**: Sequential request counter (`searchState.requestId`) ignores slow responses from cancelled earlier queries.
- **Render Free Resource Limits**:
  - Memory: lightweight static assets, zero server-side image processing.
  - Search Latency: median backend search execution < 10ms for 100 files.
  - Zero heavy frontend dependencies: vanilla JavaScript only.

---

## 8. Mobile & Desktop Responsive Design

- **Mobile Viewport (<= 640px)**:
  - Sticky search toolbar.
  - Touch-friendly quick filter pills with smooth horizontal scrolling.
  - Filter modal renders as bottom drawer with backdrop blur.
  - File cards compact grid/list layout with minimum 44px touch targets.
- **Desktop Viewport**:
  - Full-width search bar with prominent action controls.
  - Modal centered overlay with scrollable content body.
  - Keyboard accessible (Escape closes modals/drawers).

---

## 9. Current Limitations & Future Roadmap

- **No Browser Standalone Authentication**: Access requires Telegram WebApp session context. Telegram Login / OIDC browser access is reserved for a future task.
- **No Vector Search**: All searches rely on deterministic lexical, token, and metadata scoring.
- **Local OCR Engine**: Relies on Tesseract OCR binary installed on server; files without OCR text display standard metadata only.
