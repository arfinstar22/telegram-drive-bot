from datetime import datetime, timezone
from telegram import Message


FILE_TYPE_EMOJI = {
    "photo": "🖼",
    "video": "🎬",
    "document": "📄",
    "audio": "🎵",
    "voice": "🎤",
    "animation": "🎞",
    "video_note": "⏺",
}


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def extract_file_info(message: Message) -> dict | None:
    """Extract file metadata from a Telegram message."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if message.photo:
        photo = message.photo[-1]
        return {
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_size": photo.file_size or 0,
            "file_type": "photo",
            "file_name": f"photo_{now}.jpg",
            "mime_type": "image/jpeg",
            "thumbnail_file_id": message.photo[0].file_id if len(message.photo) > 1 else None,
        }

    if message.video:
        v = message.video
        return {
            "file_id": v.file_id,
            "file_unique_id": v.file_unique_id,
            "file_size": v.file_size or 0,
            "file_type": "video",
            "file_name": v.file_name or f"video_{now}.mp4",
            "mime_type": v.mime_type,
            "thumbnail_file_id": v.thumbnail.file_id if v.thumbnail else None,
        }

    if message.animation:
        a = message.animation
        return {
            "file_id": a.file_id,
            "file_unique_id": a.file_unique_id,
            "file_size": a.file_size or 0,
            "file_type": "animation",
            "file_name": a.file_name or f"animation_{now}.gif",
            "mime_type": a.mime_type,
            "thumbnail_file_id": a.thumbnail.file_id if a.thumbnail else None,
        }

    if message.document:
        d = message.document
        return {
            "file_id": d.file_id,
            "file_unique_id": d.file_unique_id,
            "file_size": d.file_size or 0,
            "file_type": "document",
            "file_name": d.file_name or f"document_{now}",
            "mime_type": d.mime_type,
            "thumbnail_file_id": d.thumbnail.file_id if d.thumbnail else None,
        }

    if message.audio:
        a = message.audio
        return {
            "file_id": a.file_id,
            "file_unique_id": a.file_unique_id,
            "file_size": a.file_size or 0,
            "file_type": "audio",
            "file_name": a.file_name or a.title or f"audio_{now}.mp3",
            "mime_type": a.mime_type,
            "thumbnail_file_id": a.thumbnail.file_id if a.thumbnail else None,
        }

    if message.voice:
        v = message.voice
        return {
            "file_id": v.file_id,
            "file_unique_id": v.file_unique_id,
            "file_size": v.file_size or 0,
            "file_type": "voice",
            "file_name": f"voice_{now}.ogg",
            "mime_type": v.mime_type or "audio/ogg",
            "thumbnail_file_id": None,
        }

    if message.video_note:
        v = message.video_note
        return {
            "file_id": v.file_id,
            "file_unique_id": v.file_unique_id,
            "file_size": v.file_size or 0,
            "file_type": "video_note",
            "file_name": f"videonote_{now}.mp4",
            "mime_type": "video/mp4",
            "thumbnail_file_id": v.thumbnail.file_id if v.thumbnail else None,
        }

    return None


def file_emoji(file_type: str) -> str:
    return FILE_TYPE_EMOJI.get(file_type, "📎")


def truncate(text: str, length: int = 25) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def get_user_lang(context=None, user_id: int | None = None) -> str:
    """Get preferred language ('id' or 'en') for user, caching in user_data."""
    if context and hasattr(context, "user_data") and "language" in context.user_data:
        return context.user_data["language"]
    if user_id:
        import database as db
        u = db.get_user(user_id)
        if u and u.get("language"):
            lang = u["language"]
            if context and hasattr(context, "user_data"):
                context.user_data["language"] = lang
            return lang
    return "id"


def parse_file_metadata(mime_type: str | None) -> tuple[str, str | None, list[str]]:
    """Parse mime_type string which can contain '|NOTE:...|TAGS:...' suffix."""
    if not mime_type:
        return "application/octet-stream", None, []

    parts = mime_type.split("|")
    clean_mime = parts[0]
    note = None
    tags = []

    for p in parts[1:]:
        if p.startswith("NOTE:"):
            note = p[5:].strip()
        elif p.startswith("TAGS:"):
            tag_str = p[5:].strip()
            tags = [t.strip().lstrip("#").lower() for t in tag_str.split(",") if t.strip()]

    return clean_mime, note, tags


def encode_file_metadata(clean_mime: str, note: str | None = None, tags: list[str] | None = None) -> str:
    """Encode clean_mime, note, and tags into a single string for storage."""
    result = clean_mime.split("|")[0] if clean_mime else "application/octet-stream"
    if note:
        safe_note = note.replace("|", " ").strip()
        result += f"|NOTE:{safe_note}"
    if tags:
        safe_tags = ",".join([t.strip().lstrip("#").lower() for t in tags if t.strip()])
        if safe_tags:
            result += f"|TAGS:{safe_tags}"
    return result


def parse_share_token(token_str: str | None) -> dict:
    """Parse share_token which may contain '|exp:...|pin:...|lim:...|cnt:...'"""
    if not token_str:
        return {"token": "", "expires_at": None, "pin": None, "limit": None, "count": 0}

    parts = token_str.split("|")
    token = parts[0]
    res = {"token": token, "expires_at": None, "pin": None, "limit": None, "count": 0}

    for p in parts[1:]:
        if p.startswith("exp:"):
            try:
                res["expires_at"] = int(p[4:])
            except ValueError:
                pass
        elif p.startswith("pin:"):
            res["pin"] = p[4:].strip()
        elif p.startswith("lim:"):
            try:
                res["limit"] = int(p[4:])
            except ValueError:
                pass
        elif p.startswith("cnt:"):
            try:
                res["count"] = int(p[4:])
            except ValueError:
                pass
    return res


def encode_share_token(token: str, expires_at: int | None = None, pin: str | None = None, limit: int | None = None, count: int = 0) -> str:
    """Encode token and security properties into a share_token string."""
    clean_token = token.split("|")[0]
    result = clean_token
    if expires_at:
        result += f"|exp:{expires_at}"
    if pin:
        result += f"|pin:{pin.strip()}"
    if limit is not None:
        result += f"|lim:{limit}"
    if count:
        result += f"|cnt:{count}"
    return result


