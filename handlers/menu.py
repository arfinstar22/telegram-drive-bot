"""Start command, main menu, text input router, cancel/home."""

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import database as db
import keyboards as kb


WELCOME_ID = (
    "🗂 <b>Telegram Drive</b>\n\n"
    "Cloud storage unlimited, gratis, langsung di Telegram.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "📱 <b>Buka WebApp Drive</b> — Tampilan visual web modern\n"
    "📁 <b>File Saya</b> — Folder & berkas Anda\n"
    "📤 <b>Upload</b> — Upload file baru\n"
    "⭐ <b>Favorit</b> — Berkas & folder favorit\n"
    "🕒 <b>Terbaru</b> — Berkas terakhir diunggah\n"
    "🔍 <b>Cari</b> — Cari berkas cepat\n"
    "⚙️ <b>Pengaturan</b> — Info & pengaturan\n"
    "━━━━━━━━━━━━━━━━━━━\n\n"
    "Mulai dengan buat folder atau klik Buka WebApp! 📱"
)

WELCOME_EN = (
    "🗂 <b>Telegram Drive</b>\n\n"
    "Unlimited, free cloud storage directly in Telegram.\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "📱 <b>Open WebApp Drive</b> — Modern visual web UI\n"
    "📁 <b>My Files</b> — Your folders & files\n"
    "📤 <b>Upload</b> — Upload new files\n"
    "⭐ <b>Starred</b> — Favorite files & folders\n"
    "🕒 <b>Recent</b> — Recently uploaded files\n"
    "🔍 <b>Search</b> — Quick file search\n"
    "⚙️ <b>Settings</b> — Storage & settings\n"
    "━━━━━━━━━━━━━━━━━━━\n\n"
    "Get started by creating a folder or launch WebApp! 📱"
)

WELCOME = WELCOME_ID


def _reset(context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "idle"
    context.user_data.pop("pending_file", None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing_user = db.get_user(user.id)
    db.upsert_user(user.id, user.username, user.full_name)
    db.get_or_create_inbox_folder(user.id)
    _reset(context)

    # First time user or user without language preference set yet
    if not existing_user or not existing_user.get("language"):
        text = (
            "🌐 <b>Pilih Bahasa / Choose Language:</b>\n\n"
            "👋 Selamat datang! Silakan pilih bahasa tampilan bot:\n"
            "👋 Welcome! Please select your preferred bot language:"
        )
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=kb.language_picker(),
        )
        return

    lang = existing_user.get("language", "id")
    context.user_data["language"] = lang

    # Check for deep-link argument (e.g. /start sf_xxx or /start sd_xxx)
    if context.args:
        arg = context.args[0]
        if arg.startswith("sf_"):
            token = arg[3:]
            f = db.get_file_by_share_token(token)
            if not f:
                err_msg = "❌ Shared file link is invalid or expired." if lang == "en" else "❌ Link file ini sudah tidak valid atau telah dinonaktifkan."
                await update.message.reply_text(
                    err_msg,
                    reply_markup=kb.main_menu(lang),
                )
                return

            import time
            from utils import file_emoji, format_size, parse_share_token
            sec = parse_share_token(f.get("share_token") or "")

            # Expiration check
            if sec.get("expires_at") and int(time.time()) > sec["expires_at"]:
                err_msg = "⏳ This shared link has expired." if lang == "en" else "⏳ Link file ini sudah kadaluarsa (expired)."
                await update.message.reply_text(err_msg, reply_markup=kb.main_menu(lang))
                return

            # Download limit / burn check
            if sec.get("limit") is not None and sec.get("count", 0) >= sec["limit"]:
                err_msg = "🔥 This link was 1-time download only and has expired." if lang == "en" else "🔥 Link file ini memiliki batas 1x unduh dan sudah hangus."
                await update.message.reply_text(err_msg, reply_markup=kb.main_menu(lang))
                return

            is_own_file = (f["user_id"] == user.id)

            # PIN check
            if sec.get("pin") and not is_own_file:
                context.user_data["state"] = f"awaiting_share_pin:{token}"
                context.user_data["share_file_id"] = f["id"]
                prompt = (
                    f"🔒 <b>PIN Protected File</b>\n\n"
                    f"File <code>{f['file_name']}</code> is protected with a 4-digit PIN.\n\n"
                    f"Please enter the 4-digit PIN to unlock access:"
                ) if lang == "en" else (
                    f"🔒 <b>File Dilindungi PIN</b>\n\n"
                    f"File <code>{f['file_name']}</code> diproteksi dengan 4-digit PIN rahasia oleh pemiliknya.\n\n"
                    f"Silakan ketik PIN untuk membuka akses:"
                )
                await update.message.reply_text(prompt, parse_mode="HTML")
                return

            emoji = file_emoji(f["file_type"])
            size = format_size(f.get("file_size", 0))

            title = "🔗 <b>Shared File</b>" if lang == "en" else "🔗 <b>File Bersama</b>"
            subtitle = "Shared with you:" if lang == "en" else "File ini dibagikan kepada kamu:"
            await update.message.reply_text(
                f"{title}\n\n"
                f"{emoji} <b>{f['file_name']}</b> ({size})\n\n"
                f"{subtitle}",
                parse_mode="HTML",
                reply_markup=kb.public_shared_file(f["id"], can_save=not is_own_file),
            )
            return

        elif arg.startswith("sd_"):
            token = arg[3:]
            folder = db.get_folder_by_share_token(token)
            if not folder:
                err_msg = "❌ Shared folder link is invalid or expired." if lang == "en" else "❌ Link folder ini sudah tidak valid atau telah dinonaktifkan."
                await update.message.reply_text(
                    err_msg,
                    reply_markup=kb.main_menu(lang),
                )
                return

            files = db.get_all_files_in_folder(folder["id"])
            from utils import file_emoji, format_size, truncate
            buttons = []
            for f in files[:20]:
                emoji = file_emoji(f["file_type"])
                size = format_size(f.get("file_size", 0))
                name = truncate(f["file_name"], 20)
                buttons.append([InlineKeyboardButton(f"{emoji} {name} — {size}", callback_data=f"pdl:{f['id']}")])
            home_title = "🏠 Home" if lang == "en" else "🏠 Menu Utama"
            buttons.append([InlineKeyboardButton(home_title, callback_data="home_nav")])
            markup = InlineKeyboardMarkup(buttons)

            hdr = "🔗 <b>Shared Folder</b>" if lang == "en" else "🔗 <b>Folder Bersama</b>"
            desc = f"Total {len(files)} files. Click below to download:" if lang == "en" else f"Total {len(files)} file. Klik file di bawah untuk langsung mengunduh:"
            await update.message.reply_text(
                f"{hdr}: 📁 <b>{folder['name']}</b>\n\n{desc}",
                parse_mode="HTML",
                reply_markup=markup,
            )
            return

    await _send_welcome_screen(update, context, user.id, lang)


async def callback_language_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """set_lang:prompt — prompt language change from settings."""
    query = update.callback_query
    await query.answer()
    text = (
        "🌐 <b>Pilih Bahasa / Choose Language:</b>\n\n"
        "Silakan pilih bahasa yang diinginkan:\n"
        "Please choose your preferred language:"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.language_picker())


async def callback_language_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """set_lang:(id|en) — handle language selection."""
    query = update.callback_query
    await query.answer()
    lang = query.data.split(":")[1]
    user_id = query.from_user.id

    db.update_user(user_id, language=lang)
    context.user_data["language"] = lang

    try:
        await query.message.delete()
    except Exception:
        pass

    await _send_welcome_screen(query, context, user_id, lang)


async def _send_welcome_screen(update_or_query, context: ContextTypes.DEFAULT_TYPE, user_id: int, lang: str):
    user = update_or_query.effective_user
    chat_id = update_or_query.effective_chat.id
    info = db.get_storage_info(user_id)

    from utils import format_size
    if info["total_files"] > 0 or info["total_folders"] > 1:
        if lang == "en":
            text = (
                f"👋 <b>Welcome Back, {user.first_name}!</b>\n"
                f"All your data is safely stored:\n"
                f"📁 <b>{info['total_folders']} Folders</b> • 📄 <b>{info['total_files']} Files</b> ({format_size(info['total_size'])})\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>My Files</b> — Your folders & files\n"
                f"📤 <b>Upload</b> — Upload new files\n"
                f"🔍 <b>Search</b> — Quick search\n"
                f"⚙️ <b>Settings</b> — Storage info & settings\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )
        else:
            text = (
                f"👋 <b>Selamat Datang Kembali, {user.first_name}!</b>\n"
                f"Semua data Anda tersimpan aman:\n"
                f"📁 <b>{info['total_folders']} Folder</b> • 📄 <b>{info['total_files']} File</b> ({format_size(info['total_size'])})\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📁 <b>File Saya</b> — Folder & berkas Anda\n"
                f"📤 <b>Upload</b> — Upload berkas baru\n"
                f"🔍 <b>Cari</b> — Cari berkas cepat\n"
                f"⚙️ <b>Pengaturan</b> — Info, kesehatan & reset\n"
                f"━━━━━━━━━━━━━━━━━━━"
            )
    else:
        text = WELCOME_EN if lang == "en" else WELCOME_ID

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=kb.main_menu(lang),
    )


async def open_webapp_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bridge handler for '📱 Buka WebApp Drive' text button from permanent Reply Keyboard.

    Sends an Inline Keyboard button containing the official Inline WebApp URL.
    This ensures Telegram client opens an Inline Mini App with full cryptographic initData.
    """
    user = update.effective_user
    user_id = user.id if user else 0
    existing_user = db.get_user(user_id) if user_id else None
    lang = (existing_user or {}).get("language", "id") if existing_user else context.user_data.get("language", "id")

    if lang == "en":
        text = (
            "📂 <b>Darfin Storage</b>\n\n"
            "Click the button below to open your Drive."
        )
    else:
        text = (
            "📂 <b>Darfin Storage</b>\n\n"
            "Klik tombol di bawah untuk membuka Drive Anda."
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=kb.inline_webapp_button(lang),
    )



async def starred_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: ⭐ Starred — show favorite folders & files."""
    user_id = update.effective_user.id
    _reset(context)
    folders = db.get_starred_folders(user_id)
    files = db.get_starred_files(user_id)

    if not folders and not files:
        await update.message.reply_text(
            "⭐ <b>Starred (Favorit)</b>\n\n"
            "Belum ada folder atau file yang kamu beri bintang.\n"
            "Buka folder atau file, lalu klik tombol <b>⭐ Star</b> untuk menandainya!",
            parse_mode="HTML", reply_markup=kb.main_menu(),
        )
        return

    total = len(folders) + len(files)
    await update.message.reply_text(
        f"⭐ <b>Starred Items</b> ({total} favorit):\n\n"
        f"Akses cepat ke folder dan file favorit kamu:",
        parse_mode="HTML",
        reply_markup=kb.starred_list(folders, files),
    )


async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    user_id = update.effective_user.id
    from utils import get_user_lang
    lang = get_user_lang(context, user_id)
    welcome_text = WELCOME_EN if lang == "en" else WELCOME_ID
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            welcome_text, parse_mode="HTML", reply_markup=kb.main_menu(lang)
        )
    elif update.message:
        await update.message.reply_text(
            welcome_text, parse_mode="HTML", reply_markup=kb.main_menu(lang)
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reset(context)
    user_id = update.effective_user.id
    from utils import get_user_lang
    lang = get_user_lang(context, user_id)
    msg = "❌ Cancelled." if lang == "en" else "❌ Dibatalkan."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg, reply_markup=kb.main_menu(lang))
    elif update.message:
        await update.message.reply_text(msg, reply_markup=kb.main_menu(lang))


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
    elif state == "awaiting_recovery_key":
        await _process_recovery_key(update, context, text)
    elif state.startswith("awaiting_share_pin:"):
        await _verify_share_pin(update, context, text)
    elif state == "awaiting_file_share_pin":
        await _save_file_share_pin(update, context, text)
    elif state == "awaiting_file_tags":
        await _save_file_tags(update, context, text)
    else:
        user_id = update.effective_user.id
        from utils import get_user_lang
        lang = get_user_lang(context, user_id)
        hint = "Choose a menu below, or send a file to upload." if lang == "en" else "Pilih menu di bawah, atau kirim file untuk upload."
        await update.message.reply_text(
            hint,
            reply_markup=kb.main_menu(lang),
        )


async def _process_recovery_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key_input: str):
    clean = key_input.strip()
    _reset(context)

    if not clean.upper().startswith("DREC-"):
        await update.message.reply_text(
            "❌ <b>Format kode pemulihan tidak valid.</b>\n\n"
            "Format kode pemulihan yang sah adalah <code>DREC-xxxx-xxxx</code>.\n"
            "Buat kode ini terlebih dahulu dari akun Telegram lama Anda melalui menu <b>Settings > Identitas & Pemulihan Akun</b>.",
            parse_mode="HTML",
            reply_markup=kb.main_menu(),
        )
        return

    success, msg = db.redeem_account_recovery_code(update.effective_user.id, clean)
    if not success:
        await update.message.reply_text(
            f"❌ <b>Gagal memulihkan data:</b>\n{msg}",
            parse_mode="HTML",
            reply_markup=kb.main_menu(),
        )
        return

    await update.message.reply_text(
        f"🎉 <b>Data Berhasil Dipulihkan!</b>\n\n"
        f"Seluruh file dan folder dari akun lama Anda telah berhasil dipindahkan ke akun ini.\n"
        f"Buka 📁 <b>My Files</b> untuk melihat seluruh berkas Anda!",
        parse_mode="HTML",
        reply_markup=kb.main_menu(),
    )


async def _verify_share_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin_text: str):
    file_id = context.user_data.get("share_file_id")
    f = db.get_file(file_id) if file_id else None
    if not f:
        _reset(context)
        await update.message.reply_text("❌ File tidak ditemukan atau link sudah kadaluarsa.", reply_markup=kb.main_menu())
        return

    from utils import parse_share_token, file_emoji, format_size, verify_pin
    sec = parse_share_token(f.get("share_token") or "")
    stored_pin = sec.get("pin")

    attempts = context.user_data.get("pin_attempts", 0) + 1
    context.user_data["pin_attempts"] = attempts

    if attempts > 5:
        _reset(context)
        await update.message.reply_text("❌ Terlalu banyak percobaan PIN salah. Akses dibatalkan.", reply_markup=kb.main_menu())
        return

    if stored_pin and not verify_pin(pin_text.strip(), stored_pin):
        await update.message.reply_text(f"❌ <b>PIN salah!</b> (Percobaan {attempts}/5). Silakan coba lagi:", parse_mode="HTML")
        return

    _reset(context)
    user = update.effective_user
    is_own_file = (f["user_id"] == user.id)
    emoji = file_emoji(f["file_type"])
    size = format_size(f.get("file_size", 0))

    await update.message.reply_text(
        f"🔓 <b>PIN Benar! Akses Diberikan.</b>\n\n"
        f"🔗 <b>File Bersama:</b>\n"
        f"{emoji} <b>{f['file_name']}</b> ({size})\n\n"
        f"File ini dibagikan kepada kamu:",
        parse_mode="HTML",
        reply_markup=kb.public_shared_file(f["id"], can_save=not is_own_file),
    )


async def _save_file_share_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin_text: str):
    file_id = context.user_data.get("sec_file_id")
    user_id = update.effective_user.id
    clean_pin = pin_text.strip()
    if not clean_pin.isdigit() or len(clean_pin) != 4:
        await update.message.reply_text(
            "❌ <b>Format PIN salah.</b>\nPIN harus 4 digit angka (contoh: <code>1234</code>).\nSilakan coba lagi atau kirim /cancel:",
            parse_mode="HTML",
        )
        return

    _reset(context)
    db.update_file_share_security(file_id, pin=clean_pin, user_id=user_id)
    await update.message.reply_text(
        f"✅ <b>PIN Proteksi Berhasil Disimpan!</b>\n\n"
        f"PIN: <code>{clean_pin}</code>\n"
        f"Setiap pengguna yang membuka link harus memasukkan PIN ini untuk mengunduh.",
        parse_mode="HTML",
        reply_markup=kb.main_menu(),
    )


async def _save_file_tags(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_text: str):
    import re
    file_id = context.user_data.get("tag_file_id")
    user_id = update.effective_user.id
    _reset(context)

    f = db.get_file_for_user(file_id, user_id) if file_id else None
    if not f:
        await update.message.reply_text("❌ File tidak ditemukan atau akses ditolak.", reply_markup=kb.main_menu())
        return

    found_tags = re.findall(r"#([a-zA-Z0-9_-]+)", raw_text)
    note_clean = re.sub(r"#[a-zA-Z0-9_-]+", "", raw_text).strip()
    note_clean = re.sub(r"\s+", " ", note_clean)

    db.update_file_notes_and_tags(file_id, note=note_clean, tags=found_tags, user_id=user_id)

    tag_str = " ".join(f"#{t}" for t in found_tags) if found_tags else "<i>(Tidak ada)</i>"
    note_str = f"<i>{note_clean}</i>" if note_clean else "<i>(Tidak ada)</i>"

    await update.message.reply_text(
        f"✅ <b>Catatan & Tag Disimpan!</b>\n\n"
        f"📄 File: <code>{f['file_name']}</code>\n"
        f"📝 Catatan: {note_str}\n"
        f"🏷 Tag: {tag_str}",
        parse_mode="HTML",
        reply_markup=kb.main_menu(),
    )


async def callback_recovery_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rec:link:{old_user_id} — deprecated unsafe direct link handler."""
    query = update.callback_query
    await query.answer("Fitur ini dinonaktifkan demi keamanan.", show_alert=True)
    await query.edit_message_text(
        "❌ <b>Pemulihan Otomatis Dinonaktifkan</b>\n\n"
        "Demi keamanan data pengguna, pemulihan akun otomatis berdasarkan ID/username telah dinonaktifkan.\n\n"
        "Silakan buka akun Telegram lama Anda, buka menu <b>Settings > Identitas & Pemulihan Akun > Buat Kode Pemulihan Sementara</b>, lalu masukkan kode tersebut di akun ini.",
        parse_mode="HTML",
    )


async def callback_recovery_ignore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """rec:ignore — ignore old account and start fresh."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ Anda memilih memulai storage baru.", parse_mode="HTML")
    await query.message.reply_text(WELCOME, parse_mode="HTML", reply_markup=kb.main_menu())


async def _create_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    user_id = update.effective_user.id
    parent_id = context.user_data.get("creating_folder_parent")
    parent_id = parent_id if parent_id else None

    folder = db.create_folder(user_id, name, parent_id)
    _reset(context)

    if folder:
        await update.message.reply_text(f"✅ Folder <b>{name}</b> dibuat!", parse_mode="HTML",
                                        reply_markup=kb.main_menu())
        from handlers.folders import _show_folder_view
        await _show_folder_view(update, context, parent_id, user_id, send_new=True)
    else:
        await update.message.reply_text("❌ Gagal membuat folder.", reply_markup=kb.main_menu())


async def _rename_folder(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    folder_id = context.user_data.get("rename_target_id")
    user_id = update.effective_user.id
    db.rename_folder(folder_id, name, user_id=user_id)
    _reset(context)
    await update.message.reply_text(f"✅ Folder renamed to <b>{name}</b>", parse_mode="HTML",
                                    reply_markup=kb.main_menu())
    from handlers.folders import _show_folder_view
    folder = db.get_folder_for_user(folder_id, user_id)
    if folder:
        await _show_folder_view(update, context, folder.get("parent_id"), user_id, send_new=True)


async def _rename_file(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    file_id = context.user_data.get("rename_target_id")
    user_id = update.effective_user.id
    db.rename_file(file_id, name, user_id=user_id)
    _reset(context)
    await update.message.reply_text(f"✅ File renamed to <b>{name}</b>", parse_mode="HTML",
                                    reply_markup=kb.main_menu())


async def _do_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    user_id = update.effective_user.id
    _reset(context)

    import smart_organizer
    all_files = db.get_all_user_files(user_id, limit=300)
    results = smart_organizer.smart_search(query, all_files) if all_files else []
    smart_used = bool(results)

    if not results:
        results = db.search_files(user_id, query)
        smart_used = False

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

    badge = " (⚡ Smart Match)" if smart_used else ""
    text = f"🔍 Hasil pencarian: <b>{query}</b>{badge}\n{len(results)} file ditemukan"
    await update.message.reply_text(text, parse_mode="HTML",
                                    reply_markup=InlineKeyboardMarkup(buttons))
