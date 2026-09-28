"""File upload, preview, download, rename, move, delete, search."""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from utils import extract_file_info, file_emoji, format_size


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

    # Quick upload: file sent outside upload mode
    info["_msg_id"] = update.message.message_id
    context.user_data["pending_file"] = info
    folders = db.get_all_folders(user_id)

    if not folders:
        await update.message.reply_text(
            "📁 Belum ada folder. Buat folder dulu lewat <b>My Files</b>.",
            parse_mode="HTML", reply_markup=kb.main_menu(),
        )
        return

    await update.message.reply_text(
        f"📎 File diterima: <b>{info['file_name']}</b>\n\nPilih folder tujuan:",
        parse_mode="HTML",
        reply_markup=kb.folder_picker(folders, "qup:"),
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
