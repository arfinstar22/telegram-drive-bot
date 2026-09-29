"""Inline query handler: search and send files from any chat."""

import logging
from telegram import (
    Update,
    InlineQueryResultCachedDocument,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedVoice,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import ContextTypes

import database as db
import smart_organizer
from utils import format_size, parse_file_metadata

log = logging.getLogger(__name__)


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle @bot_name search queries in any chat."""
    inline_query = update.inline_query
    if not inline_query:
        return

    query = inline_query.query.strip()
    user_id = inline_query.from_user.id

    try:
        # Fetch user's non-trashed files
        all_files = db.get_all_user_files(user_id, limit=60)
        if not all_files:
            items = [
                InlineQueryResultArticle(
                    id="no_files",
                    title="📁 Belum Ada File",
                    description="Buka bot untuk mulai upload file ke Telegram Drive Anda.",
                    input_message_content=InputTextMessageContent(
                        "🗂 <b>Telegram Drive</b>\nBelum ada file di penyimpanan saya.",
                        parse_mode="HTML",
                    ),
                )
            ]
            await inline_query.answer(items, cache_time=2, is_personal=True)
            return

        if query:
            matches = smart_organizer.smart_search(query, all_files)
        else:
            matches = all_files[:25]

        if not matches:
            items = [
                InlineQueryResultArticle(
                    id="no_match",
                    title=f"🔍 Tidak ditemukan: {query}",
                    description="Coba cari dengan kata kunci, nama file, tahun, atau format lain.",
                    input_message_content=InputTextMessageContent(
                        f"🔍 Tidak ditemukan file untuk: <b>{query}</b>",
                        parse_mode="HTML",
                    ),
                )
            ]
            await inline_query.answer(items, cache_time=2, is_personal=True)
            return

        items = []
        for f in matches[:25]:
            try:
                fid = str(f["id"])
                name = f.get("file_name", "File")
                size = format_size(f.get("file_size", 0))
                ftype = f.get("file_type", "document")
                tg_file_id = f.get("file_id")
                if not tg_file_id:
                    continue

                folder_info = f["folders"]["name"] if f.get("folders") and isinstance(f["folders"], dict) else "Drive"

                # Check for custom note or tags
                _, note, tags = parse_file_metadata(f.get("mime_type"))
                note_str = f"\n📝 <i>{note}</i>" if note else ""
                tags_str = ("\n🏷 " + " ".join([f"#{t}" for t in tags])) if tags else ""

                caption = f"📄 <b>{name}</b> ({size})\n📁 {folder_info}{note_str}{tags_str}"

                if ftype == "photo":
                    items.append(InlineQueryResultCachedPhoto(
                        id=fid,
                        photo_file_id=tg_file_id,
                        title=name,
                        caption=caption,
                        parse_mode="HTML",
                    ))
                elif ftype == "video":
                    items.append(InlineQueryResultCachedVideo(
                        id=fid,
                        video_file_id=tg_file_id,
                        title=name,
                        description=f"{size} • {folder_info}",
                        caption=caption,
                        parse_mode="HTML",
                    ))
                elif ftype == "audio":
                    items.append(InlineQueryResultCachedAudio(
                        id=fid,
                        audio_file_id=tg_file_id,
                        caption=caption,
                        parse_mode="HTML",
                    ))
                elif ftype == "voice":
                    items.append(InlineQueryResultCachedVoice(
                        id=fid,
                        voice_file_id=tg_file_id,
                        title=name,
                        caption=caption,
                        parse_mode="HTML",
                    ))
                else:
                    items.append(InlineQueryResultCachedDocument(
                        id=fid,
                        title=name,
                        document_file_id=tg_file_id,
                        description=f"{size} • {folder_info}",
                        caption=caption,
                        parse_mode="HTML",
                    ))
            except Exception as item_err:
                log.warning("Skipping inline file item %s: %s", f.get("id"), item_err)

        await inline_query.answer(items, cache_time=2, is_personal=True)
    except Exception as e:
        log.exception("Error in inline_query_handler: %s", e)
