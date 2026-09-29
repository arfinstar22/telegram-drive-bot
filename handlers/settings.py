"""Settings: storage info, trash management, sort preference."""

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from utils import format_size, file_emoji


SORT_CYCLE = ["date_desc", "date_asc", "name_asc", "name_desc", "size_desc", "size_asc"]
SORT_LABELS = {
    "date_desc": "📅 Date ↓",
    "date_asc":  "📅 Date ↑",
    "name_asc":  "🔤 Name A-Z",
    "name_desc": "🔤 Name Z-A",
    "size_desc": "📊 Size ↓",
    "size_asc":  "📊 Size ↑",
}


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: ⚙️ Settings / ⚙️ Pengaturan."""
    context.user_data["state"] = "idle"
    user_id = update.effective_user.id
    from utils import get_user_lang
    lang = get_user_lang(context, user_id)
    info = db.get_storage_info(user_id)

    title = "⚙️ <b>Settings</b>" if lang == "en" else "⚙️ <b>Pengaturan</b>"
    await update.message.reply_text(
        title,
        parse_mode="HTML",
        reply_markup=kb.settings_menu(info["trash_count"], lang=lang),
    )


async def storage_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """si — show storage statistics."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    info = db.get_storage_info(user_id)

    type_lines = ""
    for ftype, count in sorted(info["by_type"].items()):
        emoji = file_emoji(ftype)
        type_lines += f"  {emoji} {ftype}: {count}\n"

    text = (
        f"📊 <b>Storage Info</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📁 Folders: {info['total_folders']}\n"
        f"📄 Files: {info['total_files']}\n"
        f"💾 Total size: {format_size(info['total_size'])}\n"
        f"🗑 Trash: {info['trash_count']} file\n"
    )
    if type_lines:
        text += f"\n📋 <b>By type:</b>\n{type_lines}"

    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="sb")]])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=back_btn)


async def settings_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """sb — back to settings menu."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    from utils import get_user_lang
    lang = get_user_lang(context, user_id)
    info = db.get_storage_info(user_id)
    title = "⚙️ <b>Settings</b>" if lang == "en" else "⚙️ <b>Pengaturan</b>"
    await query.edit_message_text(title, parse_mode="HTML",
                                  reply_markup=kb.settings_menu(info["trash_count"], lang=lang))


async def sort_cycle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ss:cycle — cycle through sort options."""
    query = update.callback_query
    current = context.user_data.get("sort", "date_desc")
    idx = SORT_CYCLE.index(current) if current in SORT_CYCLE else 0
    next_sort = SORT_CYCLE[(idx + 1) % len(SORT_CYCLE)]
    context.user_data["sort"] = next_sort

    label = SORT_LABELS.get(next_sort, next_sort)
    await query.answer(f"Sort: {label}")

    user_id = query.from_user.id
    from utils import get_user_lang
    lang = get_user_lang(context, user_id)
    info = db.get_storage_info(user_id)

    await query.edit_message_reply_markup(kb.settings_menu(info["trash_count"], lang=lang))


# ── Trash ──────────────────────────────────────────────

async def trash_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tv — show trashed files."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    files = db.get_trash(user_id)

    if not files:
        text = "🗑 <b>Trash</b>\n\nKosong!"
    else:
        text = f"🗑 <b>Trash</b>\n\n{len(files)} file\n♻️ Restore  ❌ Hapus permanen"

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.trash_list(files))


async def trash_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tr:{file_id} — restore file from trash."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])
    f = db.get_file(file_id)

    if f:
        # Check if folder still exists
        folder = db.get_folder(f["folder_id"])
        if not folder:
            await query.answer("Folder asli sudah dihapus. Tidak bisa restore.", show_alert=True)
            return

        db.restore_file(file_id)
        await query.answer(f"♻️ {f['file_name']} restored!")
    else:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    # Refresh trash view
    user_id = query.from_user.id
    files = db.get_trash(user_id)
    text = f"🗑 <b>Trash</b>\n\n{len(files)} file" if files else "🗑 <b>Trash</b>\n\nKosong!"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.trash_list(files))


async def trash_permanent_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tp:{file_id} — permanently delete from trash."""
    query = update.callback_query
    file_id = int(query.data.split(":")[1])
    f = db.get_file(file_id)

    if f:
        db.permanent_delete(file_id)
        await query.answer(f"❌ {f['file_name']} dihapus permanen")
    else:
        await query.answer("File tidak ditemukan", show_alert=True)
        return

    user_id = query.from_user.id
    files = db.get_trash(user_id)
    text = f"🗑 <b>Trash</b>\n\n{len(files)} file" if files else "🗑 <b>Trash</b>\n\nKosong!"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.trash_list(files))


async def trash_empty_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """te — confirm empty trash."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚠️ <b>Kosongkan Trash?</b>\nSemua file akan dihapus permanen!",
        parse_mode="HTML",
        reply_markup=kb.confirm_empty_trash(),
    )


async def trash_empty_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """tec — empty all trash."""
    query = update.callback_query
    user_id = query.from_user.id
    db.empty_trash(user_id)
    await query.answer("Trash dikosongkan ✅")
    await query.edit_message_text("🗑 <b>Trash</b>\n\nKosong!", parse_mode="HTML",
                                  reply_markup=kb.trash_list([]))


# ── Storage Health & Cleaner ───────────────────────────

async def storage_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """sh:menu — show storage health, duplicates, largest files."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    health = db.get_storage_health(user_id)

    largest_text = ""
    for idx, f in enumerate(health.get("largest_files", []), 1):
        emoji = file_emoji(f["file_type"])
        size = format_size(f.get("file_size", 0))
        folder_name = f.get("folders", {}).get("name") if f.get("folders") else "Storage"
        largest_text += f"  {idx}. {emoji} <b>{f['file_name']}</b> ({size}) — <i>{folder_name}</i>\n"
    if not largest_text:
        largest_text = "  <i>Belum ada file.</i>\n"

    dup_count = health["total_duplicates"]
    dup_size = format_size(health["dup_wasted_size"])
    trash_count = health["trash_count"]
    trash_size = format_size(health["trash_size"])

    text = (
        f"🩺 <b>Storage Health & Cleaner</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 <b>Duplikat Terdeteksi:</b> {dup_count} file ({dup_size})\n"
        f"🗑 <b>Trash Sampah:</b> {trash_count} file ({trash_size})\n\n"
        f"📌 <b>File Terbesar Kamu:</b>\n{largest_text}\n"
        f"Pilih tindakan di bawah untuk membersihkan ruang penyimpanan:"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.storage_health_view(health))


async def clean_duplicates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """sh:clean_dup — clean redundant duplicate files."""
    query = update.callback_query
    user_id = query.from_user.id
    cleaned = db.clean_duplicate_files(user_id)
    await query.answer(f"🧹 Berhasil memindahkan {cleaned} file duplikat ke Trash!", show_alert=True)
    await storage_health(update, context)


# ── Reset Storage ──────────────────────────────────────

async def reset_storage_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rst:prompt — confirm before wiping all user storage."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    info = db.get_storage_info(user_id)

    text = (
        "⚠️ <b>Peringatan: Reset Seluruh Storage</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"Data penyimpanan Anda saat ini:\n"
        f"📁 <b>{info['total_folders']} Folder</b>\n"
        f"📄 <b>{info['total_files']} File</b> ({format_size(info['total_size'])})\n"
        f"🗑 <b>{info['trash_count']} File di Trash</b>\n\n"
        "Tindakan ini akan <b>MENGHAPUS PERMANEN</b> seluruh folder dan file Anda dari Darfin Storage.\n\n"
        "🚨 <b>Data yang terhapus TIDAK DAPAT dipulihkan lagi!</b>\n"
        "Apakah Anda yakin ingin menghapus seluruh file dan mereset storage?"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton("🚨 Ya, Hapus Semua Data", callback_data="rst:confirm")],
        [InlineKeyboardButton("⬅️ Batal / Kembali", callback_data="sb")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def reset_storage_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rst:confirm — execute storage wipe."""
    query = update.callback_query
    user_id = query.from_user.id
    db.reset_user_storage(user_id)
    await query.answer("Storage berhasil di-reset ✅", show_alert=True)

    text = (
        "🧹 <b>Storage Berhasil Direset!</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Seluruh file dan folder Anda telah dihapus secara permanen.\n"
        "Penyimpanan Anda kini bersih seperti akun baru. Folder 📥 <b>File Masuk</b> telah disiapkan."
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="home_nav")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


# ── Account Recovery & Identity ────────────────────────

async def account_recovery_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rec:menu — show account recovery key and manual link option."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    key = f"DS-{user.id}"

    text = (
        "🔑 <b>Identitas & Pemulihan Akun</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Nama:</b> {user.full_name}\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"🏷 <b>Username:</b> @{user.username if user.username else '<i>Belum pasang username</i>'}\n"
        f"🔐 <b>Kunci Pemulihan:</b> <code>{key}</code>\n\n"
        "📌 <b>Bagaimana Bot Mengenali Anda?</b>\n"
        "1. <b>Otomatis:</b> Selama akun Telegram Anda sama, bot otomatis mengenali dan menyimpan seluruh data Anda selamanya.\n"
        "2. <b>Auto-Sync Username:</b> Jika Anda menghapus akun dan membuat akun baru dengan @username yang sama, bot otomatis menawarkan pemulihan data saat klik /start.\n"
        "3. <b>Kunci Akun:</b> Simpan Kunci Pemulihan di atas. Jika Anda ganti akun atau nomor baru, gunakan tombol di bawah untuk menyambungkan data lama ke akun ini."
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton("🔄 Sambungkan Akun Lama", callback_data="rec:input_prompt")],
        [InlineKeyboardButton("⬅️ Kembali ke Settings", callback_data="sb")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


async def account_recovery_input_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rec:input_prompt — ask user to send old username or recovery key."""
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "awaiting_recovery_key"

    text = (
        "🔄 <b>Pemulihan Data Akun Lama</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Kirimkan salah satu data akun lama Anda:\n"
        "• <b>Kunci Pemulihan</b> (contoh: <code>DS-123456789</code>)\n"
        "• <b>Telegram ID lama</b> (contoh: <code>123456789</code>)\n"
        "• <b>Username lama</b> (contoh: <code>@darfinstar</code>)\n\n"
        "Ketik datanya di chat sekarang atau klik Batal:"
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton("❌ Batal", callback_data="sb")],
    ]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))


