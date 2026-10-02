# Darfin Storage — Telegram Cloud Storage & WebApp

A production-grade, secure cloud storage platform built on **Python 3.12**, **python-telegram-bot 21.x**, **Tornado 6.5**, **Supabase (PostgreSQL)**, and **Telegram WebApp (Mini App)**, optimized for seamless deployment on Render.

---

## 🌟 Features

- **Telegram Media Storage:** Upload any document, photo, video, or audio file directly in chat or via WebApp.
- **Glassmorphic WebApp:** Modern, high-performance web drive interface designed for desktop and mobile Telegram.
- **File & Folder Management:** Create folders, nested subfolders, rename, move, and batch organize.
- **Batch Operations:** Select multiple items to batch-star, batch-move, batch-delete, or send to Telegram chat.
- **Trash & Recovery:** Soft-delete to trash with instant restore or permanent purge.
- **Smart Duplicate Cleaner:** Automatically scan and group duplicate files by unique file hash (`file_unique_id`).
- **Storage Statistics:** Visual category breakdowns and quota usage.
- **Public File Sharing:** Generate exact-match shareable links with server-side expiration, PBKDF2 PIN protection, and download limits (burn after reading).
- **Public Dropzone:** Generate guest upload links allowing external contributors to submit files directly into a specific folder.
- **Direct Streaming & Download:** Fast audio and video preview streaming through an authenticated streaming proxy.
- **Secure Account Recovery:** Cryptographically generated one-time expiring recovery codes (`DREC-xxxx-xxxx`) for safely migrating drives between Telegram accounts.

---

## 🔒 Security Architecture

For detailed security specifications, threat modeling, and access control flows, see [`SECURITY_MODEL.md`](file:///home/darfinstar/projectTelegram/SECURITY_MODEL.md).

- **Zero Trust Client Identity:** Client-provided `user_id` is completely ignored. User identity is cryptographically validated from Telegram `initData` HMAC-SHA256 signatures.
- **Object-Level Authorization (IDOR Immune):** Every database query and bot callback enforces `WHERE user_id = :authenticated_user_id`.
- **Server-Side Share Enforcement:** Public links are checked for expiration, PIN hash, and download count on the server.
- **DoS & Upload Protection:** Enforced per-file size limits, batch file counts, and batch payload thresholds.
- **XSS & Traversal Immunity:** Filename sanitization strips null bytes, path traversal sequences (`..`), and HTML characters.

---

## 🚀 Quick Setup & Installation

### 1. Prerequisites
- Python 3.12+
- A Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- A [Supabase](https://supabase.com) project

### 2. Clone and Setup Environment
```bash
git clone <repository_url>
cd projectTelegram

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Database Initialization
1. Open your Supabase Dashboard -> **SQL Editor**.
2. Run [`setup.sql`](file:///home/darfinstar/projectTelegram/setup.sql) to create base tables and indexes.
3. Run [`migrations/001_security_hardening.sql`](file:///home/darfinstar/projectTelegram/migrations/001_security_hardening.sql) to add recovery and security enhancements.

### 4. Configure Environment Variables
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

| Variable | Description | Default / Example |
|---|---|---|
| `BOT_TOKEN` | Telegram Bot Token from BotFather | `123456789:ABC...` |
| `SUPABASE_URL` | Supabase Project URL | `https://xxxx.supabase.co` |
| `SUPABASE_KEY` | Supabase API Key (service_role or anon) | `eyJh...` |
| `WEBHOOK_URL` | Full URL for Telegram Webhook | `https://your-domain.onrender.com` |
| `WEBAPP_URL` | Full URL to WebApp endpoint | `https://your-domain.onrender.com/webapp` |
| `PUBLIC_BASE_URL` | Public base URL for share/dropzone links | `https://your-domain.onrender.com` |
| `PORT` | Local or Render HTTP Port | `10000` |
| `MAX_UPLOAD_FILE_SIZE_MB` | Maximum single upload size | `50` |
| `MAX_UPLOAD_BATCH_FILES` | Maximum files per batch upload | `20` |
| `MAX_UPLOAD_BATCH_MB` | Maximum total batch payload | `100` |
| `DEV_AUTH_ENABLED` | Enable dev mock authentication | `false` |
| `DEV_USER_ID` | Telegram User ID for dev testing | `0` |

---

## 🧪 Running Automated Tests

Run the complete security and regression test suite:
```bash
.venv/bin/python test_security.py
```
See [`TEST_REPORT.md`](file:///home/darfinstar/projectTelegram/TEST_REPORT.md) for full test coverage and results.

---

## 📦 Deployment to Render

This project is pre-configured for Render via [`render.yaml`](file:///home/darfinstar/projectTelegram/render.yaml):

1. Link your repository to [Render](https://render.com).
2. Create a **Web Service** with:
   - **Environment:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
3. Configure environment variables in the Render Dashboard matching your `.env`.
4. Render will start the combined bot and Tornado web server on port `10000`.
