"""File upload, preview, download, rename, move, delete, search."""

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
                await update.message.reply_text(
                    f"{emoji} <b>{info['file_name']}</b> ({size}) ✅",
                    parse_mode="HTML",
                )
            return

    # Quick upload: file sent outside upload mode
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
    context.user_data.pop("pending_file", None)
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
