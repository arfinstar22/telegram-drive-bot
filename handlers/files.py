"""File upload, preview, download, rename, move, delete, search."""

import asyncio
import base64
import io
import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import smart_organizer
import database as db
import keyboards as kb
import time
import secrets
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


_upload_batches: dict[int, dict] = {}


async def _debounce_flush(user_id: int, context: ContextTypes.DEFAULT_TYPE, delay: float = 1.8):
    try:
        await asyncio.sleep(delay)
        await _flush_upload_batch(user_id, context)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.error("Error in _debounce_flush: %s", exc)


async def _flush_upload_batch(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    batch = _upload_batches.pop(user_id, None)
    if not batch:
        return

    files = batch.get("files", [])
    if not files:
        return

    chat_id = batch["chat_id"]
    msg_id = batch.get("msg_id")
    folder_id = batch["folder_id"]
    folder_name = batch["folder_name"]
    is_inbox = batch.get("is_inbox", False)

    total_size = sum(f.get("size", 0) for f in files)
    dup_count = batch.get("dup_count", 0)

    # Exactly 1 file
    if len(files) == 1 and dup_count == 0:
        f = files[0]
        emoji = file_emoji(f["type"])
        size_str = format_size(f["size"])
        text = (
            f"{emoji} <b>{f['name']}</b> ({size_str})\n"
            f"📁 Disimpan ke <b>{folder_name}</b> ✅"
        )
        keyboard = kb.single_upload_keyboard(folder_id, f["id"])
    else:
        # Multiple files in batch
        count = len(files)
        preview_lines = ""
        for f in files[-4:]:
            em = file_emoji(f["type"])
            sz = format_size(f["size"])
            name_cut = f["name"][:25] + "..." if len(f["name"]) > 28 else f["name"]
            preview_lines += f"  • {em} <code>{name_cut}</code> ({sz})\n"

        more_count = count - 4
        if more_count > 0:
            preview_lines += f"  <i>(+ {more_count} file lainnya)</i>\n"

        dup_info = f"\n⚠️ <i>({dup_count} file duplikat dilewati)</i>" if dup_count > 0 else ""

        text = (
            f"📦 <b>Batch Upload Selesai!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>{count} file</b> berhasil disimpan!\n"
            f"💾 Total: <b>{format_size(total_size)}</b>\n"
            f"📁 Folder: <b>{folder_name}</b>{dup_info}\n\n"
            f"📋 <b>Rincian File:</b>\n{preview_lines}"
        )

        batch_id = secrets.token_hex(4)
        context.user_data[f"batch_files_{batch_id}"] = [f["id"] for f in files]
        keyboard = kb.batch_upload_keyboard(folder_id, batch_id, can_smart_sort=is_inbox)

    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def done_uploading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: ✅ Done — exit upload mode."""
    user_id = update.effective_user.id
    folder_id = context.user_data.get("upload_folder_id")
    context.user_data["state"] = "idle"
    context.user_data.pop("upload_folder_id", None)

    # Immediately finalize any ongoing batch upload
    if user_id in _upload_batches:
        b = _upload_batches[user_id]
        if b.get("task"):
            b["task"].cancel()
        await _flush_upload_batch(user_id, context)

    await update.message.reply_text("✅ Mode upload selesai!", reply_markup=kb.main_menu())

    if folder_id:
        from handlers.folders import _show_folder_view
        await _show_folder_view(update, context, folder_id, user_id, send_new=True)


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming file upload with intelligent batch buffering and anti-spam."""
    info = extract_file_info(update.message)
    if not info:
        return

    state = context.user_data.get("state", "idle")
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if state == "uploading":
        folder_id = context.user_data.get("upload_folder_id")
        f_obj = db.get_folder(folder_id) if folder_id else None
        folder_name = f_obj["name"] if f_obj else "Folder"
        is_inbox = False
    else:
        inbox = db.get_or_create_inbox_folder(user_id)
        folder_id = inbox["id"]
        folder_name = "📥 File Masuk"
        is_inbox = True

    # Delete incoming user media message to keep the chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

    batch = _upload_batches.get(user_id)
    if not batch or batch.get("folder_id") != folder_id:
        batch = {
            "chat_id": chat_id,
            "folder_id": folder_id,
            "folder_name": folder_name,
            "is_inbox": is_inbox,
            "files": [],
            "dup_count": 0,
            "msg_id": None,
            "task": None,
            "last_edit": 0.0,
        }
        _upload_batches[user_id] = batch

    # Duplicate check
    if info.get("file_unique_id"):
        dup = db.find_duplicate_file(user_id, info["file_unique_id"])
        if dup:
            batch["dup_count"] += 1
            if batch["task"]:
                batch["task"].cancel()
            batch["task"] = asyncio.create_task(_debounce_flush(user_id, context, delay=1.8))
            return

    # Save to database
    saved = db.save_file(user_id, folder_id, **info)
    if not saved:
        return

    batch["files"].append({
        "id": saved["id"],
        "name": info["file_name"],
        "size": info.get("file_size", 0),
        "type": info["file_type"],
    })

    now = time.time()
    count = len(batch["files"])

    if batch["msg_id"] is None:
        try:
            m = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ <b>Menyimpan file ke {folder_name}...</b> (1 file)",
                parse_mode="HTML",
            )
            batch["msg_id"] = m.message_id
            batch["last_edit"] = now
        except Exception as exc:
            log.warning("Could not send initial upload status message: %s", exc)
    else:
        if now - batch["last_edit"] >= 1.2:
            total_sz = sum(f["size"] for f in batch["files"])
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=batch["msg_id"],
                    text=f"⏳ <b>Mengunggah batch ({count} file tersimpan)...</b>\n💾 Total: {format_size(total_sz)}",
                    parse_mode="HTML",
                )
                batch["last_edit"] = now
            except Exception:
                pass

    if batch["task"]:
        batch["task"].cancel()
    batch["task"] = asyncio.create_task(_debounce_flush(user_id, context, delay=1.8))


async def batch_smart_sort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """bsm:{batch_id} — auto-organize all files in a batch into smart folders."""
    query = update.callback_query
    await query.answer()
    batch_id = query.data.split(":")[1]
    user_id = query.from_user.id

    file_ids = context.user_data.pop(f"batch_files_{batch_id}", None)
    if not file_ids:
        await query.answer("Data batch sudah kadaluarsa.", show_alert=True)
        return

    folder_map: dict[str, int] = {}
    moved_count = 0

    for fid in file_ids:
        f = db.get_file(fid)
        if not f:
            continue
        suggested_name, _, _ = smart_organizer.suggest_folder(f["file_name"], f.get("file_type", "document"))
        if suggested_name not in folder_map:
            dest = db.get_or_create_folder(user_id, suggested_name)
            folder_map[suggested_name] = dest["id"]

        target_folder_id = folder_map[suggested_name]
        db.move_file(fid, target_folder_id)
        moved_count += 1

    summary_lines = ""
    for fname in sorted(folder_map.keys())[:5]:
        summary_lines += f"  • 📁 <b>{fname}</b>\n"
    if len(folder_map) > 5:
        summary_lines += f"  <i>(+ {len(folder_map) - 5} folder lainnya)</i>\n"

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 Buka My Files", callback_data="f:0")],
        [InlineKeyboardButton("🗑 Bersihkan Notif", callback_data="msg_del")],
    ])
    await query.edit_message_text(
        f"✨ <b>Smart Sort Berhasil!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Berhasil merapikan <b>{moved_count} file</b> ke dalam folder:\n"
        f"{summary_lines}\n"
        f"Semua file telah tertata rapi sesuai kategori dan tahunnya!",
        parse_mode="HTML",
        reply_markup=btn,
    )


async def delete_notification_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """msg_del — delete notification message to keep chat completely clean."""
    query = update.callback_query
    await query.answer("Notifikasi dibersihkan 🧹")
    try:
        await query.message.delete()
    except Exception:
        pass



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


# ── Smart Organizer & Smart Rename (Rule/Dictionary) ──

async def smart_folder_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """smf:{file_id} — analyze file and suggest auto folder organization."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan.", show_alert=True)
        return

    folder_name, topic, year = smart_organizer.suggest_folder(f["file_name"], f.get("file_type", "document"))
    context.user_data[f"smf_target_{file_id}"] = folder_name

    current_folder = db.get_folder(f["folder_id"])
    curr_name = current_folder["name"] if current_folder else "Inbox"

    text = (
        f"🗂 <b>Smart Folder Organizer</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📄 File: <code>{f['file_name']}</code>\n"
        f"📂 Folder Saat Ini: <i>{curr_name}</i>\n"
        f"🎯 <b>Folder Saran:</b> <code>{folder_name}</code>\n"
        f"🏷 Kategori: <i>{topic}</i>\n"
        f"📅 Periode/Tahun: <i>{year or 'Umum'}</i>\n\n"
        f"Pindahkan file ini ke folder <b>{folder_name}</b>?\n"
        f"<i>(Folder otomatis dibuat jika belum ada)</i>"
    )
    await query.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.smart_folder_confirm(file_id),
    )


async def smart_folder_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """smf_ok:{file_id} — move file into the suggested smart folder."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    f = db.get_file(file_id)
    if not f:
        await query.edit_message_text("❌ File tidak ditemukan.")
        return

    target_name = context.user_data.pop(f"smf_target_{file_id}", None)
    if not target_name:
        target_name, _, _ = smart_organizer.suggest_folder(f["file_name"], f.get("file_type", "document"))

    target_folder = db.get_or_create_folder(user_id, target_name)
    db.move_file(file_id, target_folder["id"])

    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📂 Buka Folder '{target_name}'", callback_data=f"f:{target_folder['id']}")],
        [InlineKeyboardButton("🏠 Beranda", callback_data="home_nav")],
    ])
    await query.edit_message_text(
        f"✅ <b>File Berhasil Dipindahkan!</b>\n\n"
        f"📄 File: <code>{f['file_name']}</code>\n"
        f"📁 Folder Baru: <b>{target_name}</b>",
        parse_mode="HTML",
        reply_markup=btn,
    )


async def smart_rename_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """smr:{file_id} (or aisr legacy) — suggest cleaned descriptive name using pattern dictionary."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])

    f = db.get_file(file_id)
    if not f:
        await query.answer("File tidak ditemukan.", show_alert=True)
        return

    new_name = smart_organizer.smart_rename(f["file_name"])
    if new_name == f["file_name"]:
        await query.answer("Nama file ini sudah rapi! ✨", show_alert=True)
        return

    context.user_data[f"smr_new_{file_id}"] = new_name
    await query.message.reply_text(
        f"✨ <b>Saran Nama Rapi:</b>\n\n"
        f"Lama: <code>{f['file_name']}</code>\n"
        f"Baru: <code>{new_name}</code>\n\n"
        f"Terapkan nama ini?",
        parse_mode="HTML",
        reply_markup=kb.apply_rename_keyboard(file_id),
    )


async def smart_apply_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """smr_ok:{file_id} (or aisrok legacy) — apply suggested smart name to file."""
    query = update.callback_query
    await query.answer()
    file_id = int(query.data.split(":")[1])
    new_name = context.user_data.pop(f"smr_new_{file_id}", None)

    f = db.get_file(file_id)
    if not f or not new_name:
        await query.edit_message_text("❌ Usulan nama sudah kadaluarsa.")
        return

    db.rename_file(file_id, new_name)
    await query.edit_message_text(
        f"✅ Nama file berhasil diubah menjadi:\n<b>{new_name}</b>",
        parse_mode="HTML",
    )


