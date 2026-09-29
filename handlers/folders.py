"""Folder navigation: list, open, create, rename, delete."""

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from utils import format_size


async def my_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply Keyboard: 📁 My Files — show root folders."""
    context.user_data["state"] = "idle"
    user_id = update.effective_user.id
    await _show_folder_view(update, context, parent_id=None, user_id=user_id, send_new=True)


async def open_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline callback f:{id} — open folder or root."""
    query = update.callback_query
    await query.answer()
    from handlers.files import cancel_auto_delete
    cancel_auto_delete(query.message.chat_id, query.message.message_id)
    folder_id = int(query.data.split(":")[1])
    user_id = query.from_user.id

    if folder_id == 0:
        await _show_root(query, user_id)
    else:
        await _show_folder_contents(query, context, folder_id, user_id)


async def _show_root(query, user_id: int):
    folders = db.get_folders(user_id, parent_id=None)
    if not folders:
        text = "📁 <b>My Files</b>\n\nBelum ada folder. Buat folder pertama!"
    else:
        text = f"📁 <b>My Files</b>\n\n{len(folders)} folder"
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.folder_list(folders))
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=kb.folder_list(folders))


async def _show_folder_contents(query, context, folder_id: int, user_id: int, page: int = 1):
    folder = db.get_folder(folder_id)
    if not folder:
        await query.edit_message_text("❌ Folder tidak ditemukan.")
        return

    path = db.get_folder_path(folder_id)
    breadcrumb = " > ".join(["🏠"] + [f["name"] for f in path])

    subfolders = db.get_folders(user_id, parent_id=folder_id)
    sort_pref = context.user_data.get("sort", "date_desc")
    active_filter = context.user_data.get(f"filter_{folder_id}", "all")

    files, total_filtered, total_pages = db.get_files(
        folder_id, page=page, sort=sort_pref, file_type=active_filter
    )
    raw_total_files = db.get_file_count(folder_id)

    total_size = sum(f.get("file_size", 0) for f in files)
    sub_count = len(subfolders)

    parts = []
    if sub_count:
        parts.append(f"{sub_count} subfolder")
    filter_label = f" ({active_filter})" if active_filter != "all" else ""
    parts.append(f"{total_filtered}{filter_label} file")
    if total_size:
        parts.append(format_size(total_size))
    stats = " • ".join(parts)

    is_starred = bool(folder.get("is_starred"))
    star_badge = "★ " if is_starred else ""

    text = (
        f"📂 <b>{star_badge}{folder['name']}</b>\n"
        f"📍 {breadcrumb}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 {stats}"
    )

    markup = kb.folder_contents(
        folder_id, files, subfolders, page, total_pages,
        is_starred=is_starred, active_filter=active_filter,
        has_any_files=(raw_total_files > 0)
    )
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def _show_folder_view(update_or_query, context, parent_id, user_id, send_new=False):
    """Shared helper to show a folder listing (root or subfolder contents)."""
    if parent_id:
        folder = db.get_folder(parent_id)
        if not folder:
            return
        path = db.get_folder_path(parent_id)
        breadcrumb = " > ".join(["🏠"] + [f["name"] for f in path])
        subfolders = db.get_folders(user_id, parent_id=parent_id)
        sort_pref = context.user_data.get("sort", "date_desc")
        active_filter = context.user_data.get(f"filter_{parent_id}", "all")

        files, total_filtered, total_pages = db.get_files(
            parent_id, page=1, sort=sort_pref, file_type=active_filter
        )
        raw_total_files = db.get_file_count(parent_id)
        total_size = sum(f.get("file_size", 0) for f in files)
        parts = []
        if subfolders:
            parts.append(f"{len(subfolders)} subfolder")
        filter_label = f" ({active_filter})" if active_filter != "all" else ""
        parts.append(f"{total_filtered}{filter_label} file")
        if total_size:
            parts.append(format_size(total_size))

        is_starred = bool(folder.get("is_starred"))
        star_badge = "★ " if is_starred else ""

        text = (
            f"📂 <b>{star_badge}{folder['name']}</b>\n"
            f"📍 {breadcrumb}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {' • '.join(parts)}"
        )
        markup = kb.folder_contents(
            parent_id, files, subfolders, 1, total_pages,
            is_starred=is_starred, active_filter=active_filter,
            has_any_files=(raw_total_files > 0)
        )
    else:
        folders = db.get_folders(user_id, parent_id=None)
        if not folders:
            text = "📁 <b>My Files</b>\n\nBelum ada folder. Buat folder pertama!"
        else:
            text = f"📁 <b>My Files</b>\n\n{len(folders)} folder"
        markup = kb.folder_list(folders)

    msg = update_or_query.message if hasattr(update_or_query, "message") else update_or_query
    if send_new:
        target = msg if hasattr(msg, "reply_text") else msg.message
        await target.reply_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await msg.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


async def create_folder_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """cf:{parent_id} — ask user for new folder name."""
    query = update.callback_query
    await query.answer()
    parent_id = int(query.data.split(":")[1])

    context.user_data["state"] = "creating_folder"
    context.user_data["creating_folder_parent"] = parent_id if parent_id else None

    await query.message.reply_text(
        "📁 Ketik nama folder baru:",
        reply_markup=kb.cancel_only(),
    )


async def rename_folder_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dr:{folder_id} — ask user for new folder name."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])

    context.user_data["state"] = "renaming_folder"
    context.user_data["rename_target_id"] = folder_id

    folder = db.get_folder(folder_id)
    name = folder["name"] if folder else "?"
    await query.message.reply_text(
        f"✏️ Rename folder <b>{name}</b>\nKetik nama baru:",
        parse_mode="HTML",
        reply_markup=kb.cancel_only(),
    )


async def delete_folder_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dx:{folder_id} — confirmation prompt."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])

    folder = db.get_folder(folder_id)
    if not folder:
        await query.edit_message_text("❌ Folder tidak ditemukan.")
        return

    file_count = db.get_file_count(folder_id)
    sub_count = db.get_subfolder_count(folder_id)

    text = (
        f"⚠️ Hapus folder <b>{folder['name']}</b>?\n\n"
        f"Isi: {file_count} file, {sub_count} subfolder\n"
        f"File akan masuk Trash."
    )
    await query.edit_message_text(text, parse_mode="HTML",
                                  reply_markup=kb.confirm_delete_folder(folder_id))


async def confirm_delete_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dxc:{folder_id} — actually delete."""
    query = update.callback_query
    await query.answer("Folder dihapus ✅")
    folder_id = int(query.data.split(":")[1])

    folder = db.get_folder(folder_id)
    parent_id = folder["parent_id"] if folder else None
    user_id = query.from_user.id

    db.delete_folder(folder_id)

    # Go back to parent
    if parent_id:
        await _show_folder_contents(query, context, parent_id, user_id)
    else:
        await _show_root(query, user_id)


async def file_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """fp:{folder_id}:{page} — paginate files in folder."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    folder_id = int(parts[1])
    page = int(parts[2])
    user_id = query.from_user.id
    await _show_folder_contents(query, context, folder_id, user_id, page=page)


async def toggle_star_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dst:{folder_id} — toggle starred status for folder."""
    query = update.callback_query
    folder_id = int(query.data.split(":")[1])
    is_starred = db.toggle_star_folder(folder_id)
    msg = "Ditambahkan ke Favorit ⭐" if is_starred else "Dihapus dari Favorit"
    await query.answer(msg)
    user_id = query.from_user.id
    await _show_folder_contents(query, context, folder_id, user_id)


async def set_folder_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ffilt:{folder_id}:{type} — set file type filter."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    folder_id = int(parts[1])
    filter_type = parts[2]

    context.user_data[f"filter_{folder_id}"] = filter_type
    user_id = query.from_user.id
    await _show_folder_contents(query, context, folder_id, user_id, page=1)


async def share_folder_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dsh:{folder_id} — generate or show public share link for folder."""
    query = update.callback_query
    await query.answer()
    folder_id = int(query.data.split(":")[1])

    folder = db.get_folder(folder_id)
    if not folder:
        await query.edit_message_text("❌ Folder tidak ditemukan.")
        return

    token = db.get_or_create_folder_share_token(folder_id)
    bot_me = await context.bot.get_me()
    share_link = f"https://t.me/{bot_me.username}?start=sd_{token}"

    text = (
        f"🔗 <b>Public Share Link</b>\n\n"
        f"Folder: 📁 <b>{folder['name']}</b>\n\n"
        f"Siapa saja yang memiliki link ini dapat membuka isi folder dan mengunduh filenya:\n\n"
        f"<code>{share_link}</code>\n\n"
        f"<i>Klik link di atas untuk menyalin.</i>"
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb.share_folder_view(folder_id))


async def revoke_folder_share(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """dsh_rev:{folder_id} — revoke share link."""
    query = update.callback_query
    folder_id = int(query.data.split(":")[1])
    db.revoke_folder_share_token(folder_id)
    await query.answer("Link dibatalkan ✅")
    user_id = query.from_user.id
    await _show_folder_contents(query, context, folder_id, user_id)
