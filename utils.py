import hashlib
import html
import os
import re
import secrets
import unicodedata
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


def escape_html(text: str) -> str:
    """Safely escape text for Telegram HTML parse mode and HTML templates."""
    return html.escape(str(text or ""), quote=True)


def sanitize_filename(name: str, max_length: int = 255) -> str:
    """Sanitize user-provided filename against traversal, null bytes, control chars, and HTML tags."""
    if not name:
        return "file"
    # Normalize unicode
    cleaned = unicodedata.normalize("NFKC", str(name))
    # Strip directory traversal sequences
    cleaned = cleaned.replace("..", "")
    # Remove null bytes and path separators
    cleaned = cleaned.replace("\x00", "").replace("/", "_").replace("\\", "_")
    # Remove forbidden characters: < > : " | ? *
    cleaned = re.sub(r'[<>:"|?*]', "", cleaned)
    # Remove ASCII control characters (0x00 - 0x1f and 0x7f)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned).strip()
    # Strip any remaining leading/trailing underscores or dots
    cleaned = re.sub(r"^[._]+", "", cleaned)
    # Replace multiple consecutive spaces with a single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or cleaned in (".", ".."):
        return "file"
    # Ensure max length while preserving extension
    if len(cleaned) > max_length:
        parts = cleaned.rsplit(".", 1)
        if len(parts) == 2 and len(parts[1]) <= 15:
            ext = "." + parts[1]
            base = parts[0][: max_length - len(ext)]
            cleaned = base + ext
        else:
            cleaned = cleaned[:max_length]
    return cleaned.strip() or "file"


def hash_pin(pin: str, salt: str | None = None) -> str:
    """Hash PIN using PBKDF2-HMAC-SHA256 with random salt."""
    clean_pin = pin.strip()
    if not salt:
        salt = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", clean_pin.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return f"pbkdf2_sha256${salt}:{h}"


def verify_pin(pin: str, stored_val: str | None) -> bool:
    """Verify PIN with constant-time comparison. Supports hashed PIN and legacy plaintext."""
    if not stored_val or not pin:
        return False
    clean_pin = pin.strip()
    stored = str(stored_val).strip()

    if stored.startswith("pbkdf2_sha256$"):
        stored = stored[len("pbkdf2_sha256$"):]

    # Hashed format: <salt>:<pbkdf2_hex>
    if ":" in stored:
        parts = stored.split(":", 1)
        if len(parts) == 2:
            salt, expected_h = parts
            computed_h = hashlib.pbkdf2_hmac(
                "sha256", clean_pin.encode("utf-8"), salt.encode("utf-8"), 100_000
            ).hex()
            return secrets.compare_digest(computed_h.lower(), expected_h.lower())

    # Fallback to constant-time comparison against legacy plaintext PIN
    return secrets.compare_digest(clean_pin, stored)


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def extract_file_info(message: Message) -> dict | None:
    """Extract file metadata from a Telegram message, sanitizing filenames."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if message.photo:
        photo = message.photo[-1]
        return {
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "file_size": photo.file_size or 0,
            "file_type": "photo",
            "file_name": sanitize_filename(f"photo_{now}.jpg"),
            "mime_type": "image/jpeg",
            "thumbnail_file_id": message.photo[0].file_id if len(message.photo) > 1 else None,
        }

    if message.video:
        v = message.video
        raw_name = v.file_name or f"video_{now}.mp4"
        return {
            "file_id": v.file_id,
            "file_unique_id": v.file_unique_id,
            "file_size": v.file_size or 0,
            "file_type": "video",
            "file_name": sanitize_filename(raw_name),
            "mime_type": v.mime_type,
            "thumbnail_file_id": v.thumbnail.file_id if v.thumbnail else None,
        }

    if message.animation:
        a = message.animation
        raw_name = a.file_name or f"animation_{now}.gif"
        return {
            "file_id": a.file_id,
            "file_unique_id": a.file_unique_id,
            "file_size": a.file_size or 0,
            "file_type": "animation",
            "file_name": sanitize_filename(raw_name),
            "mime_type": a.mime_type,
            "thumbnail_file_id": a.thumbnail.file_id if a.thumbnail else None,
        }

    if message.document:
        d = message.document
        raw_name = d.file_name or f"document_{now}"
        ext = os.path.splitext(raw_name)[1].lower()
        mime = (d.mime_type or "").lower()
        if mime.startswith("image/") or ext in [".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff"]:
            detected_type = "photo"
        elif mime.startswith("video/") or ext in [".mp4", ".mov", ".mkv", ".webm", ".avi"]:
            detected_type = "video"
        elif mime.startswith("audio/") or ext in [".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"]:
            detected_type = "audio"
        else:
            detected_type = "document"

        return {
            "file_id": d.file_id,
            "file_unique_id": d.file_unique_id,
            "file_size": d.file_size or 0,
            "file_type": detected_type,
            "file_name": sanitize_filename(raw_name),
            "mime_type": d.mime_type,
            "thumbnail_file_id": d.thumbnail.file_id if d.thumbnail else None,
        }

    if message.audio:
        a = message.audio
        raw_name = a.file_name or a.title or f"audio_{now}.mp3"
        return {
            "file_id": a.file_id,
            "file_unique_id": a.file_unique_id,
            "file_size": a.file_size or 0,
            "file_type": "audio",
            "file_name": sanitize_filename(raw_name),
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
            "file_name": sanitize_filename(f"voice_{now}.ogg"),
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
            "file_name": sanitize_filename(f"videonote_{now}.mp4"),
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
    """Parse share_token which may contain '|exp:...|pin:...|pinhash:...|lim:...|cnt:...'"""
    if not token_str:
        return {"token": "", "expires_at": None, "pin_hash": None, "limit": None, "count": 0}

    parts = token_str.split("|")
    token = parts[0]
    res = {"token": token, "expires_at": None, "pin_hash": None, "limit": None, "count": 0}

    for p in parts[1:]:
        if p.startswith("exp:"):
            try:
                res["expires_at"] = int(p[4:])
            except ValueError:
                pass
        elif p.startswith("pinhash:"):
            res["pin_hash"] = p[8:].strip()
        elif p.startswith("pin:"):
            # Legacy plaintext format stored previously
            res["pin_hash"] = p[4:].strip()
            res["is_legacy_pin"] = True
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


def encode_share_token(
    token: str,
    expires_at: int | None = None,
    pin: str | None = None,
    limit: int | None = None,
    count: int = 0,
) -> str:
    """Encode token and security properties. PINs are automatically hashed."""
    clean_token = token.split("|")[0]
    result = clean_token
    if expires_at:
        result += f"|exp:{expires_at}"
    if pin:
        clean_pin = pin.strip()
        # If not already hashed (<salt>:<hex>), hash it now
        if ":" not in clean_pin:
            hashed = hash_pin(clean_pin)
        else:
            hashed = clean_pin
        result += f"|pinhash:{hashed}"
    if limit is not None:
        result += f"|lim:{limit}"
    if count:
        result += f"|cnt:{count}"
    return result


def optimize_preview_image(raw_bytes: bytes, max_dim: int = 1600, quality: int = 88) -> bytes:
    """Optimize image for high-speed Telegram photo preview while keeping crisp HD quality."""
    if not raw_bytes:
        return raw_bytes
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(raw_bytes)) as im:
            w, h = im.size
            if max(w, h) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()
    except Exception:
        return raw_bytes


