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
