"""Telegram Mini App (TMA) Web Server & API for Darfin Storage.

Serves the visual glassmorphic cloud drive interface directly inside Telegram.
Integrates with Tornado and Python-Telegram-Bot webhook server without extra dependencies.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import tornado.web
import tornado.httputil
from telegram import Bot

from config import BOT_TOKEN, PORT, WEBHOOK_URL
import database as db
import smart_organizer
from utils import format_size, parse_file_metadata

log = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "webapp.html"
DROPZONE_TEMPLATE_PATH = Path(__file__).parent / "templates" / "dropzone.html"
SHARE_FILE_TEMPLATE_PATH = Path(__file__).parent / "templates" / "share_file.html"


class BaseApiHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header("Content-Type", "application/json; charset=utf-8")

    def options(self):
        self.set_status(204)
        self.finish()


class ApiPingHandler(BaseApiHandler):
    """Health check / ping endpoint for keep-alive worker and WebApp cold-start detection."""
    def get(self):
        self.write({"ok": True, "status": "awake", "service": "telegram-drive-bot"})

    def head(self):
        self.set_status(200)


class WebAppPageHandler(tornado.web.RequestHandler):
    def get(self):
        try:
            if TEMPLATE_PATH.exists():
                html = TEMPLATE_PATH.read_text(encoding="utf-8")
            else:
                html = "<h1>Darfin Storage WebApp Template Not Found</h1>"
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        except Exception as e:
            self.set_status(500)
            self.write(f"Error loading WebApp: {e}")

    def head(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        self.set_status(200)


class DropzonePageHandler(tornado.web.RequestHandler):
    """Serve the public Dropzone upload webpage."""
    def get(self, token: str):
        try:
            if DROPZONE_TEMPLATE_PATH.exists():
                html = DROPZONE_TEMPLATE_PATH.read_text(encoding="utf-8")
            else:
                html = "<h1>Dropzone Template Not Found</h1>"
            self.set_header("Content-Type", "text/html; charset=utf-8")
            self.write(html)
        except Exception as e:
            self.set_status(500)
            self.write(f"Error loading Dropzone: {e}")


class PublicFileSharePageHandler(tornado.web.RequestHandler):
    """Serve the public file view/download page without Telegram bot or auth."""
    async def get(self, token: str):
        try:
            is_download = self.get_argument("download", "0") in ("1", "true")
            f = db.get_file_by_share_token(token)
            if not f or f.get("is_trashed"):
                self.set_status(404)
                self.set_header("Content-Type", "text/html; charset=utf-8")
                self.write("""
                <!DOCTYPE html>
                <html lang="id">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Berkas Tidak Ditemukan - Darfin Storage</title>
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
                </html>
                """)
                return

            if is_download:
                try:
                    bot = get_shared_bot()
                    tg_file = await bot.get_file(f["file_id"])
                    if tg_file and tg_file.file_path:
                        self.redirect(tg_file.file_path)
                        return
                except Exception as ex:
                    log.warning("Could not fetch direct CDN for share download: %s", ex)

                bot_me = await get_shared_bot().get_me()
                self.redirect(f"https://t.me/{bot_me.username}?start=sf_{token}")
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
            self.write(f"Error loading shared file: {e}")


class ApiDriveHandler(BaseApiHandler):
    async def get(self):
        user_id_raw = self.get_argument("user_id", None)
        if not user_id_raw or not user_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid or missing user_id"}))
            return

        user_id = int(user_id_raw)
        folder_id_raw = self.get_argument("folder_id", None)
        folder_id = int(folder_id_raw) if folder_id_raw and folder_id_raw.isdigit() else None

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
            raw_path = db.get_folder_path(folder_id)
            breadcrumbs = [{"id": f["id"], "name": f["name"]} for f in raw_path]

        # Folders
        folders = db.get_folders(user_id, parent_id=folder_id)
        folders_data = []
        for f in folders:
            # Count files in this subfolder
            cnt = db.get_file_count(f["id"])
            folders_data.append({
                "id": f["id"],
                "name": f["name"],
                "is_starred": bool(f.get("is_starred", False)),
                "file_count": cnt,
            })

        # Files
        if folder_id:
            files_raw = db.get_all_files_in_folder(folder_id)
        else:
            files_raw = db.get_all_user_files(user_id, limit=60)

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
                "thumb_url": f"/api/thumbnail?file_id={f['id']}" if has_thumb else None,
                "stream_url": f"/api/download?file_id={f['id']}&user_id={user_id}" if f.get("file_type") == "photo" else None,
            })

        response_data = {
            "storage": storage_summary,
            "breadcrumbs": breadcrumbs,
            "folders": folders_data,
            "files": files_data,
        }
        self.write(json.dumps(response_data))


# In-memory LRU cache for thumbnail binary (capped to 300 items ~3MB RAM max)
_THUMB_CACHE: dict[int, bytes] = {}
_MAX_THUMB_CACHE = 300
_shared_bot_instance: Optional[Bot] = None


def get_shared_bot() -> Bot:
    """Reuse singleton Bot instance to avoid re-initializing connection pools."""
    global _shared_bot_instance
    if _shared_bot_instance is None:
        _shared_bot_instance = Bot(BOT_TOKEN)
    return _shared_bot_instance


class ApiThumbnailHandler(tornado.web.RequestHandler):
    """Serve thumbnail image for video, photo, or document files with in-memory caching."""
    async def get(self):
        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write("Invalid file_id")
            return

        file_id = int(file_id_raw)

        # 1. Instant hit from server RAM cache (<1ms response time)
        if file_id in _THUMB_CACHE:
            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Cache-Control", "public, max-age=604800, immutable")
            self.write(_THUMB_CACHE[file_id])
            return

        f = db.get_file(file_id)
        if not f:
            self.set_status(404)
            self.write("File not found")
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

            # Store in RAM cache (FIFO / LRU eviction when limit reached)
            _THUMB_CACHE[file_id] = resp.body
            if len(_THUMB_CACHE) > _MAX_THUMB_CACHE:
                _THUMB_CACHE.pop(next(iter(_THUMB_CACHE)))

            self.set_header("Content-Type", "image/jpeg")
            self.set_header("Cache-Control", "public, max-age=604800, immutable")
            self.write(resp.body)
        except Exception as e:
            log.warning("Could not fetch thumbnail for file %s: %s", f["id"], e)
            self.set_status(404)


class ApiDownloadHandler(tornado.web.RequestHandler):
    """Directly stream or redirect to Telegram CDN for file viewing/playing."""
    async def get(self):
        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write("Invalid file_id")
            return

        file_id = int(file_id_raw)
        f = db.get_file(file_id)
        if not f:
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
            log.warning("Could not fetch direct Telegram CDN url for file %s: %s", file_id, e)

        # Fallback to direct bot message link
        bot_url = f"https://t.me/darfinstoragebot?start=sf_{f.get('share_token') or f['id']}"
        self.redirect(bot_url)


class ApiStarHandler(BaseApiHandler):
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id = data.get("file_id")
            folder_id = data.get("folder_id")
            if file_id:
                db.toggle_star_file(file_id)
            elif folder_id:
                db.toggle_star_folder(folder_id)
            self.write(json.dumps({"ok": True}))
        except Exception as e:
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


async def _send_single_file_to_chat(bot: Bot, user_id: int, f: dict):
    """Sends a single media or document file with actions markup to Telegram chat."""
    import keyboards as kb
    from utils import file_emoji, format_size, parse_file_metadata
    emoji = file_emoji(f["file_type"])
    size = format_size(f.get("file_size", 0))
    created = f.get("created_at", "")[:10]
    _, note, tags = parse_file_metadata(f.get("mime_type"))
    note_line = f"\n📝 <i>{note}</i>" if note else ""
    tags_line = f"\n🏷 " + " ".join(f"#{t}" for t in tags) if tags else ""
    caption = f"{emoji} <b>{f['file_name']}</b>\n📊 {size} • 📅 {created}{note_line}{tags_line}"
    markup = kb.file_actions(f)

    ftype = f.get("file_type", "document")
    fid = f["file_id"]

    if ftype == "photo":
        await bot.send_photo(chat_id=user_id, photo=fid, caption=caption, parse_mode="HTML", reply_markup=markup)
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
    """Sends file directly into user's Telegram chat with full interactive buttons."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id = data.get("file_id")
            user_id = data.get("user_id")
            if not file_id or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing file_id or user_id"}))
                return

            f = db.get_file(file_id)
            if not f:
                self.set_status(404)
                self.write(json.dumps({"error": "File not found"}))
                return

            bot = get_shared_bot()
            await _send_single_file_to_chat(bot, int(user_id), f)
            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Failed to send file to chat: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiBatchSendToChatHandler(BaseApiHandler):
    """Batch sends multiple files into user's Telegram chat."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            user_id = data.get("user_id")
            if not file_ids or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing file_ids or user_id"}))
                return

            bot = get_shared_bot()
            sent = 0
            for fid in file_ids:
                try:
                    f = db.get_file(int(fid))
                    if not f:
                        continue
                    await _send_single_file_to_chat(bot, int(user_id), f)
                    sent += 1
                    await asyncio.sleep(0.3)
                except Exception as ex:
                    log.warning("Failed sending batch file %s to chat: %s", fid, ex)

            self.write(json.dumps({"ok": True, "sent_count": sent}))
        except Exception as e:
            log.exception("Error batch sending files to chat: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiAllFoldersHandler(BaseApiHandler):
    """Returns list of all user folders for destination selection."""
    async def get(self):
        user_id_raw = self.get_argument("user_id", None)
        if not user_id_raw or not user_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid user_id"}))
            return

        user_id = int(user_id_raw)
        folders = db.get_all_folders(user_id)
        data = []
        for f in folders:
            cnt = db.get_file_count(f["id"])
            data.append({
                "id": f["id"],
                "name": f["name"],
                "parent_id": f.get("parent_id"),
                "file_count": cnt,
            })
        self.write(json.dumps({"folders": data}))


class ApiBatchMoveHandler(BaseApiHandler):
    """Batch moves multiple files to target folder."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            target_folder_id = data.get("target_folder_id")
            user_id = data.get("user_id")

            if not file_ids or target_folder_id is None or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing parameters"}))
                return

            target_folder_id = int(target_folder_id)
            if target_folder_id == 0:
                inbox = db.get_or_create_inbox_folder(int(user_id))
                target_folder_id = inbox["id"]
                folder_name = inbox["name"]
            else:
                tf = db.get_folder(target_folder_id)
                if not tf:
                    self.set_status(404)
                    self.write(json.dumps({"error": "Folder tujuan tidak ditemukan"}))
                    return
                folder_name = tf["name"]

            moved = 0
            for fid in file_ids:
                try:
                    db.move_file(int(fid), target_folder_id)
                    moved += 1
                except Exception as ex:
                    log.warning("Failed moving file %s: %s", fid, ex)

            self.write(json.dumps({"ok": True, "count": moved, "folder_name": folder_name}))
        except Exception as e:
            log.exception("Error batch moving files: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiCreateFolderHandler(BaseApiHandler):
    """Create new folder in drive."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            name = (data.get("name") or "").strip()
            parent_id = data.get("parent_id")
            user_id = data.get("user_id")
            if not name or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Nama folder dan user_id wajib diisi"}))
                return

            folder = db.get_or_create_folder(int(user_id), name, int(parent_id) if parent_id else None)
            self.write(json.dumps({"ok": True, "folder": folder}))
        except Exception as e:
            log.exception("Error create folder: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiRenameHandler(BaseApiHandler):
    """Rename file or folder."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            item_type = data.get("type", "file")
            item_id = data.get("id")
            new_name = (data.get("new_name") or "").strip()
            user_id = data.get("user_id")

            if not item_id or not new_name or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing parameters"}))
                return

            if item_type == "folder":
                db.rename_folder(int(item_id), new_name)
            else:
                db.rename_file(int(item_id), new_name)

            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Error rename: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiBatchDeleteHandler(BaseApiHandler):
    """Trash/delete files and folders."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            folder_ids = data.get("folder_ids", [])
            user_id = data.get("user_id")

            del_files = 0
            for fid in file_ids:
                try:
                    db.trash_file(int(fid))
                    del_files += 1
                except Exception as ex:
                    log.warning("Failed trashing file %s: %s", fid, ex)

            del_folders = 0
            for fld_id in folder_ids:
                try:
                    db.delete_folder(int(fld_id))
                    del_folders += 1
                except Exception as ex:
                    log.warning("Failed deleting folder %s: %s", fld_id, ex)

            self.write(json.dumps({"ok": True, "deleted_files": del_files, "deleted_folders": del_folders}))
        except Exception as e:
            log.exception("Error batch delete: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiBatchStarHandler(BaseApiHandler):
    """Batch star/unstar files."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            is_starred = bool(data.get("is_starred", True))

            for fid in file_ids:
                try:
                    db.db.table("files").update({"is_starred": is_starred, "updated_at": db._now()}).eq("id", int(fid)).execute()
                except Exception as ex:
                    log.warning("Failed starring file %s: %s", fid, ex)

            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Error batch star: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiUploadHandler(BaseApiHandler):
    """Direct file upload from WebApp."""
    async def post(self):
        try:
            user_id_raw = self.get_argument("user_id", None)
            folder_id_raw = self.get_argument("folder_id", None)
            if not user_id_raw or not user_id_raw.isdigit():
                self.set_status(400)
                self.write(json.dumps({"error": "Invalid user_id"}))
                return

            user_id = int(user_id_raw)
            if folder_id_raw and folder_id_raw.isdigit() and int(folder_id_raw) > 0:
                folder_id = int(folder_id_raw)
            else:
                inbox = db.get_or_create_inbox_folder(user_id)
                folder_id = inbox["id"]

            uploaded_files = self.request.files.get("files", [])
            if not uploaded_files:
                self.set_status(400)
                self.write(json.dumps({"error": "Tidak ada file yang diunggah"}))
                return

            bot = get_shared_bot()
            f_obj = db.get_folder(folder_id)
            folder_name = f_obj["name"] if f_obj else "Folder"

            saved_count = 0
            for fileinfo in uploaded_files:
                filename = fileinfo["filename"]
                body = fileinfo["body"]
                content_type = fileinfo.get("content_type", "application/octet-stream")
                size = len(body)

                lower_name = filename.lower()
                thumb_fid = None
                if any(lower_name.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                    ftype = "photo"
                    msg = await bot.send_photo(chat_id=user_id, photo=body, caption=f"📤 Diunggah via WebApp ke 📁 {folder_name}")
                    fid = msg.photo[-1].file_id
                    fuid = msg.photo[-1].file_unique_id
                    thumb_fid = msg.photo[0].file_id if len(msg.photo) > 1 else None
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

                db.save_file(
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
                saved_count += 1

            self.write(json.dumps({"ok": True, "count": saved_count}))
        except Exception as e:
            log.exception("Error in ApiUploadHandler: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiFileContentHandler(BaseApiHandler):
    """Fetches text content for text/code preview."""
    async def get(self):
        file_id_raw = self.get_argument("file_id", None)
        if not file_id_raw or not file_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid file_id"}))
            return

        f = db.get_file(int(file_id_raw))
        if not f:
            self.set_status(404)
            self.write(json.dumps({"error": "File not found"}))
            return

        if f.get("file_size", 0) > 2 * 1024 * 1024:
            self.set_status(400)
            self.write(json.dumps({"error": "File terlalu besar untuk preview teks (> 2MB)"}))
            return

        try:
            bot = get_shared_bot()
            tg_file = await bot.get_file(f["file_id"])
            if not tg_file or not tg_file.file_path:
                self.set_status(500)
                self.write(json.dumps({"error": "Could not get file path"}))
                return

            import urllib.request
            req = urllib.request.Request(tg_file.file_path, headers={"User-Agent": "DarfinStorage"})
            with urllib.request.urlopen(req) as response:
                content = response.read().decode("utf-8", errors="replace")

            self.write(json.dumps({"ok": True, "content": content[:80000]}))
        except Exception as e:
            log.exception("Error fetching file content: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiDropzoneInfoHandler(BaseApiHandler):
    """Fetch folder details by dropzone share token."""
    async def get(self):
        token = self.get_argument("token", None)
        if not token:
            self.set_status(400)
            self.write(json.dumps({"error": "Missing token"}))
            return

        folder = db.get_folder_by_share_token(token)
        if not folder:
            self.set_status(404)
            self.write(json.dumps({"error": "Link Dropzone tidak valid atau telah dinonaktifkan."}))
            return

        user = db.get_user(folder["user_id"])
        owner_name = user.get("first_name", "Darfin Storage") if user else "Darfin Storage"

        self.write(json.dumps({
            "ok": True,
            "folder": {
                "id": folder["id"],
                "name": folder["name"],
                "owner_name": owner_name,
            }
        }))


class ApiDropzoneUploadHandler(BaseApiHandler):
    """Direct multi-file upload from public Dropzone page."""
    async def post(self):
        try:
            token = self.get_argument("token", None)
            sender_name = (self.get_argument("sender_name", "") or "").strip() or "Tamu Dropzone"

            if not token:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing token"}))
                return

            folder = db.get_folder_by_share_token(token)
            if not folder:
                self.set_status(404)
                self.write(json.dumps({"error": "Folder Dropzone tidak ditemukan"}))
                return

            user_id = folder["user_id"]
            folder_id = folder["id"]
            folder_name = folder["name"]

            uploaded_files = self.request.files.get("files", [])
            if not uploaded_files:
                self.set_status(400)
                self.write(json.dumps({"error": "Tidak ada berkas yang diunggah"}))
                return

            bot = get_shared_bot()
            saved_count = 0
            total_bytes = 0
            file_names_summary = []

            for file_info in uploaded_files:
                filename = file_info["filename"]
                body = file_info["body"]
                size = len(body)
                total_bytes += size
                file_names_summary.append(filename)

                lower_name = filename.lower()
                thumb_fid = None
                caption_note = f"📥 Masuk via Dropzone oleh: {sender_name} ke 📁 {folder_name}"

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

            # Send summary notification to owner
            try:
                from utils import format_size
                summary_text = (
                    f"📥 <b>Dropzone: Berkas Baru Diterima!</b>\n\n"
                    f"📁 <b>Folder:</b> {folder_name}\n"
                    f"👤 <b>Pengirim:</b> {sender_name}\n"
                    f"📦 <b>Jumlah:</b> {saved_count} berkas ({format_size(total_bytes)})\n"
                    f"📄 <b>Daftar:</b>\n" + "\n".join(f"• {fn}" for fn in file_names_summary[:5])
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
            self.write(json.dumps({"error": str(e)}))


class ApiFolderDropzoneHandler(BaseApiHandler):
    """Manage folder Dropzone link (create/get/revoke)."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            folder_id = data.get("folder_id")
            user_id = data.get("user_id")
            action = data.get("action", "get")

            if not folder_id or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing parameters"}))
                return

            folder = db.get_folder(int(folder_id))
            if not folder or folder["user_id"] != int(user_id):
                self.set_status(403)
                self.write(json.dumps({"error": "Folder tidak ditemukan atau akses ditolak"}))
                return

            if action == "revoke":
                db.revoke_folder_share_token(int(folder_id))
                self.write(json.dumps({"ok": True, "active": False}))
                return

            token = db.get_or_create_folder_share_token(int(folder_id))
            base_url = WEBHOOK_URL.rstrip('/') if WEBHOOK_URL else "https://telegram-drive-bot-0upd.onrender.com"
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
            self.write(json.dumps({"error": str(e)}))


class ApiFileShareLinkHandler(BaseApiHandler):
    """Manage file public share link (get/create/revoke)."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_id = data.get("file_id")
            user_id = data.get("user_id")
            action = data.get("action", "get")

            if not file_id or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing file_id or user_id"}))
                return

            f = db.get_file(int(file_id))
            if not f or int(f.get("user_id", 0)) != int(user_id):
                self.set_status(403)
                self.write(json.dumps({"error": "Berkas tidak ditemukan atau akses ditolak"}))
                return

            if action == "revoke":
                db.revoke_file_share_token(int(file_id))
                self.write(json.dumps({"ok": True, "active": False}))
                return

            token = db.get_or_create_file_share_token(int(file_id))
            base_url = f"{self.request.protocol}://{self.request.host}" if self.request.host else (WEBHOOK_URL.rstrip('/') if WEBHOOK_URL else "https://telegram-drive-bot-0upd.onrender.com")
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
            self.write(json.dumps({"error": str(e)}))


class ApiShareFileInfoHandler(BaseApiHandler):
    """Fetch public file metadata by share token."""
    async def get(self):
        token = self.get_argument("token", None)
        if not token:
            self.set_status(400)
            self.write(json.dumps({"error": "Missing token"}))
            return

        f = db.get_file_by_share_token(token)
        if not f or f.get("is_trashed"):
            self.set_status(404)
            self.write(json.dumps({"error": "Berkas tidak ditemukan atau telah dihapus."}))
            return

        preview_url = None
        bot = get_shared_bot()
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
            "file": {
                "name": f["file_name"],
                "size_formatted": format_size(f.get("file_size", 0)),
                "size_bytes": f.get("file_size", 0),
                "type": f.get("file_type", "document"),
                "mime_type": f.get("mime_type", ""),
                "created_at": f.get("created_at", "")[:10],
                "preview_url": preview_url,
                "download_url": f"/s/{token}?download=1",
                "bot_url": f"https://t.me/{bot_username}?start=sf_{token}"
            }
        }))


class ApiTrashHandler(BaseApiHandler):
    """List all trashed files for a user."""
    async def get(self):
        user_id_raw = self.get_argument("user_id", None)
        if not user_id_raw or not user_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid user_id"}))
            return

        user_id = int(user_id_raw)
        trash_files = db.get_trash(user_id)
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
                "thumb_url": f"/api/thumbnail?file_id={f['id']}" if has_thumb else None,
            })
        self.write(json.dumps({"ok": True, "files": res_files, "count": len(res_files)}))


class ApiRestoreHandler(BaseApiHandler):
    """Restore trashed file(s)."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            file_ids = data.get("file_ids", [])
            user_id = data.get("user_id")

            if not file_ids or not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing parameters"}))
                return

            restored = 0
            for fid in file_ids:
                try:
                    db.restore_file(int(fid))
                    restored += 1
                except Exception as ex:
                    log.warning("Failed restoring file %s: %s", fid, ex)

            self.write(json.dumps({"ok": True, "restored_count": restored}))
        except Exception as e:
            log.exception("Error restoring file: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiEmptyTrashHandler(BaseApiHandler):
    """Permanently delete all trashed files of user."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            user_id = data.get("user_id")
            if not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing user_id"}))
                return

            db.empty_trash(int(user_id))
            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Error emptying trash: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


class ApiDuplicatesHandler(BaseApiHandler):
    """Get duplicate files report and potential space savings."""
    async def get(self):
        user_id_raw = self.get_argument("user_id", None)
        if not user_id_raw or not user_id_raw.isdigit():
            self.set_status(400)
            self.write(json.dumps({"error": "Invalid user_id"}))
            return

        user_id = int(user_id_raw)
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
    """One-click cleanup redundant duplicate copies to trash."""
    async def post(self):
        try:
            data = json.loads(self.request.body.decode("utf-8"))
            user_id = data.get("user_id")
            if not user_id:
                self.set_status(400)
                self.write(json.dumps({"error": "Missing user_id"}))
                return

            cleaned = db.clean_duplicate_files(int(user_id))
            self.write(json.dumps({"ok": True, "cleaned_count": cleaned}))
        except Exception as e:
            log.exception("Error cleaning duplicates: %s", e)
            self.set_status(500)
            self.write(json.dumps({"error": str(e)}))


def get_webapp_routes(webhook_path: str, shared_objects: dict) -> list[tuple]:
    """Compile all WebApp + Telegram Webhook routes."""
    import telegram.ext._utils.webhookhandler as wh
    return [
        (rf"{webhook_path}/?", wh.TelegramHandler, shared_objects),
        (r"/", WebAppPageHandler),
        (r"/webapp/?", WebAppPageHandler),
        (r"/api/drive/?", ApiDriveHandler),
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
        (r"/api/ping/?", ApiPingHandler),
        (r"/health/?", ApiPingHandler),
    ]


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
            handlers = get_webapp_routes(webhook_path, self.shared_objects)
            tornado.web.Application.__init__(self, handlers)

        def log_request(self, handler):
            pass

    wh.WebhookAppClass = CustomWebhookApp
    telegram.ext._updater.WebhookAppClass = CustomWebhookApp
    log.info("Patched PTB WebhookAppClass with Darfin Storage WebApp routes (/webapp, /api/*)")


def start_standalone_webapp_server(port: int = 10000):
    """Run standalone WebApp server for local development or polling mode."""
    routes = [
        (r"/", WebAppPageHandler),
        (r"/webapp/?", WebAppPageHandler),
        (r"/api/drive/?", ApiDriveHandler),
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
        (r"/api/ping/?", ApiPingHandler),
        (r"/health/?", ApiPingHandler),
    ]
    app = tornado.web.Application(routes)
    try:
        app.listen(port)
        log.info("Standalone WebApp server listening on http://0.0.0.0:%s/webapp", port)
    except Exception as e:
        log.warning("Could not start standalone WebApp server on port %s: %s", port, e)
