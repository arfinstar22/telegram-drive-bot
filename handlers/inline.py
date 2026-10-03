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
    """Handle @bot_name search queries in any chat with multi-signal search and infinite pagination."""
    inline_query = update.inline_query
    if not inline_query:
        return

    query = inline_query.query.strip()
    user_id = inline_query.from_user.id
    raw_offset = inline_query.offset or ""
    try:
        offset = int(raw_offset) if raw_offset else 0
    except ValueError:
        offset = 0

    page_size = 25
    has_more = False

    try:
        if query:
            try:
                from darfin_intelligence.search import search
                search_res = search(user_id=user_id, query=query, limit=page_size, offset=offset)
                matches = [item.file_data for item in search_res.items]
                has_more = search_res.has_more
            except Exception as e:
                log.warning("darfin_intelligence search error in inline: %s", e)
                matches = []
                has_more = False

            if not matches and offset == 0:
                all_files = db.get_all_user_files(user_id, limit=None)
                all_matches = smart_organizer.smart_search(query, all_files)
                matches = all_matches[offset : offset + page_size]
                has_more = (offset + page_size) < len(all_matches)
        else:
            all_files = db.get_all_user_files(user_id, limit=None)
            matches = all_files[offset : offset + page_size]
            has_more = (offset + page_size) < len(all_files)

        if not matches:
            if offset == 0:
                items = [
                    InlineQueryResultArticle(
                        id="no_match",
                        title=f"🔍 Tidak ditemukan: {query}" if query else "📂 Belum ada berkas",
                        description="Coba cari dengan kata kunci, nama file, tahun, atau format lain." if query else "Unggah berkas melalui bot terlebih dahulu.",
                        input_message_content=InputTextMessageContent(
                            f"🔍 Tidak ditemukan file untuk: <b>{query}</b>" if query else "📂 Belum ada file tersimpan.",
                            parse_mode="HTML",
                        ),
                    )
                ]
                await inline_query.answer(items, cache_time=2, is_personal=True, next_offset="")
            else:
                await inline_query.answer([], cache_time=2, is_personal=True, next_offset="")
            return

        items = []
        for f in matches:
            try:
                fid = str(f["id"])
                name = f.get("file_name", "File")
                size = format_size(f.get("file_size", 0))
                tg_file_id = f.get("file_id")
                if not tg_file_id:
                    continue

                folder_info = f["folders"]["name"] if f.get("folders") and isinstance(f["folders"], dict) else "Drive"

                # Check for custom note or tags
                _, note, tags = parse_file_metadata(f.get("mime_type"))
                note_str = f"\n📝 <i>{note}</i>" if note else ""
                tags_str = ("\n🏷 " + " ".join([f"#{t}" for t in tags])) if tags else ""

                caption = f"📄 <b>{name}</b> ({size})\n📁 {folder_info}{note_str}{tags_str}"

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

        next_offset = str(offset + len(matches)) if has_more and len(matches) > 0 else ""
        await inline_query.answer(items, cache_time=1, is_personal=True, next_offset=next_offset)
    except Exception as e:
        log.exception("Error in inline_query_handler: %s", e)
