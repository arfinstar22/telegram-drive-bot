"""File upload, preview, download, rename, move, delete, search."""

import asyncio
import base64
import io
import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import ai_service
import database as db
import keyboards as kb
from utils import extract_file_info, file_emoji, format_size

log = logging.getLogger(__name__)


# ── Upload flow ────────────────────────────────────────

async def upload_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: 📤 Upload — show folder picker."""
    context.user_data["state"] = "idle"
    user_id = update.effective_user.id
    folders = db.get_all_folders(user_id)

    if not folders:
        await update.message.reply_text(
            "📁 Belum ada folder.\nBuat folder dulu lewat <b>My Files</b>.",
            parse_mode="HTML", reply_markup=kb.main_menu(),
        )
        return

    await update.message.reply_text(
        "📤 Pilih folder tujuan upload:",
        reply_markup=kb.folder_picker(folders, "up:"),
    )


async def upload_to_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """up:{folder_id} — enter upload mode for a specific folder."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])

    folder = db.get_folder(folder_id)
    if not folder:
        await query.edit_message_text("❌ Folder tidak ditemukan.")
        return

    context.user_data["state"] = "uploading"
    context.user_data["upload_folder_id"] = folder_id

    await query.edit_message_text(
        f"📤 Upload mode: <b>{folder['name']}</b>\n\n"
        f"Kirim file, foto, video, audio — semuanya.\n"
        f"Tekan <b>✅ Done</b> jika selesai.",
        parse_mode="HTML",
    )
    await query.message.reply_text("📤 Kirim file sekarang:", reply_markup=kb.upload_mode())


async def done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: ✅ Done — exit upload mode."""
    folder_id = context.user_data.get("upload_folder_id")
    context.user_data["state"] = "idle"
    context.user_data.pop("upload_folder_id", None)

    await update.message.reply_text("✅ Upload selesai!", reply_markup=kb.main_menu())

    if folder_id:
        from handlers.folders import _show_folder_view
        await _show_folder_view(update, context, folder_id, update.effective_user.id, send_new=True)


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any file sent by the user (photo, video, document, etc.)."""
    info = extract_file_info(update.message)
    if not info:
        return

    state = context.user_data.get("state", "idle")
    user_id = update.effective_user.id

    # 🔄 Check duplicate
    if info.get("file_unique_id"):
        dup = db.find_duplicate_file(user_id, info["file_unique_id"])
        if dup:
            target_fid = context.user_data.get("upload_folder_id") if state == "uploading" else db.get_or_create_inbox_folder(user_id)["id"]
            context.user_data["pending_dup"] = {"info": info, "folder_id": target_fid}
            try:
                await update.message.delete()
            except Exception:
                pass
            dup_folder = dup.get("folders", {}).get("name") if dup.get("folders") else "Storage"
            size = format_size(info.get("file_size", 0))
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    f"⚠️ <b>Duplikat Terdeteksi!</b>\n\n"
                    f"File ini persis sama dengan yang sudah ada:\n"
                    f"📄 <b>{dup['file_name']}</b> ({size})\n"
                    f"📁 Di folder: <b>{dup_folder}</b>\n\n"
                    f"Tetap simpan sebagai salinan baru?"
                ),
                parse_mode="HTML",
                reply_markup=kb.duplicate_warning_keyboard(),
            )
            return

    if state == "uploading":
        folder_id = context.user_data.get("upload_folder_id")
        if folder_id:
            saved = db.save_file(user_id, folder_id, **info)
            if saved:
                emoji = file_emoji(info["file_type"])
                size = format_size(info.get("file_size", 0))
                # Delete original file message from chat to keep chat clean
                try:
                    await update.message.delete()
                except Exception:
                    pass
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{emoji} <b>{info['file_name']}</b> ({size}) ✅",
                    parse_mode="HTML",
                )
            return

    # Quick upload: file sent outside upload mode -> auto-save to "📥 File Masuk"
    inbox = db.get_or_create_inbox_folder(user_id)
    saved = db.save_file(user_id, inbox["id"], **info)

    # Delete original file message from chat to keep it clean
    try:
        await update.message.delete()
    except Exception:
        pass

    if saved:
        emoji = file_emoji(info["file_type"])
        size = format_size(info.get("file_size", 0))
        text = (
            f"{emoji} <b>{info['file_name']}</b> ({size})\n"
            f"📁 Disimpan ke <b>📥 File Masuk</b> ✅"
        )
        buttons = [
            [InlineKeyboardButton("📂 Buka File Masuk", callback_data=f"f:{inbox['id']}"),
             InlineKeyboardButton("📁 Pindahkan", callback_data=f"fm:{saved['id']}")],
        ]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Gagal menyimpan file.",
        )


async def quick_upload_to_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """qup:{folder_id} — save pending file to chosen folder."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    pending = context.user_data.pop("pending_file", None)
    if not pending:
        await query.edit_message_text("❌ File tidak ditemukan. Coba kirim ulang.")
        return

    # Delete original file message from chat
    msg_id = pending.pop("_msg_id", None)
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=msg_id)
        except Exception:
            pass

    folder = db.get_folder(folder_id)
    saved = db.save_file(user_id, folder_id, **pending)
    if saved:
        emoji = file_emoji(pending["file_type"])
        size = format_size(pending.get("file_size", 0))
        folder_name = folder["name"] if folder else "?"
        await query.edit_message_text(
            f"{emoji} <b>{pending['file_name']}</b> ({size})\n"
            f"📁 Disimpan ke <b>{folder_name}</b> ✅",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Gagal menyimpan file.")


async def cancel_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel folder picker."""
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_file", None)
    if pending and "_msg_id" in pending:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=pending["_msg_id"])
        except Exception:
            pass
    await query.edit_message_text("❌ Dibatalkan.")


# ── File preview ───────────────────────────────────────

async def preview_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fi:{file_id} — send file preview with action buttons."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    emoji = file_emoji(f["file_type"])
    size = format_size(f.get("file_size", 0))
    created = f.get("created_at", "")[:10]
    caption = f"{emoji} <b>{f['file_name']}</b>\n📊 {size} • 📅 {created}"
    markup = kb.file_actions(f)

    try:
        send = {
            "photo": query.message.reply_photo,
            "video": query.message.reply_video,
            "animation": query.message.reply_animation,
            "audio": query.message.reply_audio,
            "voice": query.message.reply_voice,
            "video_note": query.message.reply_video_note,
            "document": query.message.reply_document,
        }

        file_type = f["file_type"]
        sender = send.get(file_type, send["document"])

        if file_type == "video_note":
            await sender(f["file_id"], reply_markup=markup)
            await query.message.reply_text(caption, parse_mode="HTML")
        else:
            await sender(f["file_id"], caption=caption, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await query.message.reply_document(f["file_id"], caption=caption,
                                           parse_mode="HTML", reply_markup=markup)


# ── File actions ───────────────────────────────────────

async def download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fdl:{file_id} — re-send file as document (original quality)."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    await query.message.reply_document(f["file_id"],
                                       caption=f"📥 {f['file_name']}")


async def rename_file_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fr:{file_id} — ask for new filename."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    context.user_data["state"] = "renaming_file"
    context.user_data["rename_target_id"] = file_id

    f = db.get_file(file_id)
    name = f["file_name"] if f else "?"
    await query.message.reply_text(
        f"✏️ Rename file <b>{name}</b>\nKetik nama baru:",
        parse_mode="HTML", reply_markup=kb.cancel_only(),
    )


async def move_file_picker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fm:{file_id} — show folder picker to move file."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    user_id = query.from_user.id
    folders = db.get_all_folders(user_id)

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    await query.message.reply_text(
        f"📁 Pindahkan <b>{f['file_name']}</b> ke folder:",
        parse_mode="HTML",
        reply_markup=kb.folder_picker(folders, f"fmt:{file_id}:"),
    )


async def move_to_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fmt:{file_id}:{folder_id} — execute file move."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    file_id = int(parts[1])
    folder_id = int(parts[2])

    f = db.get_file(file_id)
    folder = db.get_folder(folder_id)
    db.move_file(file_id, folder_id)

    file_name = f["file_name"] if f else "?"
    folder_name = folder["name"] if folder else "?"
    await query.edit_message_text(
        f"✅ <b>{file_name}</b> dipindahkan ke 📁 <b>{folder_name}</b>",
        parse_mode="HTML",
    )


async def delete_file_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fx:{file_id} — confirmation."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    await query.message.reply_text(
        f"⚠️ Hapus <b>{f['file_name']}</b>?\nFile akan masuk Trash.",
        parse_mode="HTML",
        reply_markup=kb.confirm_delete_file(file_id, f["folder_id"]),
    )


async def confirm_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fxc:{file_id} — trash the file."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    db.trash_file(file_id)
    await query.answer("File dihapus ✅")

    folder_name = ""
    if f:
        folder = db.get_folder(f["folder_id"])
        folder_name = folder["name"] if folder else ""
    await query.edit_message_text(
        f"🗑 <b>{f['file_name'] if f else '?'}</b> dipindahkan ke Trash.",
        parse_mode="HTML",
    )


async def back_to_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fb:{folder_id} — go back to folder contents view."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])

    from handlers.folders import _show_folder_contents
    await _show_folder_contents(query, context, folder_id, query.from_user.id)


# ── Search ─────────────────────────────────────────────

async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: 🔍 Search."""
    context.user_data["state"] = "searching"
    await update.message.reply_text("🔍 Ketik nama file yang dicari:",
                                    reply_markup=kb.cancel_only())


# ── Star File ──────────────────────────────────────────

async def toggle_star_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fst:{file_id} — toggle star on file."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])

    is_starred = db.toggle_star_file(file_id)
    msg = "Ditambahkan ke Favorit ⭐" if is_starred else "Dihapus dari Favorit"
    await query.answer(msg)

    f = db.get_file(file_id)
    if f:
        await query.edit_message_reply_markup(reply_markup=kb.file_actions(f))


# ── Share File ─────────────────────────────────────────

async def share_file_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fsh:{file_id} — generate public share link for file."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    token = db.get_or_create_file_share_token(file_id)
    bot_me = await context.bot.get_me()
    share_link = f"https://t.me/{bot_me.username}?start=sf_{token}"

    emoji = file_emoji(f["file_type"])
    size = format_size(f.get("file_size", 0))

    text = (
        f"🔗 <b>Public Share Link</b>\n\n"
        f"File: {emoji} <b>{f['file_name']}</b> ({size})\n\n"
        f"Siapa saja yang memiliki link ini dapat mengunduh file ini langsung:\n\n"
        f"<code>{share_link}</code>\n\n"
        f"<i>Klik link di atas untuk menyalin.</i>"
    )
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb.share_file_view(file_id))


async def revoke_file_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fsh_rev:{file_id} — revoke share link."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])
    db.revoke_file_share_token(file_id)
    await query.answer("Link dibatalkan ✅")
    await query.edit_message_text("❌ Link publik untuk file ini telah dinonaktifkan.")


# ── Batch Download ─────────────────────────────────────

async def batch_download_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dlall:{folder_id} — download all files in a folder sequentially."""
    query = update.callback_query
    folder_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    files = db.get_all_files_in_folder(folder_id)
    if not files:
        await query.answer("Folder ini belum memiliki file.", show_alert=True)
        return

    total = len(files)
    await query.answer(f"Mengunduh {total} file...")
    status_msg = await query.message.reply_text(f"📦 Mengirim {total} file... (0/{total})")

    success_count = 0
    for idx, f in enumerate(files, 1):
        try:
            await context.bot.send_document(
                chat_id=user_id,
                document=f["file_id"],
                caption=f"📄 {f['file_name']}",
            )
            success_count += 1
            if idx % 3 == 0 or idx == total:
                await status_msg.edit_text(f"📦 Mengirim file... ({idx}/{total})")
        except Exception:
            pass
        await asyncio.sleep(0.4)

    await status_msg.edit_text(f"✅ Selesai! {success_count}/{total} file berhasil dikirim.")


# ── Public Shared File Actions ─────────────────────────

async def public_download_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """pdl:{file_id} — guest downloads a shared file."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan atau telah dihapus.", show_alert=True)
        return

    await query.message.reply_document(f["file_id"], caption=f"📥 {f['file_name']}")


async def public_save_to_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """psave:{file_id} — guest saves shared file to their own drive."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    folders = db.get_all_folders(user_id)
    if not folders:
        await query.message.reply_text(
            "📁 Kamu belum punya folder. Buat folder dulu lewat menu <b>📁 My Files</b>.",
            parse_mode="HTML",
        )
        return

    # Show folder picker
    await query.message.reply_text(
        "Pilih folder tujuan untuk menyimpan file ini:",
        reply_markup=kb.folder_picker(folders, f"psaveto:{file_id}:"),
    )


async def public_save_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """psaveto:{file_id}:{folder_id} — execute copy file."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    file_id = int(parts[1])
    folder_id = int(parts[2])
    user_id = query.from_user.id

    source_file = db.get_file(file_id)
    if not source_file:
        await query.edit_message_text("❌ File sumber tidak ditemukan.")
        return

    folder = db.get_folder(folder_id)
    folder_name = folder["name"] if folder else "folder"

    saved = db.copy_file_to_user_folder(source_file, user_id, folder_id)
    if saved:
        emoji = file_emoji(source_file["file_type"])
        await query.edit_message_text(
            f"✅ {emoji} <b>{source_file['file_name']}</b> berhasil disimpan ke folder <b>{folder_name}</b>!",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Gagal menyimpan file.")


# ── Recent Files Menu ──────────────────────────────────

async def recent_files_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: 🕒 Recent — show last 15 uploaded files."""
    user_id = update.effective_user.id
    files = db.get_recent_files(user_id, limit=15)

    if not files:
        await update.message.reply_text(
            "🕒 <b>Recent Files</b>\n\nBelum ada file yang diunggah.",
            parse_mode="HTML", reply_markup=kb.main_menu(),
        )
        return

    await update.message.reply_text(
        f"🕒 <b>Recent Files</b> (15 file terakhir):\n\n"
        f"Pilih file untuk melihat preview atau mengunduh:",
        parse_mode="HTML",
        reply_markup=kb.recent_list(files),
    )


# ── Duplicate Resolution ───────────────────────────────

async def duplicate_force_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dup_force — user chose to keep duplicate file."""
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_dup", None)
    if not pending:
        await query.edit_message_text("❌ Data upload kadaluarsa.")
        return

    user_id = query.from_user.id
    saved = db.save_file(user_id, pending["folder_id"], **pending["info"])
    if saved:
        emoji = file_emoji(pending["info"]["file_type"])
        size = format_size(pending["info"].get("file_size", 0))
        await query.edit_message_text(
            f"✅ {emoji} <b>{pending['info']['file_name']}</b> ({size}) tetap disimpan sebagai salinan baru!",
            parse_mode="HTML",
        )
    else:
        await query.edit_message_text("❌ Gagal menyimpan file.")


async def duplicate_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dup_skip — user chose to skip duplicate file."""
    query = update.callback_query
    await query.answer("File duplikat dilewati")
    context.user_data.pop("pending_dup", None)
    await query.edit_message_text("❌ File duplikat diabaikan (tidak disimpan).")


# ── AI Features (Gemini 3.7 Flash) ────────────────────

async def ai_smart_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """aisr:{file_id} — suggest a descriptive filename using Gemini 3.7 Flash."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])

    if not ai_service.is_ai_enabled():
        await query.answer("⚠️ Fitur AI belum aktif (GEMINI_API_KEY belum diisi).", show_alert=True)
        return

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan.", show_alert=True)
        return

    await query.answer("🤖 Gemini 3.7 Flash menganalisis...")
    wait_msg = await query.message.reply_text("⏳ <i>Gemini 3.7 Flash sedang membuat saran nama file baru...</i>", parse_mode="HTML")

    b64 = None
    mime_type = f.get("mime_type")
    # For photos or small files (< 15MB), grab content or thumbnail for visual context
    if f.get("file_size", 0) <= 15 * 1024 * 1024 and f["file_type"] in ("photo", "document"):
        try:
            target_fid = f.get("thumbnail_file_id") or f["file_id"]
            tg_file = await context.bot.get_file(target_fid)
            bio = io.BytesIO()
            await tg_file.download_to_memory(bio)
            b64 = base64.b64encode(bio.getvalue()).decode("utf-8")
            if not mime_type:
                mime_type = "image/jpeg" if f["file_type"] == "photo" else "application/octet-stream"
        except Exception as exc:
            log.warning("Could not download file for rename context: %s", exc)

    new_name = await ai_service.generate_smart_rename(f["file_name"], b64, mime_type)
    try:
        await wait_msg.delete()
    except Exception:
        pass

    if not new_name:
        await query.message.reply_text("❌ Gagal mendapatkan saran nama dari AI.")
        return

    context.user_data[f"ai_rename_{file_id}"] = new_name
    await query.message.reply_text(
        f"✨ <b>Saran Nama Baru dari Gemini 3.7 Flash:</b>\n\n"
        f"Lama: <code>{f['file_name']}</code>\n"
        f"Baru: <code>{new_name}</code>\n\n"
        f"Terapkan nama ini?",
        parse_mode="HTML",
        reply_markup=kb.apply_rename_keyboard(file_id),
    )


async def ai_apply_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """aisrok:{file_id} — apply AI suggested name to file."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])
    new_name = context.user_data.pop(f"ai_rename_{file_id}", None)

    f = db.get_file(file_id)
    if not f or not new_name:
        await query.edit_message_text("❌ Usulan nama sudah kadaluarsa.")
        return

    db.rename_file(file_id, new_name)
    await query.edit_message_text(
        f"✅ Nama file berhasil diubah menjadi:\n<b>{new_name}</b>",
        parse_mode="HTML",
    )


async def ai_summarize_ocr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """aisum:{file_id} — OCR image or summarize document using Gemini 3.7 Flash."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])

    if not ai_service.is_ai_enabled():
        await query.answer("⚠️ Fitur AI belum aktif (GEMINI_API_KEY belum diisi).", show_alert=True)
        return

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan.", show_alert=True)
        return

    if f.get("file_size", 0) > 20 * 1024 * 1024:
        await query.answer("Ukuran file > 20MB melebihi batas Telegram Bot API.", show_alert=True)
        return

    await query.answer("🤖 Gemini 3.7 Flash membaca isi file...")
    wait_msg = await query.message.reply_text("⏳ <i>Sedang membaca dan menganalisis file dengan Gemini 3.7 Flash...</i>", parse_mode="HTML")

    try:
        tg_file = await context.bot.get_file(f["file_id"])
        bio = io.BytesIO()
        await tg_file.download_to_memory(bio)
        b64 = base64.b64encode(bio.getvalue()).decode("utf-8")
        mime_type = f.get("mime_type") or ("image/jpeg" if f["file_type"] == "photo" else "application/pdf")

        summary = await ai_service.summarize_or_ocr(b64, mime_type, f["file_name"])
    except Exception as exc:
        log.error("Failed to run summarize/OCR: %s", exc)
        summary = None

    try:
        await wait_msg.delete()
    except Exception:
        pass

    if not summary:
        await query.message.reply_text("❌ Gagal membaca atau meringkas file ini.")
        return

    header = f"📝 <b>Hasil Analisis Gemini 3.7 Flash:</b>\n📄 <i>{f['file_name']}</i>\n━━━━━━━━━━━━━━━━━━━\n\n"
    full_text = header + summary
    if len(full_text) > 4000:
        full_text = full_text[:3990] + "..."

    try:
        await query.message.reply_text(full_text, parse_mode="Markdown")
    except Exception:
        await query.message.reply_text(full_text)

