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

from config import BOT_TOKEN, PORT
import database as db
import smart_organizer
from utils import format_size, parse_file_metadata

log = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "webapp.html"


class BaseApiHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with, content-type")
        self.set_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.set_header("Content-Type", "application/json; charset=utf-8")

    def options(self):
        self.set_status(204)
        self.finish()


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
        storage_summary = {
            "total_files": info.get("total_files", 0),
            "total_folders": info.get("total_folders", 0),
            "total_size": format_size(info.get("total_size", 0)),
            "total_size_bytes": info.get("total_size", 0),
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
                "stream_url": f"/api/download?file_id={f['id']}&user_id={user_id}" if f.get("file_type") == "photo" else None,
            })

        response_data = {
            "storage": storage_summary,
            "breadcrumbs": breadcrumbs,
            "folders": folders_data,
            "files": files_data,
        }
        self.write(json.dumps(response_data))


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
            bot = Bot(BOT_TOKEN)
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

            bot = Bot(BOT_TOKEN)
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

            self.write(json.dumps({"ok": True}))
        except Exception as e:
            log.exception("Failed to send file to chat: %s", e)
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


def get_webapp_routes(webhook_path: str, shared_objects: dict) -> list[tuple]:
    """Compile all WebApp + Telegram Webhook routes."""
    import telegram.ext._utils.webhookhandler as wh
    return [
        (rf"{webhook_path}/?", wh.TelegramHandler, shared_objects),
        (r"/webapp/?", WebAppPageHandler),
        (r"/api/drive/?", ApiDriveHandler),
        (r"/api/download/?", ApiDownloadHandler),
        (r"/api/star/?", ApiStarHandler),
        (r"/api/send_to_chat/?", ApiSendToChatHandler),
        (r"/api/all_folders/?", ApiAllFoldersHandler),
        (r"/api/batch_move/?", ApiBatchMoveHandler),
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
        (r"/webapp/?", WebAppPageHandler),
        (r"/api/drive/?", ApiDriveHandler),
        (r"/api/download/?", ApiDownloadHandler),
        (r"/api/star/?", ApiStarHandler),
        (r"/api/send_to_chat/?", ApiSendToChatHandler),
        (r"/api/all_folders/?", ApiAllFoldersHandler),
        (r"/api/batch_move/?", ApiBatchMoveHandler),
    ]
    app = tornado.web.Application(routes)
    try:
        app.listen(port)
        log.info("Standalone WebApp server listening on http://0.0.0.0:%s/webapp", port)
    except Exception as e:
        log.warning("Could not start standalone WebApp server on port %s: %s", port, e)
