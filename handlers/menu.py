"""Start command, main menu, text input router, cancel/home."""

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb


WELCOME = (
    "🗂 <b>Telegram Drive</b>\n"
    "\n"
    "Cloud storage unlimited, gratis, langsung di Telegram.\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "📁 <b>My Files</b> — Folder & file kamu\n"
    "📤 <b>Upload</b> — Upload file baru\n"
    "🔍 <b>Search</b> — Cari file\n"
    "⚙️ <b>Settings</b> — Info & pengaturan\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "\n"
    "Mulai dengan buat folder pertama! 📁"
)


def _reset(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "idle"
    context.user_data.pop("pending_file", None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)
    _reset(context)
    await update.message.reply_text(WELCOME, parse_mode="HTML", reply_markup=kb.main_menu())


async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    await update.message.reply_text("🏠 Menu utama", reply_markup=kb.main_menu())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=kb.main_menu())


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route free-text input based on current user state."""
    state = context.user_data.get("state", "idle")
    text = update.message.text.strip()

    if not text:
        return

    if state == "creating_folder":
        await _create_folder(update, context, text)
    elif state == "renaming_folder":
        await _rename_folder(update, context, text)
    elif state == "renaming_file":
        await _rename_file(update, context, text)
    elif state == "searching":
        await _do_search(update, context, text)
    else:
        await update.message.reply_text(
            "Pilih menu di bawah, atau kirim file untuk upload.",
            reply_markup=kb.main_menu(),
        )


async def _create_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    user_id = update.effective_user.id
    parent_id = context.user_data.get("creating_folder_parent")
    parent_id = parent_id if parent_id else None

    folder = db.create_folder(user_id, name, parent_id)
    _reset(context)

    if folder:
        await update.message.reply_text(f"✅ Folder <b>{name}</b> dibuat!", parse_mode="HTML",
                                        reply_markup=kb.main_menu())
        # Show parent folder contents
        from handlers.folders import _show_folder_view
        await _show_folder_view(update, context, parent_id, user_id, send_new=True)
    else:
        await update.message.reply_text("❌ Gagal membuat folder.", reply_markup=kb.main_menu())


async def _rename_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    folder_id = context.user_data.get("rename_target_id")
    db.rename_folder(folder_id, name)
    _reset(context)
    await update.message.reply_text(f"✅ Folder renamed to <b>{name}</b>", parse_mode="HTML",
                                    reply_markup=kb.main_menu())
    from handlers.folders import _show_folder_view
    folder = db.get_folder(folder_id)
    if folder:
        await _show_folder_view(update, context, folder.get("parent_id"), update.effective_user.id, send_new=True)


async def _rename_file(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    file_id = context.user_data.get("rename_target_id")
    db.rename_file(file_id, name)
    _reset(context)
    await update.message.reply_text(f"✅ File renamed to <b>{name}</b>", parse_mode="HTML",
                                    reply_markup=kb.main_menu())


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    user_id = update.effective_user.id
    results = db.search_files(user_id, query)
    _reset(context)

    if not results:
        await update.message.reply_text(f"🔍 Tidak ditemukan file untuk: <b>{query}</b>",
                                        parse_mode="HTML", reply_markup=kb.main_menu())
        return

    from utils import file_emoji, format_size, truncate
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    for f in results[:15]:
        emoji = file_emoji(f["file_type"])
        name = truncate(f["file_name"], 20)
        size = format_size(f.get("file_size", 0))
        folder_name = ""
        if f.get("folders") and isinstance(f["folders"], dict):
            folder_name = f" 📁{f['folders']['name']}"
        buttons.append([InlineKeyboardButton(
            f"{emoji} {name} — {size}{folder_name}",
            callback_data=f"fi:{f['id']}",
        )])

    text = f"🔍 Hasil pencarian: <b>{query}</b>\n{len(results)} file ditemukan"
    await update.message.reply_text(text, parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(buttons))
