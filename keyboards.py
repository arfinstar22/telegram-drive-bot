from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

from utils import file_emoji, format_size, truncate


# ── Reply Keyboards (bottom-screen persistent buttons) ──

def main_menu():
    return ReplyKeyboardMarkup(
        [["📁 My Files", "📤 Upload"],
         ["🔍 Search", "⚙️ Settings"]],
        resize_keyboard=True,
    )


def upload_mode():
    return ReplyKeyboardMarkup(
        [["✅ Done", "❌ Cancel"]],
        resize_keyboard=True,
    )


def cancel_only():
    return ReplyKeyboardMarkup(
        [["❌ Cancel"]],
        resize_keyboard=True,
    )


# ── Inline Keyboards (under messages) ──────────────────

def folder_list(folders: list[dict], parent_id: int | None = None):
    buttons = []
    for folder in folders:
        buttons.append([InlineKeyboardButton(
            f"📁 {folder['name']}",
            callback_data=f"f:{folder['id']}",
        )])

    parent_val = parent_id or 0
    buttons.append([InlineKeyboardButton("➕ New Folder", callback_data=f"cf:{parent_val}")])

    if parent_id:
        from database import get_folder
        folder = get_folder(parent_id)
        back_target = folder["parent_id"] if folder and folder.get("parent_id") else 0
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"f:{back_target}")])

    return InlineKeyboardMarkup(buttons)


def folder_contents(folder_id: int, files: list[dict], subfolders: list[dict],
                    page: int, total_pages: int):
    buttons = []

    for sf in subfolders:
        buttons.append([InlineKeyboardButton(
            f"📁 {sf['name']}",
            callback_data=f"f:{sf['id']}",
        )])

    for f in files:
        emoji = file_emoji(f["file_type"])
        size = format_size(f.get("file_size", 0))
        name = truncate(f["file_name"], 22)
        buttons.append([InlineKeyboardButton(
            f"{emoji} {name} — {size}",
            callback_data=f"fi:{f['id']}",
        )])

    if total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"fp:{folder_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"fp:{folder_id}:{page + 1}"))
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("📤 Upload", callback_data=f"up:{folder_id}"),
        InlineKeyboardButton("➕ Subfolder", callback_data=f"cf:{folder_id}"),
    ])
    buttons.append([
        InlineKeyboardButton("✏️ Rename", callback_data=f"dr:{folder_id}"),
        InlineKeyboardButton("🗑 Delete", callback_data=f"dx:{folder_id}"),
    ])

    from database import get_folder
    folder = get_folder(folder_id)
    back_target = folder["parent_id"] if folder and folder.get("parent_id") else 0
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"f:{back_target}")])

    return InlineKeyboardMarkup(buttons)


def file_actions(file_data: dict):
    file_id = file_data["id"]
    folder_id = file_data["folder_id"]
    buttons = [
        [InlineKeyboardButton("📥 Download", callback_data=f"fdl:{file_id}"),
         InlineKeyboardButton("📁 Move", callback_data=f"fm:{file_id}")],
        [InlineKeyboardButton("✏️ Rename", callback_data=f"fr:{file_id}"),
         InlineKeyboardButton("🗑 Delete", callback_data=f"fx:{file_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"fb:{folder_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def confirm_delete_folder(folder_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Yes, delete", callback_data=f"dxc:{folder_id}"),
         InlineKeyboardButton("❌ No", callback_data=f"f:{folder_id}")],
    ])


def confirm_delete_file(file_id: int, folder_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Yes, delete", callback_data=f"fxc:{file_id}"),
         InlineKeyboardButton("❌ No", callback_data=f"fb:{folder_id}")],
    ])


def folder_picker(folders: list[dict], callback_prefix: str):
    """Generic folder picker for move file / quick upload."""
    buttons = []
    for folder in folders:
        buttons.append([InlineKeyboardButton(
            f"📁 {folder['name']}",
            callback_data=f"{callback_prefix}{folder['id']}",
        )])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_pick")])
    return InlineKeyboardMarkup(buttons)


def trash_list(files: list[dict]):
    buttons = []
    for f in files[:20]:
        emoji = file_emoji(f["file_type"])
        name = truncate(f["file_name"], 20)
        buttons.append([
            InlineKeyboardButton(f"{emoji} {name}", callback_data="noop"),
            InlineKeyboardButton("♻️", callback_data=f"tr:{f['id']}"),
            InlineKeyboardButton("❌", callback_data=f"tp:{f['id']}"),
        ])
    if files:
        buttons.append([InlineKeyboardButton("🗑 Empty Trash", callback_data="te")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="sb")])
    return InlineKeyboardMarkup(buttons)


def confirm_empty_trash():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Yes, empty all", callback_data="tec"),
         InlineKeyboardButton("❌ No", callback_data="tv")],
    ])


def settings_menu(trash_count: int = 0):
    trash_label = f"🗑 Trash ({trash_count})" if trash_count else "🗑 Trash"
    buttons = [
        [InlineKeyboardButton("📊 Storage Info", callback_data="si")],
        [InlineKeyboardButton(trash_label, callback_data="tv")],
        [InlineKeyboardButton("📋 Sort: by Date ↓", callback_data="ss:cycle")],
    ]
    return InlineKeyboardMarkup(buttons)
