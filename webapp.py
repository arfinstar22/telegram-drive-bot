"""Telegram Mini App (TMA) Web Server & API for Darfin Storage.

Serves the visual cloud drive interface directly inside Telegram.
Enforces authentication, authorization, ownership verification,
upload limits, exact-match share token validation, and secure rate limiting.
"""

import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Optional

import tornado.web
import tornado.httputil
import tornado.httpclient
from telegram import Bot

import config
from config import (
    BOT_TOKEN,
    PORT,
    WEBHOOK_URL,
    PUBLIC_BASE_URL,
    ALLOWED_ORIGINS,
    MAX_UPLOAD_FILE_SIZE_MB,
    MAX_UPLOAD_BATCH_FILES,
    MAX_UPLOAD_BATCH_MB,
)
import database as db
import smart_organizer
from utils import (
    format_size,
    parse_file_metadata,
    parse_share_token,
    sanitize_filename,
    escape_html,
    verify_pin,
)
from auth import (
    require_authenticated_user,
    get_authenticated_user,
    validate_telegram_init_data,
    create_session_token,
)
import auth
from darfin_intelligence.search.service import _mask_sensitive_text
import oidc
import secrets

log = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "webapp.html"
DROPZONE_TEMPLATE_PATH = Path(__file__).parent / "templates" / "dropzone.html"
SHARE_FILE_TEMPLATE_PATH = Path(__file__).parent / "templates" / "share_file.html"
STATIC_DIR = Path(__file__).parent / "static"

# In-memory rate limiter
# Format: {key: [timestamps]}
_RATE_LIMITS: dict[str, list[float]] = {}


def check_rate_limit(key: str, max_requests: int = 10, window_seconds: int = 60) -> bool:
    """Simple, zero-dependency in-memory rate limiter for sensitive endpoints."""
    now = time.time()
    timestamps = _RATE_LIMITS.setdefault(key, [])
    _RATE_LIMITS[key] = [t for t in timestamps if now - t < window_seconds]
    if len(_RATE_LIMITS[key]) >= max_requests:
        return False
    _RATE_LIMITS[key].append(now)
    return True


class RateLimiter:
    """Zero-dependency token bucket / sliding window rate limiter."""
    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    def allow_request(self, key: str) -> bool:
        return check_rate_limit(key, self.max_requests, self.window_seconds)

    def is_allowed(self, key: str) -> bool:
        return self.allow_request(key)


class BaseApiHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        # Origin verification for CORS
        origin = self.request.headers.get("Origin")
        if origin:
            if not ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS:
                self.set_header("Access-Control-Allow-Origin", origin)
                self.set_header("Access-Control-Allow-Credentials", "true")
            else:
                log.debug("CORS origin not allowed: %s", origin)
        elif not ALLOWED_ORIGINS:
            self.set_header("Access-Control-Allow-Origin", "*")

        self.set_header(
            "Access-Control-Allow-Headers",
            "x-requested-with, content-type, authorization, x-telegram-init-data",
        )
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS, HEAD")
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "SAMEORIGIN")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.set_header("Pragma", "no-cache")

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code: int, **kwargs):
        """Sanitized error responses to prevent leaking internal traces or SQL."""
        self.set_header("Content-Type", "application/json; charset=utf-8")
        err_msg = "Terjadi kesalahan pada server."
        if status_code == 400:
            err_msg = "Permintaan tidak valid."
        elif status_code == 401:
            err_msg = "Autentikasi Telegram diperlukan."
        elif status_code == 403:
            err_msg = "Akses ditolak."
        elif status_code == 404:
            err_msg = "Objek tidak ditemukan."
        elif status_code == 429:
            err_msg = "Terlalu banyak permintaan. Silakan tunggu beberapa saat."

        self.finish(json.dumps({
            "ok": False,
            "error": {
                "code": f"HTTP_{status_code}",
                "message": err_msg,
            }
        }))


class ApiPingHandler(BaseApiHandler):
    """Health check / ping endpoint."""
    def get(self):
        self.write({"ok": True, "status": "awake", "service": "telegram-drive-bot"})

    def head(self):
        self.set_status(200)


class WebAppPageHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.set_header("Pragma", "no-cache")
        self.set_header("Expires", "0")
        # Allow embedding in Telegram WebApp
        self.set_header(
            "Content-Security-Policy",
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org telegram:;",
        )

    def get(self):
        try:
            if TEMPLATE_PATH.exists():
                html = TEMPLATE_PATH.read_text(encoding="utf-8")
            else:
                html = "<h1>Darfin Storage WebApp Template Not Found</h1>"
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        except Exception as e:
            log.error("Error loading WebApp template: %s", e)
            self.set_status(500)
            self.write("Error loading WebApp")

    def head(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_status(200)


class DropzonePageHandler(tornado.web.RequestHandler):
    """Serve the public Dropzone upload webpage."""
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    def get(self, token: str):
        try:
            if DROPZONE_TEMPLATE_PATH.exists():
                html = DROPZONE_TEMPLATE_PATH.read_text(encoding="utf-8")
            else:
                html = "<h1>Dropzone Template Not Found</h1>"
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        except Exception as e:
            log.error("Error loading Dropzone template: %s", e)
            self.set_status(500)
            self.write("Error loading Dropzone")


class PublicFileSharePageHandler(tornado.web.RequestHandler):
    """Serve the public file view/download page with strict policy enforcement."""
    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    async def get(self, token: str):
        try:
            is_download = self.get_argument("download", "0") in ("1", "true")
            pin = self.get_argument("pin", None)

            f, err = db.validate_public_share(token, pin=pin)
            if err == "NOT_FOUND" or not f:
                self.set_status(404)
                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.write("""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tautan Tidak Valid - Darfin Storage</title>
    <style>
        body { background: #070B14; color: #F8FAFC; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; text-align: center; }
        .card { background: rgba(15,23,42,0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px 24px; max-width: 400px; }
        h2 { color: #f43f5e; margin-bottom: 8px; }
        p { color: #94A3B8; font-size: 0.9rem; }
    </style>
</head>
<body>
    <div class="card">
        <h2>⚠️ Tautan Tidak Valid</h2>
        <p>Berkas ini tidak ditemukan, telah dihapus, atau tautan publiknya telah dinonaktifkan oleh pemilik.</p>
    </div>
</body>
</html>""")
                return

            if err in ("EXPIRED", "LIMIT_EXHAUSTED"):
                self.set_status(410)
                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.write("""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tautan Kadaluarsa - Darfin Storage</title>
    <style>body { background: #070B14; color: #F8FAFC; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; text-align: center; }
    .card { background: rgba(15,23,42,0.8); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px 24px; max-width: 400px; }
    h2 { color: #f59e0b; margin-bottom: 8px; } p { color: #94A3B8; font-size: 0.9rem; }</style>
</head>
<body>
    <div class="card">
        <h2>⏳ Tautan Sudah Kadaluarsa</h2>
        <p>Tautan berkas ini telah melewati batas waktu atau batas unduhan maksimum.</p>
    </div>
</body>
</html>""")
                return

            # Direct download request
            if is_download:
                if err in ("PIN_REQUIRED", "PIN_INCORRECT"):
                    # Redirect to file share page for PIN unlock
                    self.redirect(f"/s/{token}")
                    return

                # Record download atomically
                db.record_file_share_download(f["id"])

                try:
                    bot = get_shared_bot()
                    tg_file = await bot.get_file(f["file_id"])
                    if tg_file and tg_file.file_path:
                        self.redirect(tg_file.file_path)
                        return
                except Exception as ex:
                    log.warning("Could not fetch direct CDN for share download: %s", ex)

                bot_me = await get_shared_bot().get_me()
                bot_username = bot_me.username if bot_me else "darfinstoragebot"
                self.redirect(f"https://t.me/{bot_username}?start=sf_{token}")
                return

            if SHARE_FILE_TEMPLATE_PATH.exists():
                html = SHARE_FILE_TEMPLATE_PATH.read_text(encoding="utf-8")
            else:
                html = "<h1>Share Template Not Found</h1>"
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        except Exception as e:
            log.exception("Error in PublicFileSharePageHandler: %s", e)
            self.set_status(500)
            self.write("Error loading shared file")


class ApiAuthSessionHandler(BaseApiHandler):
    """Authenticate Telegram WebApp initData and issue signed session cookie."""
    async def post(self):
        try:
            init_data = self.request.headers.get("X-Telegram-Init-Data")
            req_body = {}
            if self.request.body:
                try:
                    req_body = json.loads(self.request.body.decode("utf-8"))
                    if not init_data:
                        init_data = req_body.get("init_data") or req_body.get("initData")
                except Exception:
                    pass

            if not init_data:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "MISSING_DATA", "message": "init_data is required."}}))
                return

            validated = validate_telegram_init_data(init_data)
            if not validated:
                self.set_status(401)
                self.write(json.dumps({"ok": False, "error": {"code": "INVALID_SIGNATURE", "message": "Validasi Telegram gagal."}}))
                return

            user_id = validated["user_id"]
            db.upsert_user(user_id, username=validated.get("username"), full_name=validated.get("first_name"))
            db.get_or_create_inbox_folder(user_id)

            token = create_session_token(user_id, duration_seconds=86400)
            csrf_token = secrets.token_hex(16)
            is_secure = (self.request.protocol == "https") or ("onrender.com" in self.request.host)
            # Set secure session cookie
            self.set_cookie(
                "tma_session",
                token,
                expires_days=1,
                httponly=True,
                secure=is_secure,
                samesite="Lax" if not is_secure else "None",
            )
            self.set_cookie(
                "tma_csrf",
                csrf_token,
                expires_days=1,
                httponly=False,
                secure=is_secure,
                samesite="Lax" if not is_secure else "None",
            )

            self.write(json.dumps({
                "ok": True,
                "user": {
                    "id": user_id,
                    "first_name": validated.get("first_name", ""),
                    "username": validated.get("username"),
                },
                "token": token,
                "session_token": token,
            }))
        except Exception as e:
            log.exception("Error in ApiAuthSessionHandler.post: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Terjadi kesalahan autentikasi."}}))

    async def get(self):
        user = get_authenticated_user(self)
        if not user:
            self.set_status(401)
            self.write(json.dumps({"ok": False, "error": {"code": "UNAUTHORIZED", "message": "Belum terautentikasi."}}))
            return
        self.write(json.dumps({"ok": True, "user": user}))


class ApiDriveHandler(BaseApiHandler):
    """Retrieve drive contents for authenticated user."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        folder_id_raw = self.get_argument("folder_id", None)
        folder_id = None
        if folder_id_raw and folder_id_raw.isdigit():
            folder_id = int(folder_id_raw)
            if folder_id > 0:
                # Verify folder ownership
                target_fld = db.get_folder(folder_id, user_id=user_id)
                if not target_fld:
                    self.set_status(404)
                    self.write(json.dumps({"ok": False, "error": {"code": "FOLDER_NOT_FOUND", "message": "Folder tidak ditemukan."}}))
                    return
            else:
                folder_id = None

        # Fetch storage diagnostics
        info = db.get_storage_info(user_id)
        total_size_bytes = info.get("total_size", 0)
        by_type = info.get("by_type", {})
        size_by_type = info.get("size_by_type", {})

        categories = [
            ("video", "Video & Film", "🎬", "#38bdf8"),
            ("photo", "Foto & Gambar", "🖼", "#f59e0b"),
            ("document", "Dokumen", "📄", "#10b981"),
            ("audio", "Musik & Audio", "🎵", "#a855f7"),
        ]
        breakdown = []
        accounted_types = set()
        for cat_key, cat_label, cat_emoji, cat_color in categories:
            cnt = by_type.get(cat_key, 0)
            sz = size_by_type.get(cat_key, 0)
            pct = round((sz / total_size_bytes * 100), 1) if total_size_bytes > 0 else 0
            breakdown.append({
                "type": cat_key,
                "label": cat_label,
                "emoji": cat_emoji,
                "color": cat_color,
                "count": cnt,
                "size_bytes": sz,
                "size_formatted": format_size(sz),
                "percent": pct,
            })
            accounted_types.add(cat_key)

        other_cnt = sum(cnt for k, cnt in by_type.items() if k not in accounted_types)
        other_sz = sum(sz for k, sz in size_by_type.items() if k not in accounted_types)
        if other_cnt > 0 or other_sz > 0:
            other_pct = round((other_sz / total_size_bytes * 100), 1) if total_size_bytes > 0 else 0
            breakdown.append({
                "type": "other",
                "label": "Berkas Lainnya",
                "emoji": "📁",
                "color": "#ec4899",
                "count": other_cnt,
                "size_bytes": other_sz,
                "size_formatted": format_size(other_sz),
                "percent": other_pct,
            })

        storage_summary = {
            "total_files": info.get("total_files", 0),
            "total_folders": info.get("total_folders", 0),
            "total_size": format_size(total_size_bytes),
            "total_size_bytes": total_size_bytes,
            "trash_count": info.get("trash_count", 0),
            "breakdown": breakdown,
        }

        # Breadcrumbs
        breadcrumbs = []
        if folder_id:
            raw_path = db.get_folder_path(folder_id, user_id=user_id)
            breadcrumbs = [{"id": f["id"], "name": escape_html(f["name"])} for f in raw_path]

        # Folders
        folders = db.get_folders(user_id, parent_id=folder_id)
        folders_data = []
        for f in folders:
            cnt = db.get_file_count(f["id"], user_id=user_id)
            folders_data.append({
                "id": f["id"],
                "name": f["name"],
                "is_starred": bool(f.get("is_starred", False)),
                "file_count": cnt,
            })

        # Files
        if folder_id:
            files_raw = db.get_all_files_in_folder(folder_id, user_id=user_id)
        else:
            files_raw = db.get_all_user_files(user_id, limit=60)

        # Generate signed auth token for media URLs
        media_auth_token = create_session_token(user_id, duration_seconds=3600)

        files_data = []
        for f in files_raw:
            _, note, tags = parse_file_metadata(f.get("mime_type"))
            has_thumb = bool(f.get("thumbnail_file_id") or f.get("file_type") == "photo")
            files_data.append({
                "id": f["id"],
                "file_name": f.get("file_name", "File"),
                "file_size": f.get("file_size", 0),
                "file_size_formatted": format_size(f.get("file_size", 0)),
                "file_type": f.get("file_type", "document"),
                "is_starred": bool(f.get("is_starred", False)),
                "created_at": f.get("created_at", ""),
                "note": note,
                "tags": tags,
                "has_thumb": has_thumb,
                "thumb_url": f"/api/thumbnail?file_id={f['id']}&auth={media_auth_token}" if has_thumb else None,
                "stream_url": f"/api/download?file_id={f['id']}&auth={media_auth_token}" if f.get("file_type") == "photo" else None,
            })

        self.write(json.dumps({
            "ok": True,
            "storage": storage_summary,
            "breadcrumbs": breadcrumbs,
            "folders": folders_data,
            "files": files_data,
        }))


# In-memory thumbnail cache
_THUMB_CACHE: dict[int, bytes] = {}
_MAX_THUMB_CACHE = 250
_MAX_THUMB_BYTES = 500 * 1024  # 500 KB per entry limit
_shared_bot_instance: Optional[Bot] = None


def get_shared_bot() -> Bot:
    global _shared_bot_instance
    if _shared_bot_instance is None:
        _shared_bot_instance = Bot(BOT_TOKEN)
    return _shared_bot_instance


class ApiThumbnailHandler(tornado.web.RequestHandler):
    """Serve thumbnail image with ownership validation or active share verification."""
    async def get(self):
        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write("Invalid file_id")
            return

        file_id = int(file_id_raw)

        # Authenticate requester
        user = get_authenticated_user(self)
        user_id = user["user_id"] if user else None

        # Check public share fallback
        share_token = self.get_argument("share_token", None)
        is_authorized = False

        if user_id:
            f = db.get_file(file_id, user_id=user_id)
            if f:
                is_authorized = True
        elif share_token:
            shared_file, err = db.validate_public_share(share_token)
            if shared_file and shared_file["id"] == file_id:
                f = shared_file
                is_authorized = True

        if not is_authorized:
            self.set_status(401 if not user_id else 404)
            self.write("Unauthorized or file not found")
            return

        # RAM Cache hit
        if file_id in _THUMB_CACHE:
            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Cache-Control", "private, max-age=86400")
            self.set_header("X-Content-Type-Options", "nosniff")
            self.write(_THUMB_CACHE[file_id])
            return

        thumb_id = f.get("thumbnail_file_id")
        if not thumb_id and f.get("file_type") == "photo":
            thumb_id = f.get("file_id")

        if not thumb_id:
            self.set_status(404)
            self.write("No thumbnail")
            return

        try:
            bot = get_shared_bot()
            tg_file = await bot.get_file(thumb_id)
            if not tg_file or not tg_file.file_path:
                self.set_status(404)
                return

            client = tornado.httpclient.AsyncHTTPClient()
            resp = await client.fetch(tg_file.file_path, request_timeout=6.0)

            if len(resp.body) <= _MAX_THUMB_BYTES:
                _THUMB_CACHE[file_id] = resp.body
                if len(_THUMB_CACHE) > _MAX_THUMB_CACHE:
                    _THUMB_CACHE.pop(next(iter(_THUMB_CACHE)))

            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Cache-Control", "private, max-age=86400")
            self.set_header("X-Content-Type-Options", "nosniff")
            self.write(resp.body)
        except Exception as e:
            log.warning("Could not fetch thumbnail for file %s: %s", file_id, e)
            self.set_status(404)


class ApiDownloadHandler(tornado.web.RequestHandler):
    """Directly stream or redirect to Telegram CDN for file owned by authenticated user."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write("Invalid file_id")
            return

        file_id = int(file_id_raw)
        f = db.get_file(file_id, user_id=user_id)
        if not f or f.get("is_trashed"):
            self.set_status(404)
            self.write("File not found")
            return

        try:
            bot = get_shared_bot()
            tg_file = await bot.get_file(f["file_id"])
            if tg_file and tg_file.file_path:
                self.redirect(tg_file.file_path)
                return
        except Exception as e:
            log.warning("Could not fetch CDN url for file %s: %s", file_id, e)

        bot_me = await get_shared_bot().get_me()
        bot_username = bot_me.username if bot_me else "darfinstoragebot"
        self.redirect(f"https://t.me/{bot_username}?start=sf_{f.get('share_token') or f['id']}")


class ApiStarHandler(BaseApiHandler):
    """Toggle star on owned file or folder."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id = data.get("file_id")
            folder_id = data.get("folder_id")

            if file_id and str(file_id).isdigit():
                res = db.toggle_star_file(int(file_id), user_id=user_id)
            elif folder_id and str(folder_id).isdigit():
                res = db.toggle_star_folder(int(folder_id), user_id=user_id)
            else:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "ID berkas atau folder wajib disertakan."}}))
                return

            if res is None:
                self.set_status(404)
                self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Berkas atau folder tidak ditemukan."}}))
                return

            self.write(json.dumps({"ok": True, "is_starred": res}))
        except Exception as e:
            log.exception("Error in ApiStarHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengubah status bintang."}}))


async def _send_single_file_to_chat(bot: Bot, user_id: int, f: dict):
    import keyboards as kb
    from utils import file_emoji, format_size, parse_file_metadata
    emoji = file_emoji(f["file_type"])
    size = format_size(f.get("file_size", 0))
    created = f.get("created_at", "")[:10]
    _, note, tags = parse_file_metadata(f.get("mime_type"))
    note_line = f"\n📝 <i>{escape_html(note)}</i>" if note else ""
    tags_line = f"\n🏷 " + " ".join(f"#{escape_html(t)}" for t in tags) if tags else ""
    safe_name = escape_html(f["file_name"])
    caption = f"{emoji} <b>{safe_name}</b>\n📊 {size} • 📅 {created}{note_line}{tags_line}"
    markup = kb.file_actions(f)

    ftype = f.get("file_type", "document")
    fid = f["file_id"]
    thumb_fid = f.get("thumbnail_file_id")

    file_name = (f.get("file_name") or "").lower()
    mime_type = (f.get("mime_type") or "").lower()
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff"}
    is_image = (
        ftype == "photo"
        or mime_type.startswith("image/")
        or any(file_name.endswith(ext) for ext in image_extensions)
    )

    if is_image:
        try:
            await bot.send_photo(chat_id=user_id, photo=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
            return
        except Exception:
            pass

        if thumb_fid:
            try:
                await bot.send_photo(chat_id=user_id, photo=thumb_fid, caption=caption, parse_mode="HTML", reply_markup=markup)
                return
            except Exception:
                pass

        buf = None
        if f.get("file_size", 0) <= 20 * 1024 * 1024:
            try:
                tg_file = await bot.get_file(fid)
                buf = await tg_file.download_as_bytearray()
            except Exception:
                buf = None

        if not buf and thumb_fid:
            try:
                tg_file = await bot.get_file(thumb_fid)
                buf = await tg_file.download_as_bytearray()
            except Exception:
                buf = None

        if buf:
            try:
                sent = await bot.send_photo(chat_id=user_id, photo=bytes(buf), caption=caption, parse_mode="HTML", reply_markup=markup)
                if sent and sent.photo:
                    db.update_file_thumbnail(f["id"], sent.photo[-1].file_id, file_type="photo")
                return
            except Exception:
                pass

        await bot.send_document(chat_id=user_id, document=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
        return
    elif ftype == "video":
        await bot.send_video(chat_id=user_id, video=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
    elif ftype == "audio":
        await bot.send_audio(chat_id=user_id, audio=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
    elif ftype == "voice":
        await bot.send_voice(chat_id=user_id, voice=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
    elif ftype == "animation":
        await bot.send_animation(chat_id=user_id, animation=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
    elif ftype == "video_note":
        await bot.send_video_note(chat_id=user_id, video_note=fid, reply_markup=markup)
        await bot.send_message(chat_id=user_id, text=caption, parse_mode="HTML")
    else:
        await bot.send_document(chat_id=user_id, document=fid, caption=caption, parse_mode="HTML", reply_markup=markup)


class ApiSendToChatHandler(BaseApiHandler):
    """Sends file to authenticated user's Telegram chat."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id_raw = data.get("file_id")
            if not file_id_raw or not str(file_id_raw).isdigit():
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "file_id wajib disertakan."}}))
                return

            file_id = int(file_id_raw)
            f = db.get_file(file_id, user_id=user_id)
            if not f or f.get("is_trashed"):
                self.set_status(404)
                self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Berkas tidak ditemukan."}}))
                return

            bot = get_shared_bot()
            await _send_single_file_to_chat(bot, user_id, f)
            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Failed to send file to chat: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengirim berkas ke Telegram."}}))


class ApiBatchSendToChatHandler(BaseApiHandler):
    """Batch sends multiple owned files into authenticated user's Telegram chat."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            if not isinstance(file_ids, list) or not file_ids:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "file_ids wajib berupa array."}}))
                return

            # Cap batch size to prevent rate-limit flooding
            unique_ids = list(dict.fromkeys(int(fid) for fid in file_ids if str(fid).isdigit()))[:30]

            bot = get_shared_bot()
            sent = 0
            for fid in unique_ids:
                try:
                    f = db.get_file(fid, user_id=user_id)
                    if not f or f.get("is_trashed"):
                        continue
                    await _send_single_file_to_chat(bot, user_id, f)
                    sent += 1
                    await asyncio.sleep(0.3)
                except Exception as ex:
                    log.warning("Failed sending batch file %s to chat: %s", fid, ex)

            self.write(json.dumps({"ok": True, "sent_count": sent}))
        except Exception as e:
            log.exception("Error batch sending files to chat: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengirim batch berkas."}}))


class ApiAllFoldersHandler(BaseApiHandler):
    """Returns list of all authenticated user's folders."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        folders = db.get_all_folders(user_id)
        data = []
        for f in folders:
            cnt = db.get_file_count(f["id"], user_id=user_id)
            data.append({
                "id": f["id"],
                "name": f["name"],
                "parent_id": f.get("parent_id"),
                "file_count": cnt,
            })
        self.write(json.dumps({"ok": True, "folders": data}))


class ApiBatchMoveHandler(BaseApiHandler):
    """Batch moves multiple owned files to a target folder owned by user."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            target_folder_id = data.get("target_folder_id")

            if not file_ids or target_folder_id is None:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Parameter tidak lengkap."}}))
                return

            target_folder_id = int(target_folder_id)
            if target_folder_id == 0:
                inbox = db.get_or_create_inbox_folder(user_id)
                target_folder_id = inbox["id"]
                folder_name = inbox["name"]
            else:
                tf = db.get_folder(target_folder_id, user_id=user_id)
                if not tf:
                    self.set_status(404)
                    self.write(json.dumps({"ok": False, "error": {"code": "FOLDER_NOT_FOUND", "message": "Folder tujuan tidak ditemukan."}}))
                    return
                folder_name = tf["name"]

            unique_ids = list(dict.fromkeys(int(fid) for fid in file_ids if str(fid).isdigit()))[:100]
            moved = 0
            for fid in unique_ids:
                if db.move_file(fid, target_folder_id, user_id=user_id):
                    moved += 1

            self.write(json.dumps({"ok": True, "count": moved, "folder_name": folder_name}))
        except Exception as e:
            log.exception("Error batch moving files: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal memindahkan berkas."}}))


class ApiCreateFolderHandler(BaseApiHandler):
    """Create new folder in drive."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            name = sanitize_filename(data.get("name") or "").strip()
            parent_id = data.get("parent_id")
            if not name:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Nama folder wajib diisi."}}))
                return

            parent_id_clean = int(parent_id) if parent_id and str(parent_id).isdigit() and int(parent_id) > 0 else None
            folder = db.create_folder(user_id, name, parent_id_clean)
            if not folder:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "CREATE_FAILED", "message": "Gagal membuat folder."}}))
                return

            self.write(json.dumps({"ok": True, "folder": folder}))
        except Exception as e:
            log.exception("Error create folder: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal membuat folder."}}))


class ApiRenameHandler(BaseApiHandler):
    """Rename owned file or folder."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            item_type = data.get("type", "file")
            item_id = data.get("id")
            new_name = sanitize_filename(data.get("new_name") or "").strip()

            if not item_id or not str(item_id).isdigit() or not new_name:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "ID dan nama baru wajib diisi."}}))
                return

            item_id = int(item_id)
            if item_type == "folder":
                ok = db.rename_folder(item_id, new_name, user_id=user_id)
            else:
                ok = db.rename_file(item_id, new_name, user_id=user_id)

            if not ok:
                self.set_status(404)
                self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Objek tidak ditemukan atau akses ditolak."}}))
                return

            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Error rename: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengubah nama."}}))


class ApiBatchDeleteHandler(BaseApiHandler):
    """Trash/delete owned files and folders."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            folder_ids = data.get("folder_ids", [])

            del_files = 0
            if isinstance(file_ids, list):
                for fid in list(dict.fromkeys(int(f) for f in file_ids if str(f).isdigit()))[:100]:
                    if db.trash_file(fid, user_id=user_id):
                        del_files += 1

            del_folders = 0
            if isinstance(folder_ids, list):
                for fld_id in list(dict.fromkeys(int(f) for f in folder_ids if str(f).isdigit()))[:50]:
                    if db.delete_folder(fld_id, user_id=user_id):
                        del_folders += 1

            self.write(json.dumps({
                "ok": True,
                "deleted_files": del_files,
                "deleted_folders": del_folders,
            }))
        except Exception as e:
            log.exception("Error batch delete: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal menghapus berkas."}}))


class ApiBatchStarHandler(BaseApiHandler):
    """Batch star/unstar owned files."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            is_starred = bool(data.get("is_starred", True))

            updated = 0
            if isinstance(file_ids, list):
                for fid in list(dict.fromkeys(int(f) for f in file_ids if str(f).isdigit()))[:100]:
                    f = db.get_file(fid, user_id=user_id)
                    if f:
                        db.db.table("files").update({"is_starred": is_starred, "updated_at": db._now()}).eq("id", fid).eq("user_id", user_id).execute()
                        updated += 1

            self.write(json.dumps({"ok": True, "count": updated}))
        except Exception as e:
            log.exception("Error batch star: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal memperbarui favorit."}}))


class ApiUploadHandler(BaseApiHandler):
    """Direct file upload from authenticated WebApp with size guards."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            folder_id_raw = self.get_argument("folder_id", None)
            folder_id = None
            if folder_id_raw and folder_id_raw.isdigit() and int(folder_id_raw) > 0:
                f_obj = db.get_folder(int(folder_id_raw), user_id=user_id)
                if f_obj:
                    folder_id = f_obj["id"]

            if not folder_id:
                inbox = db.get_or_create_inbox_folder(user_id)
                folder_id = inbox["id"]
                folder_name = inbox["name"]
            else:
                f_obj = db.get_folder(folder_id, user_id=user_id)
                folder_name = f_obj["name"] if f_obj else "Folder"

            uploaded_files = self.request.files.get("files", [])
            if not uploaded_files:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "NO_FILES", "message": "Tidak ada berkas yang diunggah."}}))
                return

            if len(uploaded_files) > MAX_UPLOAD_BATCH_FILES:
                self.set_status(400)
                self.write(json.dumps({
                    "ok": False,
                    "error": {
                        "code": "BATCH_LIMIT_EXCEEDED",
                        "message": f"Maksimal {MAX_UPLOAD_BATCH_FILES} berkas sekaligus per batch.",
                    },
                }))
                return

            max_single_bytes = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
            max_batch_bytes = MAX_UPLOAD_BATCH_MB * 1024 * 1024
            total_batch_bytes = sum(len(finfo["body"]) for finfo in uploaded_files)

            if total_batch_bytes > max_batch_bytes:
                self.set_status(400)
                self.write(json.dumps({
                    "ok": False,
                    "error": {
                        "code": "TOTAL_SIZE_EXCEEDED",
                        "message": f"Total ukuran batch melebihi batas {MAX_UPLOAD_BATCH_MB} MB.",
                    },
                }))
                return

            bot = get_shared_bot()
            saved_count = 0
            failed_count = 0
            failed_files = []

            for fileinfo in uploaded_files:
                raw_filename = fileinfo["filename"]
                filename = sanitize_filename(raw_filename)
                body = fileinfo["body"]
                content_type = fileinfo.get("content_type", "application/octet-stream")
                size = len(body)

                if size > max_single_bytes:
                    failed_count += 1
                    failed_files.append({"name": filename, "reason": f"Ukuran melebihi {MAX_UPLOAD_FILE_SIZE_MB} MB"})
                    continue

                lower_name = filename.lower()
                thumb_fid = None
                try:
                    if any(lower_name.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                        ftype = "photo"
                        msg = await bot.send_document(chat_id=user_id, document=body, filename=filename, caption=f"📤 Diunggah via WebApp ke 📁 {folder_name}")
                        fid = msg.document.file_id
                        fuid = msg.document.file_unique_id
                        thumb_fid = msg.document.thumbnail.file_id if msg.document.thumbnail else None
                    elif any(lower_name.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".webm"]):
                        ftype = "video"
                        msg = await bot.send_video(chat_id=user_id, video=body, caption=f"📤 Diunggah via WebApp ke 📁 {folder_name}")
                        fid = msg.video.file_id
                        fuid = msg.video.file_unique_id
                        thumb_fid = msg.video.thumbnail.file_id if msg.video.thumbnail else None
                    elif any(lower_name.endswith(ext) for ext in [".mp3", ".wav", ".flac", ".m4a"]):
                        ftype = "audio"
                        msg = await bot.send_audio(chat_id=user_id, audio=body, caption=f"📤 Diunggah via WebApp ke 📁 {folder_name}")
                        fid = msg.audio.file_id
                        fuid = msg.audio.file_unique_id
                        thumb_fid = msg.audio.thumbnail.file_id if msg.audio.thumbnail else None
                    else:
                        ftype = "document"
                        from io import BytesIO
                        bio = BytesIO(body)
                        bio.name = filename
                        msg = await bot.send_document(chat_id=user_id, document=bio, filename=filename, caption=f"📤 Diunggah via WebApp ke 📁 {folder_name}")
                        fid = msg.document.file_id
                        fuid = msg.document.file_unique_id
                        thumb_fid = msg.document.thumbnail.file_id if msg.document.thumbnail else None

                    saved = db.save_file(
                        user_id=user_id,
                        folder_id=folder_id,
                        file_id=fid,
                        file_unique_id=fuid,
                        file_name=filename,
                        file_size=size,
                        file_type=ftype,
                        mime_type=content_type,
                        thumbnail_file_id=thumb_fid,
                    )
                    if saved:
                        saved_count += 1
                        # Task 1 Read-only Intelligence Analysis hook (non-blocking)
                        try:
                            from darfin_intelligence import analyze as run_intelligence
                            intel_res = run_intelligence(
                                filename=filename,
                                mime_type=content_type,
                                file_type=ftype,
                                file_id=saved.get("id") if isinstance(saved, dict) else None,
                            )
                            log.info(
                                "Intelligence analyzed file_id=%s parser=%s status=%s family=%s",
                                saved.get("id") if isinstance(saved, dict) else None,
                                intel_res.parser_name,
                                intel_res.status,
                                intel_res.file_type.family if intel_res.file_type else None,
                            )
                        except Exception as intel_err:
                            log.warning("Intelligence analysis failed (non-blocking) for %s: %s", filename, intel_err)
                    else:
                        failed_count += 1
                        failed_files.append({"name": filename, "reason": "Gagal menyimpan database"})
                except Exception as upload_err:
                    log.warning("Failed uploading file %s: %s", filename, upload_err)
                    failed_count += 1
                    failed_files.append({"name": filename, "reason": "Kesalahan transfer Telegram"})

            if saved_count == 0 and failed_count > 0:
                self.set_status(400)
                first_reason = failed_files[0]["reason"] if failed_files else "Semua berkas gagal diunggah."
                self.write(json.dumps({
                    "ok": False,
                    "error": {
                        "code": "FILE_TOO_LARGE" if "Ukuran melebihi" in first_reason else "UPLOAD_FAILED",
                        "message": f"Berkas melebihi batas: {first_reason}",
                    },
                    "failed_files": failed_files,
                }))
                return

            self.write(json.dumps({
                "ok": True,
                "count": saved_count,
                "failed_count": failed_count,
                "failed_files": failed_files,
            }))
        except Exception as e:
            log.exception("Error in ApiUploadHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal memproses unggahan."}}))


class ApiFileContentHandler(BaseApiHandler):
    """Fetches text content preview for owned file asynchronously."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Invalid file_id."}}))
            return

        f = db.get_file(int(file_id_raw), user_id=user_id)
        if not f or f.get("is_trashed"):
            self.set_status(404)
            self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Berkas tidak ditemukan."}}))
            return

        if f.get("file_size", 0) > 2 * 1024 * 1024:
            self.set_status(400)
            self.write(json.dumps({"ok": False, "error": {"code": "TOO_LARGE", "message": "Berkas terlalu besar untuk pratinjau teks (> 2MB)."}}))
            return

        try:
            bot = get_shared_bot()
            tg_file = await bot.get_file(f["file_id"])
            if not tg_file or not tg_file.file_path:
                self.set_status(404)
                self.write(json.dumps({"ok": False, "error": {"code": "CDN_ERROR", "message": "Gagal mengambil jalur berkas."}}))
                return

            client = tornado.httpclient.AsyncHTTPClient()
            resp = await client.fetch(tg_file.file_path, request_timeout=8.0)
            content = resp.body.decode("utf-8", errors="replace")

            self.write(json.dumps({"ok": True, "content": content[:80000]}))
        except Exception as e:
            log.exception("Error fetching file content: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal membaca isi berkas."}}))


class ApiDropzoneInfoHandler(BaseApiHandler):
    """Fetch folder details by exact Dropzone share token."""
    async def get(self):
        token = self.get_argument("token", None)
        if not token:
            self.set_status(400)
            self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Token wajib diisi."}}))
            return

        folder = db.get_folder_by_share_token(token)
        if not folder:
            self.set_status(404)
            self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Tautan Dropzone tidak valid atau telah dinonaktifkan."}}))
            return

        user = db.get_user(folder["user_id"])
        owner_name = user.get("full_name") or user.get("username") or "Darfin Storage"

        self.write(json.dumps({
            "ok": True,
            "folder": {
                "id": folder["id"],
                "name": escape_html(folder["name"]),
                "owner_name": escape_html(owner_name),
            }
        }))


class ApiDropzoneUploadHandler(BaseApiHandler):
    """Public multi-file upload into Dropzone with strict rate limiting and size caps."""
    async def post(self):
        # Rate limit by client IP: max 8 uploads per 60 seconds
        client_ip = self.request.remote_ip or "unknown"
        if not check_rate_limit(f"dz_up:{client_ip}", max_requests=8, window_seconds=60):
            self.set_status(429)
            self.write(json.dumps({"ok": False, "error": {"code": "RATE_LIMITED", "message": "Terlalu banyak permintaan unggah. Tunggu 1 menit."}}))
            return

        try:
            token = self.get_argument("token", None)
            sender_name = sanitize_filename(self.get_argument("sender_name", "") or "").strip() or "Tamu Dropzone"

            if not token:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Token wajib diisi."}}))
                return

            folder = db.get_folder_by_share_token(token)
            if not folder:
                self.set_status(404)
                self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Folder Dropzone tidak ditemukan."}}))
                return

            user_id = folder["user_id"]
            folder_id = folder["id"]
            folder_name = folder["name"]

            uploaded_files = self.request.files.get("files", [])
            if not uploaded_files:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "NO_FILES", "message": "Tidak ada berkas yang diunggah."}}))
                return

            if len(uploaded_files) > MAX_UPLOAD_BATCH_FILES:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BATCH_LIMIT_EXCEEDED", "message": f"Maksimal {MAX_UPLOAD_BATCH_FILES} berkas sekaligus."}}))
                return

            max_single_bytes = MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024
            max_batch_bytes = MAX_UPLOAD_BATCH_MB * 1024 * 1024
            total_bytes = sum(len(finfo["body"]) for finfo in uploaded_files)

            if total_bytes > max_batch_bytes:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "TOTAL_SIZE_EXCEEDED", "message": f"Total berkas melebihi {MAX_UPLOAD_BATCH_MB} MB."}}))
                return

            bot = get_shared_bot()
            saved_count = 0
            file_names_summary = []

            for file_info in uploaded_files:
                filename = sanitize_filename(file_info["filename"])
                body = file_info["body"]
                size = len(body)
                if size > max_single_bytes:
                    continue

                file_names_summary.append(filename)
                lower_name = filename.lower()
                thumb_fid = None
                caption_note = f"📥 Masuk via Dropzone oleh: {sender_name} ke 📁 {folder_name}"

                try:
                    if any(lower_name.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                        ftype = "photo"
                        msg = await bot.send_photo(chat_id=user_id, photo=body, caption=caption_note)
                        fid = msg.photo[-1].file_id
                        fuid = msg.photo[-1].file_unique_id
                        thumb_fid = msg.photo[0].file_id if len(msg.photo) > 1 else None
                    elif any(lower_name.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".webm"]):
                        ftype = "video"
                        msg = await bot.send_video(chat_id=user_id, video=body, caption=caption_note)
                        fid = msg.video.file_id
                        fuid = msg.video.file_unique_id
                        thumb_fid = msg.video.thumbnail.file_id if msg.video.thumbnail else None
                    elif any(lower_name.endswith(ext) for ext in [".mp3", ".wav", ".flac", ".m4a"]):
                        ftype = "audio"
                        msg = await bot.send_audio(chat_id=user_id, audio=body, caption=caption_note)
                        fid = msg.audio.file_id
                        fuid = msg.audio.file_unique_id
                        thumb_fid = msg.audio.thumbnail.file_id if msg.audio.thumbnail else None
                    else:
                        ftype = "document"
                        from io import BytesIO
                        bio = BytesIO(body)
                        bio.name = filename
                        msg = await bot.send_document(chat_id=user_id, document=bio, filename=filename, caption=caption_note)
                        fid = msg.document.file_id
                        fuid = msg.document.file_unique_id
                        thumb_fid = msg.document.thumbnail.file_id if msg.document.thumbnail else None

                    note = f"Dikirim via Dropzone oleh: {sender_name}"
                    mime_str = f"text/plain;;;{note};;;dropzone"
                    db.save_file(
                        user_id=user_id,
                        folder_id=folder_id,
                        file_id=fid,
                        file_unique_id=fuid,
                        file_name=filename,
                        file_size=size,
                        file_type=ftype,
                        mime_type=mime_str,
                        thumbnail_file_id=thumb_fid,
                    )
                    saved_count += 1
                    await asyncio.sleep(0.2)
                except Exception as single_err:
                    log.warning("Dropzone item upload failed: %s", single_err)

            # Send notification to owner
            if saved_count > 0:
                try:
                    summary_text = (
                        f"📥 <b>Dropzone: Berkas Baru Diterima!</b>\n\n"
                        f"📁 <b>Folder:</b> {escape_html(folder_name)}\n"
                        f"👤 <b>Pengirim:</b> {escape_html(sender_name)}\n"
                        f"📦 <b>Jumlah:</b> {saved_count} berkas ({format_size(total_bytes)})\n"
                        f"📄 <b>Daftar:</b>\n" + "\n".join(f"• {escape_html(fn)}" for fn in file_names_summary[:5])
                    )
                    if len(file_names_summary) > 5:
                        summary_text += f"\n<i>...dan {len(file_names_summary) - 5} berkas lainnya</i>"
                    await bot.send_message(chat_id=user_id, text=summary_text, parse_mode="HTML")
                except Exception as alert_err:
                    log.warning("Could not send dropzone notification to owner: %s", alert_err)

            self.write(json.dumps({"ok": True, "count": saved_count}))
        except Exception as e:
            log.exception("Error in ApiDropzoneUploadHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengunggah berkas ke Dropzone."}}))


class ApiFolderDropzoneHandler(BaseApiHandler):
    """Manage folder Dropzone link (get/create/revoke)."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            folder_id_raw = data.get("folder_id")
            action = data.get("action", "get")

            if not folder_id_raw or not str(folder_id_raw).isdigit():
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "folder_id wajib diisi."}}))
                return

            folder_id = int(folder_id_raw)
            folder = db.get_folder(folder_id, user_id=user_id)
            if not folder:
                self.set_status(403)
                self.write(json.dumps({"ok": False, "error": {"code": "FORBIDDEN", "message": "Folder tidak ditemukan atau akses ditolak."}}))
                return

            if action == "revoke":
                db.revoke_folder_share_token(folder_id, user_id=user_id)
                self.write(json.dumps({"ok": True, "active": False}))
                return

            token = db.get_or_create_folder_share_token(folder_id, user_id=user_id)
            base_url = PUBLIC_BASE_URL or f"{self.request.protocol}://{self.request.host}"
            dropzone_url = f"{base_url}/dropzone/{token}"

            self.write(json.dumps({
                "ok": True,
                "active": True,
                "token": token,
                "dropzone_url": dropzone_url,
                "folder_name": folder["name"],
            }))
        except Exception as e:
            log.exception("Error in ApiFolderDropzoneHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengatur Dropzone."}}))


class ApiFileShareLinkHandler(BaseApiHandler):
    """Manage file public share link (get/create/revoke/update_security)."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id_raw = data.get("file_id")
            action = data.get("action", "get")

            if not file_id_raw or not str(file_id_raw).isdigit():
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "file_id wajib disertakan."}}))
                return

            file_id = int(file_id_raw)
            f = db.get_file(file_id, user_id=user_id)
            if not f or f.get("is_trashed"):
                self.set_status(403)
                self.write(json.dumps({"ok": False, "error": {"code": "FORBIDDEN", "message": "Berkas tidak ditemukan atau akses ditolak."}}))
                return

            if action == "revoke":
                db.revoke_file_share_token(file_id, user_id=user_id)
                self.write(json.dumps({"ok": True, "active": False}))
                return

            if action == "set_security":
                pin = data.get("pin")
                expires_at = data.get("expires_at")
                limit = data.get("limit")
                clear_all = bool(data.get("clear_all", False))
                db.update_file_share_security(
                    file_id,
                    expires_at=expires_at if expires_at is not None else db._UNSET,
                    pin=pin if pin is not None else db._UNSET,
                    limit=limit if limit is not None else db._UNSET,
                    clear_all=clear_all,
                    user_id=user_id,
                )

            token = db.get_or_create_file_share_token(file_id, user_id=user_id)
            base_url = PUBLIC_BASE_URL or f"{self.request.protocol}://{self.request.host}"
            share_url = f"{base_url}/s/{token}"
            direct_dl_url = f"{base_url}/s/{token}?download=1"

            self.write(json.dumps({
                "ok": True,
                "active": True,
                "share_token": token,
                "share_url": share_url,
                "direct_download_url": direct_dl_url,
                "file_name": f["file_name"],
                "file_size_formatted": format_size(f.get("file_size", 0)),
                "file_type": f.get("file_type", "document")
            }))
        except Exception as e:
            log.exception("Error in ApiFileShareLinkHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengatur tautan berbagi."}}))


class ApiShareFileInfoHandler(BaseApiHandler):
    """Fetch public file metadata by exact share token with PIN gate enforcement."""
    async def get(self):
        token = self.get_argument("token", None)
        pin = self.get_argument("pin", None)

        if not token:
            self.set_status(400)
            self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Token wajib diisi."}}))
            return

        # Rate limit PIN guesses: max 5 attempts per 60 seconds per IP+token
        client_ip = self.request.remote_ip or "unknown"
        if pin and not check_rate_limit(f"pin_try:{client_ip}:{token}", max_requests=5, window_seconds=60):
            self.set_status(429)
            self.write(json.dumps({"ok": False, "error": {"code": "RATE_LIMITED", "message": "Terlalu banyak percobaan PIN. Coba lagi dalam 1 menit."}}))
            return

        f, err = db.validate_public_share(token, pin=pin)
        if err == "NOT_FOUND" or not f:
            self.set_status(404)
            self.write(json.dumps({"ok": False, "error": {"code": "NOT_FOUND", "message": "Berkas tidak ditemukan atau telah dihapus."}}))
            return

        if err in ("EXPIRED", "LIMIT_EXHAUSTED"):
            self.set_status(410)
            self.write(json.dumps({"ok": False, "error": {"code": err, "message": "Tautan telah kadaluarsa atau batas unduhan habis."}}))
            return

        if err == "PIN_REQUIRED":
            # Tell client PIN is required to unlock
            self.write(json.dumps({
                "ok": True,
                "pin_required": True,
                "file": {
                    "name": sanitize_filename(f["file_name"]),
                    "size_formatted": format_size(f.get("file_size", 0)),
                    "type": f.get("file_type", "document"),
                }
            }))
            return

        if err == "PIN_INCORRECT":
            self.set_status(403)
            self.write(json.dumps({"ok": False, "error": {"code": "PIN_INCORRECT", "message": "PIN yang dimasukkan salah."}}))
            return

        bot = get_shared_bot()
        preview_url = None
        # Only provide preview CDN if file type is media and no sensitive restriction remains
        try:
            tg_file = await bot.get_file(f["file_id"])
            if tg_file and tg_file.file_path:
                preview_url = tg_file.file_path
        except Exception:
            pass

        bot_me = await bot.get_me()
        bot_username = bot_me.username if bot_me else "darfinstoragebot"

        self.write(json.dumps({
            "ok": True,
            "pin_required": False,
            "file": {
                "name": f["file_name"],
                "size_formatted": format_size(f.get("file_size", 0)),
                "size_bytes": f.get("file_size", 0),
                "type": f.get("file_type", "document"),
                "mime_type": f.get("mime_type", ""),
                "created_at": f.get("created_at", "")[:10],
                "preview_url": preview_url,
                "download_url": f"/s/{token}?download=1" + (f"&pin={pin}" if pin else ""),
                "bot_url": f"https://t.me/{bot_username}?start=sf_{token}"
            }
        }))


class ApiTrashHandler(BaseApiHandler):
    """List trashed files for authenticated user."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        trash_files = db.get_trash(user_id)
        media_auth_token = create_session_token(user_id, duration_seconds=3600)
        res_files = []
        for f in trash_files:
            has_thumb = bool(f.get("thumbnail_file_id") or f.get("file_type") == "photo")
            res_files.append({
                "id": f["id"],
                "file_name": f.get("file_name", "File"),
                "file_size": f.get("file_size", 0),
                "file_size_formatted": format_size(f.get("file_size", 0)),
                "file_type": f.get("file_type", "document"),
                "trashed_at": f.get("trashed_at", "")[:10] if f.get("trashed_at") else "",
                "has_thumb": has_thumb,
                "thumb_url": f"/api/thumbnail?file_id={f['id']}&auth={media_auth_token}" if has_thumb else None,
            })
        self.write(json.dumps({"ok": True, "files": res_files, "count": len(res_files)}))


class ApiRestoreHandler(BaseApiHandler):
    """Restore owned trashed file(s)."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            if not isinstance(file_ids, list) or not file_ids:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "file_ids wajib diisi."}}))
                return

            restored = 0
            for fid in list(dict.fromkeys(int(f) for f in file_ids if str(f).isdigit()))[:100]:
                if db.restore_file(fid, user_id=user_id):
                    restored += 1

            self.write(json.dumps({"ok": True, "restored_count": restored}))
        except Exception as e:
            log.exception("Error restoring file: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal memulihkan berkas."}}))


class ApiEmptyTrashHandler(BaseApiHandler):
    """Permanently delete all trashed files of authenticated user."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            db.empty_trash(user_id)
            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Error emptying trash: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal mengosongkan tempat sampah."}}))


class ApiDuplicatesHandler(BaseApiHandler):
    """Get duplicate files report for authenticated user."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        health = db.get_storage_health(user_id)
        formatted_groups = []
        for grp in health.get("duplicate_groups", []):
            formatted_groups.append({
                "file_name": grp[0].get("file_name", "Berkas"),
                "file_size_formatted": format_size(grp[0].get("file_size", 0)),
                "count": len(grp),
                "wasted_size": format_size(sum(item.get("file_size", 0) for item in grp[1:])),
                "items": [{
                    "id": item["id"],
                    "folder_name": (item.get("folders") or {}).get("name") if isinstance(item.get("folders"), dict) else "Inbox"
                } for item in grp]
            })

        self.write(json.dumps({
            "ok": True,
            "total_duplicates": health.get("total_duplicates", 0),
            "dup_wasted_size": format_size(health.get("dup_wasted_size", 0)),
            "groups": formatted_groups,
        }))


class ApiCleanDuplicatesHandler(BaseApiHandler):
    """One-click cleanup redundant duplicate copies to trash for authenticated user."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            cleaned = db.clean_duplicate_files(user_id)
            self.write(json.dumps({"ok": True, "cleaned_count": cleaned}))
        except Exception as e:
            log.exception("Error cleaning duplicates: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal membersihkan duplikat."}}))


class ApiOrganizerPreviewHandler(BaseApiHandler):
    """Generate dry-run smart organization suggestions for authenticated user."""
    async def get(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            from darfin_intelligence.organizer import SafeOrganizer
            folders = db.get_all_folders(user_id)
            files = db.get_all_user_files(user_id, limit=100)
            user_prefs = db.get_user_preferences(user_id)

            plan = SafeOrganizer.preview(
                files=files,
                folders=folders,
                user_id=user_id,
                user_preferences=user_prefs,
            )
            self.write(json.dumps({
                "ok": True,
                "plan": plan.to_dict(),
            }))
        except Exception as e:
            log.exception("Error generating smart organizer plan: %s", e)
            self.set_status(500)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "SERVER_ERROR", "message": "Gagal menganalisis saran penataan."},
            }))


class ApiPreferencesFeedbackHandler(BaseApiHandler):
    """Record user feedback (accepted, rejected, corrected) on folder suggestions."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id = data.get("file_id")
            action = data.get("action", "accepted")
            suggested_folder_id = data.get("suggested_folder_id")
            correct_folder_id = data.get("correct_folder_id")

            if not file_id:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "file_id wajib diisi."}}))
                return

            # 1. Verify file ownership
            f = db.get_file(int(file_id), user_id=user_id)
            if not f:
                self.set_status(403)
                self.write(json.dumps({"ok": False, "error": {"code": "FORBIDDEN", "message": "Berkas tidak ditemukan atau bukan milik Anda."}}))
                return

            # 2. Determine target folder and verify ownership
            target_folder_id = correct_folder_id if action == "corrected" else suggested_folder_id
            if target_folder_id is not None:
                target_folder_id = int(target_folder_id)
                dest = db.get_folder(target_folder_id, user_id=user_id)
                if not dest:
                    self.set_status(403)
                    self.write(json.dumps({"ok": False, "error": {"code": "FORBIDDEN", "message": "Folder tujuan tidak ditemukan atau bukan milik Anda."}}))
                    return
            else:
                self.set_status(400)
                self.write(json.dumps({"ok": False, "error": {"code": "BAD_REQUEST", "message": "Folder tujuan wajib ditentukan."}}))
                return

            # 3. Extract normalized pattern from file name
            from darfin_intelligence.preferences import extract_reusable_patterns
            patterns = extract_reusable_patterns(f.get("file_name", ""))
            pattern = patterns[0] if patterns else f.get("file_name", "").lower()[:20]

            # 4. Record preference (strictly scoped to authenticated user)
            pref = db.record_user_preference(
                user_id=user_id,
                pattern=pattern,
                target_folder_id=target_folder_id,
                action=action,
            )

            self.write(json.dumps({
                "ok": True,
                "action": action,
                "pattern": pattern,
                "target_folder_id": target_folder_id,
                "preference": pref,
            }))
        except Exception as e:
            log.exception("Error recording user preference feedback: %s", e)
            self.set_status(500)
            self.write(json.dumps({"ok": False, "error": {"code": "SERVER_ERROR", "message": "Gagal menyimpan preferensi."}}))


class ApiOrganizerExecuteHandler(BaseApiHandler):
    """Execute verified smart reorganization moves with security rechecks."""
    async def post(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            data = json.loads(self.request.body.decode("utf-8"))
            items = data.get("items")
            if not items and data.get("file_id") and data.get("target_folder_id") is not None:
                items = [data]

            if not items:
                self.set_status(400)
                self.write(json.dumps({
                    "ok": False,
                    "error": {"code": "BAD_REQUEST", "message": "Item pemindahan tidak ditemukan."},
                }))
                return

            from darfin_intelligence.organizer import SafeOrganizer
            res = SafeOrganizer.execute_batch(items=items, user_id=user_id)

            if not res["ok"]:
                self.set_status(207 if res["summary"]["moved"] > 0 else 400)

            self.write(json.dumps(res))
        except Exception as e:
            log.exception("Error executing smart organizer moves: %s", e)
            self.set_status(500)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "SERVER_ERROR", "message": "Gagal menjalankan pemindahan berkas."},
            }))


class ApiSearchHandler(BaseApiHandler):
    """Execute authenticated search query using Task 4 SearchService."""

    async def get(self):
        await self._handle_search()

    async def post(self):
        await self._handle_search()

    async def _handle_search(self):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        try:
            query = ""
            limit = 25
            offset = 0
            sort_by = "relevance"
            ext = None
            fam = None
            folder_id = None
            domain = None
            doc_type = None
            merchant = None
            has_ocr = None

            if self.request.method == "POST" and self.request.body:
                try:
                    body = json.loads(self.request.body.decode("utf-8"))
                    query = body.get("query", body.get("q", ""))
                    limit = int(body.get("limit", 25))
                    offset = int(body.get("offset", 0))
                    sort_by = body.get("sort_by", "relevance")
                    ext = body.get("ext")
                    fam = body.get("type", body.get("family"))
                    folder_id = body.get("folder_id")
                    domain = body.get("domain")
                    doc_type = body.get("document_type")
                    merchant = body.get("merchant")
                    has_ocr = body.get("has_ocr")
                except Exception:
                    pass

            if not query:
                query = self.get_argument("q", self.get_argument("query", ""))
            if self.get_argument("limit", None):
                try:
                    limit = int(self.get_argument("limit"))
                except ValueError:
                    pass
            if self.get_argument("offset", None):
                try:
                    offset = int(self.get_argument("offset"))
                except ValueError:
                    pass
            if self.get_argument("sort_by", None):
                sort_by = self.get_argument("sort_by")
            if self.get_argument("ext", None):
                ext = self.get_argument("ext")
            if self.get_argument("type", None):
                fam = self.get_argument("type")
            if self.get_argument("folder_id", None):
                try:
                    folder_id = int(self.get_argument("folder_id"))
                except ValueError:
                    pass
            if self.get_argument("domain", None):
                domain = self.get_argument("domain")
            if self.get_argument("document_type", None):
                doc_type = self.get_argument("document_type")
            if self.get_argument("merchant", None):
                merchant = self.get_argument("merchant")
            if self.get_argument("has_ocr", None):
                has_ocr = self.get_argument("has_ocr").lower() in ("true", "1", "yes")

            from darfin_intelligence.search import search, SearchFilters
            filters = SearchFilters(
                extension=ext,
                family=fam,
                folder_id=folder_id,
                domain=domain,
                document_type=doc_type,
                merchant=merchant,
                has_ocr=has_ocr,
            )

            user_prefs = db.get_user_preferences(user_id)
            search_result = search(
                user_id=user_id,
                query=query,
                filters=filters,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                preferences=user_prefs,
            )

            media_auth_token = create_session_token(user_id, duration_seconds=3600)
            res_dict = search_result.as_dict()

            for item in res_dict.get("items", []):
                fdata = item.get("file_data", {})
                fid = item.get("asset_id")
                ftype = fdata.get("file_type", "document")
                fsize = fdata.get("file_size", 0) or 0
                fdata["file_size_formatted"] = format_size(fsize)
                has_thumb = bool(fdata.get("thumbnail_file_id") or ftype == "photo")
                fdata["has_thumb"] = has_thumb
                fdata["thumb_url"] = f"/api/thumbnail?file_id={fid}&auth={media_auth_token}" if has_thumb else None
                fdata["stream_url"] = f"/api/download?file_id={fid}&auth={media_auth_token}" if ftype == "photo" else None
                fdata["download_url"] = f"/api/download?file_id={fid}&auth={media_auth_token}"
                fld = fdata.get("folders")
                if isinstance(fld, dict):
                    fdata["folder_name"] = fld.get("name")
                elif isinstance(fld, str):
                    fdata["folder_name"] = fld
                elif not fdata.get("folder_name"):
                    fdata["folder_name"] = None

            self.write(json.dumps({
                "ok": True,
                "result": res_dict,
            }))
        except Exception as e:
            log.exception("Error executing search for user %s: %s", user_id, e)
            self.set_status(500)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "SERVER_ERROR", "message": "Terjadi kesalahan saat mencari berkas."},
            }))


class ApiFileIntelligenceHandler(BaseApiHandler):
    """Retrieve full structured intelligence metadata for a specific file."""

    async def get(self, file_id_param: Optional[str] = None):
        user_id = require_authenticated_user(self)
        if not user_id:
            return

        fid_str = file_id_param or self.get_argument("file_id", None)
        if not fid_str or not fid_str.isdigit():
            self.set_status(400)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "BAD_REQUEST", "message": "Parameter file_id tidak valid."},
            }))
            return

        file_id = int(fid_str)
        f = db.get_file(file_id, user_id=user_id)
        if not f:
            self.set_status(404)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "NOT_FOUND", "message": "Berkas tidak ditemukan."},
            }))
            return

        try:
            import darfin_intelligence

            # 1. Base Intelligence (Task 1)
            intel = darfin_intelligence.analyze(
                filename=f.get("file_name", ""),
                mime_type=f.get("mime_type"),
                file_type=f.get("file_type"),
                file_id=f.get("id"),
            )

            # 2. Domain Classification (Task 2A)
            classification = darfin_intelligence.classify(intel)

            # 3. Smart Folder Mapping (Task 2B)
            folders = db.get_all_folders(user_id)
            suggestion = darfin_intelligence.organizer.map_folder(classification, folders)

            # 4. OCR / Screenshot / Document analysis (Tasks 3A, 3B, 3C)
            meta = f.get("metadata") if isinstance(f.get("metadata"), dict) else {}
            ocr_text = f.get("ocr_text") or meta.get("ocr_text") or ""
            ocr_conf = float(f.get("ocr_confidence") or meta.get("ocr_confidence") or 0.0)

            screenshot_info = None
            doc_info = None
            if ocr_text:
                ss_res = darfin_intelligence.analyze_screenshot(ocr_text)
                screenshot_info = ss_res.to_dict()
                doc_res = darfin_intelligence.analyze_document(ocr_text, screenshot_result=ss_res)
                doc_info = doc_res.to_dict() if hasattr(doc_res, "to_dict") else doc_res.as_dict()

            conf_val = classification.confidence
            if classification.status == "ambiguous":
                conf_label = "Perlu ditinjau"
            elif conf_val >= 0.75:
                conf_label = "Tinggi"
            elif conf_val >= 0.50:
                conf_label = "Sedang"
            else:
                conf_label = "Rendah"

            sug_payload = None
            if suggestion and suggestion.target_folder_id is not None:
                s_conf = suggestion.confidence
                if suggestion.status == "ambiguous":
                    s_label = "Perlu ditinjau"
                elif s_conf >= 0.75:
                    s_label = "Tinggi"
                elif s_conf >= 0.50:
                    s_label = "Sedang"
                else:
                    s_label = "Rendah"

                sug_payload = {
                    "status": suggestion.status,
                    "folder_id": suggestion.target_folder_id,
                    "folder_name": suggestion.target_folder_name,
                    "folder_path": suggestion.target_folder_path,
                    "confidence": round(suggestion.confidence, 2),
                    "confidence_label": s_label,
                    "reason": " • ".join(suggestion.reasons) if suggestion.reasons else "",
                    "target": {
                        "id": suggestion.target_folder_id,
                        "name": suggestion.target_folder_name,
                        "path": suggestion.target_folder_path,
                    },
                }
            elif suggestion:
                sug_payload = suggestion.to_dict()

            payload = {
                "file_id": f["id"],
                "file_name": f.get("file_name", ""),
                "file_size": f.get("file_size", 0),
                "file_size_formatted": format_size(f.get("file_size", 0)),
                "file_type": f.get("file_type", "document"),
                "created_at": f.get("created_at", ""),
                "classification": {
                    "family": intel.file_type.family if intel.file_type else f.get("file_type", "other"),
                    "domain": classification.domain,
                    "category": classification.category,
                    "confidence": round(classification.confidence, 2),
                    "confidence_label": conf_label,
                    "status": classification.status,
                    "explain": classification.explain() if callable(classification.explain) else str(classification.explain),
                },
                "suggestion": sug_payload,
                "ocr": {
                    "available": bool(ocr_text),
                    "confidence": round(ocr_conf, 2),
                    "text_preview": (
                        _mask_sensitive_text(
                            ocr_text[:300] + ("..." if len(ocr_text) > 300 else "")
                        )
                    ) if ocr_text else None,
                },
                "screenshot": screenshot_info,
                "document": doc_info,
            }

            self.write(json.dumps({
                "ok": True,
                "intelligence": payload,
            }))
        except Exception as e:
            log.exception("Error analyzing file intelligence for file %s: %s", file_id, e)
            self.set_status(500)
            self.write(json.dumps({
                "ok": False,
                "error": {"code": "SERVER_ERROR", "message": "Gagal menganalisis informasi intelligence."},
            }))


# ── Task 6A Telegram OIDC Standalone Browser Authentication Handlers ──

class OidcStartHandler(tornado.web.RequestHandler):
    """Initiate Telegram OpenID Connect login with PKCE and state protection."""

    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    async def get(self):
        client_ip = self.request.headers.get("X-Forwarded-For", self.request.remote_ip or "127.0.0.1").split(",")[0].strip()
        if not check_rate_limit(f"oidc_start:{client_ip}", max_requests=20, window_seconds=60):
            self.set_status(429)
            self.write("Terlalu banyak permintaan login. Silakan tunggu beberapa saat.")
            return

        if not config.TELEGRAM_OIDC_CLIENT_ID or not config.TELEGRAM_OIDC_CLIENT_SECRET or not config.TELEGRAM_OIDC_REDIRECT_URI:
            log.error("Telegram OIDC credentials not configured in environment")
            self.set_status(503)
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write("<h3>Login Telegram melalui browser belum dikonfigurasi pada server.</h3>")
            return

        next_path = oidc.sanitize_redirect_path(self.get_argument("next", "/"))
        verifier = oidc.generate_code_verifier()
        challenge = oidc.generate_code_challenge(verifier)
        state = oidc.generate_state()
        nonce = oidc.generate_nonce()

        cookie_val = oidc.create_state_cookie_value(state, verifier, nonce, next_path=next_path, max_age=600)
        is_secure = (self.request.protocol == "https") or ("onrender.com" in self.request.host)
        self.set_cookie(
            "tg_oidc_state",
            cookie_val,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            path="/auth/telegram",
            max_age=600,
        )

        auth_url = oidc.build_authorization_url(state=state, code_challenge=challenge, nonce=nonce)
        log.info("Redirecting browser to Telegram OIDC login (IP: %s)", client_ip)
        self.redirect(auth_url)


class OidcCallbackHandler(tornado.web.RequestHandler):
    """Handle Telegram OpenID Connect authorization callback, validate tokens, and establish session."""

    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    async def get(self):
        client_ip = self.request.headers.get("X-Forwarded-For", self.request.remote_ip or "127.0.0.1").split(",")[0].strip()
        if not check_rate_limit(f"oidc_callback:{client_ip}", max_requests=20, window_seconds=60):
            self.set_status(429)
            self.write("Terlalu banyak permintaan. Silakan coba lagi nanti.")
            return

        # Handle user cancellation / denied authorization
        error = self.get_argument("error", None)
        if error:
            log.warning("Telegram OIDC returned error: %s (%s)", error, self.get_argument("error_description", ""))
            self.clear_cookie("tg_oidc_state", path="/auth/telegram")
            self.redirect("/?auth_error=cancelled")
            return

        code = self.get_argument("code", None)
        state = self.get_argument("state", None)
        if not code or not state:
            log.warning("Telegram OIDC callback missing code or state parameter")
            self.clear_cookie("tg_oidc_state", path="/auth/telegram")
            self.redirect("/?auth_error=missing_params")
            return

        # Validate state cookie to prevent CSRF and replay attacks
        cookie_val = self.get_cookie("tg_oidc_state")
        state_data = oidc.verify_state_cookie_value(cookie_val, expected_state=state)
        # Clear single-use state cookie immediately
        self.clear_cookie("tg_oidc_state", path="/auth/telegram")

        if not state_data:
            log.warning("Telegram OIDC state verification failed (invalid, expired, or mismatched)")
            self.redirect("/?auth_error=invalid_state")
            return

        verifier = state_data["verifier"]
        nonce = state_data["nonce"]
        next_path = state_data["next_path"]

        # Exchange authorization code for tokens
        try:
            tokens = oidc.exchange_code_for_tokens(code=code, code_verifier=verifier)
        except Exception as e:
            log.error("Telegram OIDC token exchange failed: %s", e)
            self.redirect("/?auth_error=token_exchange_failed")
            return

        # Validate ID token signature and claims
        try:
            claims = oidc.validate_id_token(tokens["id_token"], expected_nonce=nonce)
            user_id = oidc.resolve_telegram_user_id(claims)
        except Exception as e:
            log.error("Telegram OIDC ID token validation failed: %s", e)
            self.redirect("/?auth_error=token_validation_failed")
            return

        # Provision / update Telegram user in database (same account model as bot/TMA)
        try:
            full_name = (claims.get("name") or "").strip()
            first_name = (claims.get("given_name") or claims.get("first_name") or "").strip()
            last_name = (claims.get("family_name") or claims.get("last_name") or "").strip()
            if not full_name and (first_name or last_name):
                full_name = f"{first_name} {last_name}".strip()

            username = claims.get("preferred_username") or claims.get("username")
            if username:
                username = str(username).lstrip("@").strip()

            # Fallback to Telegram Bot chat if name or username not in claims
            if (not full_name or not username) and user_id:
                try:
                    bot = get_shared_bot()
                    chat = await bot.get_chat(user_id)
                    if chat:
                        if not full_name:
                            b_first = (chat.first_name or "").strip()
                            b_last = (chat.last_name or "").strip()
                            if b_first or b_last:
                                full_name = f"{b_first} {b_last}".strip()
                        if not username and chat.username:
                            username = chat.username.lstrip("@").strip()
                except Exception:
                    pass

            db.upsert_user(user_id=user_id, username=username or None, full_name=full_name or None)
            db.get_or_create_inbox_folder(user_id)
        except Exception as e:
            log.error("Error syncing user record for Telegram user %s: %s", user_id, e)

        # Issue DARFIN session token and CSRF token
        session_token = auth.create_session_token(user_id=user_id, duration_seconds=86400)
        csrf_token = secrets.token_hex(16)
        is_secure = (self.request.protocol == "https") or ("onrender.com" in self.request.host)

        self.set_cookie(
            "tma_session",
            session_token,
            httponly=True,
            secure=is_secure,
            samesite="Lax",
            path="/",
            max_age=86400,
        )
        self.set_cookie(
            "tma_csrf",
            csrf_token,
            httponly=False,
            secure=is_secure,
            samesite="Lax",
            path="/",
            max_age=86400,
        )
        log.info("Telegram OIDC login successful for user %s. Redirecting to %s", user_id, next_path)
        self.redirect(next_path)


class OidcLogoutHandler(tornado.web.RequestHandler):
    """Log out authenticated browser session and clear cookies."""

    def set_default_headers(self):
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")

    async def get(self):
        self._perform_logout()

    async def post(self):
        self._perform_logout()

    def _perform_logout(self):
        self.clear_cookie("tma_session", path="/")
        self.clear_cookie("tma_csrf", path="/")
        if "application/json" in self.request.headers.get("Accept", ""):
            self.set_header("Content-Type", "application/json; charset=utf-8")
            self.write(json.dumps({"ok": True, "message": "Berhasil keluar."}))
        else:
            self.redirect("/?logged_out=1")


class ApiAuthMeHandler(BaseApiHandler):
    """Retrieve profile and authentication status of current user."""

    async def get(self):
        user = auth.get_authenticated_user(self)
        if not user or not user.get("user_id"):
            self.write(json.dumps({
                "ok": True,
                "authenticated": False,
                "user": None,
            }))
            return

        user_id = user["user_id"]
        u = db.get_user(user_id)

        display_name = ""
        username = ""

        if u:
            display_name = (u.get("full_name") or "").strip()
            username = (u.get("username") or "").strip()
            if not display_name:
                u_first = (u.get("first_name") or "").strip()
                u_last = (u.get("last_name") or "").strip()
                if u_first or u_last:
                    display_name = f"{u_first} {u_last}".strip()

        # If Mini App or session has user details, use them if display_name is missing
        if not display_name:
            first = (user.get("first_name") or "").strip()
            last = (user.get("last_name") or "").strip()
            if first or last:
                display_name = f"{first} {last}".strip()

        if not username and user.get("username"):
            username = str(user["username"]).lstrip("@").strip()

        # Query Telegram bot chat as fallback if name or username still missing
        if (not display_name or not username) and user_id:
            try:
                bot = get_shared_bot()
                if bot:
                    chat = await asyncio.wait_for(bot.get_chat(user_id), timeout=1.5)
                if chat:
                    if not display_name:
                        b_first = (getattr(chat, "first_name", None) or "").strip()
                        b_last = (getattr(chat, "last_name", None) or "").strip()
                        if b_first or b_last:
                            display_name = f"{b_first} {b_last}".strip()
                    if not username and getattr(chat, "username", None):
                        username = str(chat.username).lstrip("@").strip()
                    if display_name or username:
                        db.upsert_user(user_id=user_id, username=username or None, full_name=display_name or None)
            except Exception:
                pass

        # Fallback hierarchy per Requirement 3:
        # 1. full_name
        # 2. first_name + last_name
        # 3. username
        # 4. safe generic "Telegram User"
        if not display_name:
            display_name = username or "Telegram User"

        clean_username = username.lstrip("@").strip() if username else None
        picture = None
        if u and u.get("picture"):
            picture = u.get("picture")
        elif user.get("picture"):
            picture = user.get("picture")
        elif user.get("photo_url"):
            picture = user.get("photo_url")

        self.write(json.dumps({
            "ok": True,
            "authenticated": True,
            "user": {
                "id": user_id,
                "user_id": user_id,
                "name": display_name,
                "full_name": display_name,
                "first_name": display_name,
                "username": clean_username,
                "picture": picture,
                "auth_type": user.get("auth_type", "session"),
            },
        }))


class FaviconHandler(tornado.web.RequestHandler):
    """Serve favicon.ico with caching."""
    def get(self):
        fav_path = STATIC_DIR / "favicon.ico"
        if fav_path.is_file():
            self.set_header("Content-Type", "image/x-icon")
            self.set_header("Cache-Control", "public, max-age=86400")
            with open(fav_path, "rb") as f:
                self.write(f.read())
        else:
            self.set_status(404)


class FaviconPngHandler(tornado.web.RequestHandler):
    """Serve favicon.png with caching."""
    def get(self):
        fav_path = STATIC_DIR / "favicon.png"
        if fav_path.is_file():
            self.set_header("Content-Type", "image/png")
            self.set_header("Cache-Control", "public, max-age=86400")
            with open(fav_path, "rb") as f:
                self.write(f.read())
        else:
            self.set_status(404)


def build_app_routes(webhook_path: str = "", shared_objects: dict | None = None) -> list:
    """Consolidated single source of truth for all routes."""
    routes = []
    if webhook_path and shared_objects:
        import telegram.ext._utils.webhookhandler as wh
        routes.append((rf"{webhook_path}/?", wh.TelegramHandler, shared_objects))

    routes.extend([
        (r"/favicon\.ico", FaviconHandler),
        (r"/favicon\.png", FaviconPngHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": str(STATIC_DIR)}),
        (r"/", WebAppPageHandler),
        (r"/webapp/?", WebAppPageHandler),
        (r"/auth/telegram/start/?", OidcStartHandler),
        (r"/auth/telegram/callback/?", OidcCallbackHandler),
        (r"/auth/logout/?", OidcLogoutHandler),
        (r"/api/auth/me/?", ApiAuthMeHandler),
        (r"/api/auth/session/?", ApiAuthSessionHandler),
        (r"/api/drive/?", ApiDriveHandler),
        (r"/api/search/?", ApiSearchHandler),
        (r"/api/file_intelligence/?", ApiFileIntelligenceHandler),
        (r"/api/files/([0-9]+)/intelligence/?", ApiFileIntelligenceHandler),
        (r"/api/thumbnail/?", ApiThumbnailHandler),
        (r"/api/download/?", ApiDownloadHandler),
        (r"/api/star/?", ApiStarHandler),
        (r"/api/send_to_chat/?", ApiSendToChatHandler),
        (r"/api/all_folders/?", ApiAllFoldersHandler),
        (r"/api/batch_move/?", ApiBatchMoveHandler),
        (r"/api/create_folder/?", ApiCreateFolderHandler),
        (r"/api/rename/?", ApiRenameHandler),
        (r"/api/batch_delete/?", ApiBatchDeleteHandler),
        (r"/api/batch_star/?", ApiBatchStarHandler),
        (r"/api/batch_send_to_chat/?", ApiBatchSendToChatHandler),
        (r"/api/upload/?", ApiUploadHandler),
        (r"/api/file_content/?", ApiFileContentHandler),
        (r"/dropzone/([a-zA-Z0-9_\-]+)/?", DropzonePageHandler),
        (r"/api/dropzone/info/?", ApiDropzoneInfoHandler),
        (r"/api/dropzone/upload/?", ApiDropzoneUploadHandler),
        (r"/api/folder_dropzone/?", ApiFolderDropzoneHandler),
        (r"/s/([a-zA-Z0-9_\-]+)/?", PublicFileSharePageHandler),
        (r"/api/file_share_link/?", ApiFileShareLinkHandler),
        (r"/api/share_file_info/?", ApiShareFileInfoHandler),
        (r"/api/trash/?", ApiTrashHandler),
        (r"/api/restore/?", ApiRestoreHandler),
        (r"/api/empty_trash/?", ApiEmptyTrashHandler),
        (r"/api/duplicates/?", ApiDuplicatesHandler),
        (r"/api/clean_duplicates/?", ApiCleanDuplicatesHandler),
        (r"/api/organizer/preview/?", ApiOrganizerPreviewHandler),
        (r"/api/organizer/execute/?", ApiOrganizerExecuteHandler),
        (r"/api/preferences/feedback/?", ApiPreferencesFeedbackHandler),
        (r"/api/ping/?", ApiPingHandler),
        (r"/health/?", ApiPingHandler),
    ])
    return routes


def patch_ptb_webhook_app():
    """Patch PTB WebhookAppClass so it hosts our WebApp & APIs on the same port."""
    import telegram.ext._utils.webhookhandler as wh
    import telegram.ext._updater

    class CustomWebhookApp(wh.WebhookAppClass):
        def __init__(self, webhook_path: str, bot, update_queue, secret_token=None):
            self.shared_objects = {
                "bot": bot,
                "update_queue": update_queue,
                "secret_token": secret_token,
            }
            handlers = build_app_routes(webhook_path, self.shared_objects)
            tornado.web.Application.__init__(self, handlers)

        def log_request(self, handler):
            pass

    wh.WebhookAppClass = CustomWebhookApp
    telegram.ext._updater.WebhookAppClass = CustomWebhookApp
    log.info("Patched PTB WebhookAppClass with Darfin Storage WebApp routes")


def start_standalone_webapp_server(port: int = 10000):
    """Run standalone WebApp server for local development or polling mode."""
    routes = build_app_routes()
    app = tornado.web.Application(routes)
    try:
        app.listen(port)
        log.info("Standalone WebApp server listening on port %s", port)
    except Exception as e:
        log.warning("Could not start standalone WebApp server on port %s: %s", port, e)
