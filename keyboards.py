from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, WebAppInfo

from config import WEBAPP_URL
from utils import file_emoji, format_size, truncate


# ── Reply Keyboards (bottom-screen persistent buttons) ──

def main_menu(lang: str = "id"):
    webapp_label = "📱 Open WebApp Drive" if lang == "en" else "📱 Buka WebApp Drive"
    webapp_btn = KeyboardButton(webapp_label, web_app=WebAppInfo(url=WEBAPP_URL))
    if lang == "en":
        return ReplyKeyboardMarkup(
            [[webapp_btn],
             ["📁 My Files", "📤 Upload"],
             ["⭐ Starred", "🕒 Recent"],
             ["🔍 Search", "⚙️ Settings"],
             ["🏠 Home"]],
            resize_keyboard=True,
        )
    return ReplyKeyboardMarkup(
        [[webapp_btn],
         ["📁 File Saya", "📤 Upload"],
         ["⭐ Favorit", "🕒 Terbaru"],
         ["🔍 Cari", "⚙️ Pengaturan"],
         ["🏠 Beranda"]],
        resize_keyboard=True,
    )


def upload_mode(lang: str = "id"):
    if lang == "en":
        return ReplyKeyboardMarkup(
            [["✅ Done", "❌ Cancel"],
             ["🏠 Home"]],
            resize_keyboard=True,
        )
    return ReplyKeyboardMarkup(
        [["✅ Selesai", "❌ Batal"],
         ["🏠 Beranda"]],
        resize_keyboard=True,
    )


def cancel_only(lang: str = "id"):
    if lang == "en":
        return ReplyKeyboardMarkup(
            [["❌ Cancel", "🏠 Home"]],
            resize_keyboard=True,
        )
    return ReplyKeyboardMarkup(
        [["❌ Batal", "🏠 Beranda"]],
        resize_keyboard=True,
    )


def language_picker():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇩 Bahasa Indonesia", callback_data="set_lang:id"),
         InlineKeyboardButton("🇬🇧 English", callback_data="set_lang:en")],
    ])



# ── Inline Keyboards (under messages) ──────────────────

def folder_list(folders: list[dict], parent_id: int | None = None):
    buttons = []
    for folder in folders:
        star_icon = "★ " if folder.get("is_starred") else ""
        buttons.append([InlineKeyboardButton(
            f"📁 {star_icon}{folder['name']}",
            callback_data=f"f:{folder['id']}",
        )])

    parent_val = parent_id or 0
    buttons.append([InlineKeyboardButton("➕ New Folder", callback_data=f"cf:{parent_val}")])

    if parent_id:
        from database import get_folder
        folder = get_folder(parent_id)
        back_target = folder["parent_id"] if folder and folder.get("parent_id") else 0
        buttons.append([
            InlineKeyboardButton("⬅️ Back", callback_data=f"f:{back_target}"),
            InlineKeyboardButton("🏠 Beranda", callback_data="home_nav"),
        ])
    else:
        buttons.append([InlineKeyboardButton("🏠 Beranda", callback_data="home_nav")])

    return InlineKeyboardMarkup(buttons)


def folder_contents(folder_id: int, files: list[dict], subfolders: list[dict],
                    page: int, total_pages: int, is_starred: bool = False,
                    active_filter: str = "all", has_any_files: bool = True):
    buttons = []

    # Subfolders
    for sf in subfolders:
        star_icon = "★ " if sf.get("is_starred") else ""
        buttons.append([InlineKeyboardButton(
            f"📁 {star_icon}{sf['name']}",
            callback_data=f"f:{sf['id']}",
        )])

    # Filter bar if folder has any files
    if has_any_files:
        filter_options = [
            ("all", "Semua"),
            ("photo", "🖼️"),
            ("video", "🎥"),
            ("document", "📄"),
            ("audio", "🎵"),
        ]
        frow = []
        for key, label in filter_options:
            display = f"•{label}•" if active_filter == key else label
            frow.append(InlineKeyboardButton(display, callback_data=f"ffilt:{folder_id}:{key}"))
        buttons.append(frow)

    # Files
    for f in files:
        emoji = file_emoji(f["file_type"])
        star_icon = "★ " if f.get("is_starred") else ""
        size = format_size(f.get("file_size", 0))
        name = truncate(f["file_name"], 20)
        buttons.append([InlineKeyboardButton(
            f"{star_icon}{emoji} {name} — {size}",
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

    # Row 1: Upload & Subfolder
    buttons.append([
        InlineKeyboardButton("📤 Upload", callback_data=f"up:{folder_id}"),
        InlineKeyboardButton("➕ Subfolder", callback_data=f"cf:{folder_id}"),
    ])

    # Row 2: Star Folder & Share Folder
    star_btn_text = "★ Starred" if is_starred else "⭐ Star Folder"
    buttons.append([
        InlineKeyboardButton(star_btn_text, callback_data=f"dst:{folder_id}"),
        InlineKeyboardButton("🔗 Share Folder", callback_data=f"dsh:{folder_id}"),
    ])

    # Row 3: Batch Download & Unduh ZIP & Rename
    row_actions = []
    if has_any_files:
        row_actions.append(InlineKeyboardButton("📥 Download All", callback_data=f"dlall:{folder_id}"))
        row_actions.append(InlineKeyboardButton("📦 Unduh ZIP", callback_data=f"dlzip:{folder_id}"))
    row_actions.append(InlineKeyboardButton("✏️ Rename", callback_data=f"dr:{folder_id}"))
    buttons.append(row_actions)

    # Row 4: WebApp, Delete, Back & Home
    from database import get_folder
    folder = get_folder(folder_id)
    back_target = folder["parent_id"] if folder and folder.get("parent_id") else 0
    buttons.append([
        InlineKeyboardButton("📱 Buka di WebApp Drive", web_app=WebAppInfo(url=f"{WEBAPP_URL}?folder_id={folder_id}")),
    ])
    buttons.append([
        InlineKeyboardButton("🗑 Delete", callback_data=f"dx:{folder_id}"),
        InlineKeyboardButton("⬅️ Back", callback_data=f"f:{back_target}"),
        InlineKeyboardButton("🏠 Beranda", callback_data="home_nav"),
    ])

    return InlineKeyboardMarkup(buttons)


def file_actions(file_data: dict):
    file_id = file_data["id"]
    folder_id = file_data["folder_id"]
    is_starred = file_data.get("is_starred", False)
    star_label = "★ Starred" if is_starred else "⭐ Star"

    buttons = [
        [InlineKeyboardButton("📥 Download", callback_data=f"fdl:{file_id}"),
         InlineKeyboardButton(star_label, callback_data=f"fst:{file_id}")],
        [InlineKeyboardButton("📁 Auto Folder", callback_data=f"smf:{file_id}"),
         InlineKeyboardButton("✨ Smart Rename", callback_data=f"smr:{file_id}")],
        [InlineKeyboardButton("🏷 Tag & Catatan", callback_data=f"ftag:{file_id}"),
         InlineKeyboardButton("🔗 Share Link", callback_data=f"fsh:{file_id}")],
        [InlineKeyboardButton("📁 Move", callback_data=f"fm:{file_id}"),
         InlineKeyboardButton("✏️ Rename", callback_data=f"fr:{file_id}")],
        [InlineKeyboardButton("🗑 Delete", callback_data=f"fx:{file_id}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"fb:{folder_id}"),
         InlineKeyboardButton("🏠 Beranda", callback_data="home_nav")],
    ]
    return InlineKeyboardMarkup(buttons)


def starred_list(folders: list[dict], files: list[dict]):
    buttons = []
    for folder in folders:
        buttons.append([InlineKeyboardButton(f"📁 ★ {folder['name']}", callback_data=f"f:{folder['id']}")])
    for f in files:
        emoji = file_emoji(f["file_type"])
        size = format_size(f.get("file_size", 0))
        name = truncate(f["file_name"], 20)
        buttons.append([InlineKeyboardButton(f"★ {emoji} {name} — {size}", callback_data=f"fi:{f['id']}")])
    buttons.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="home_nav")])
    return InlineKeyboardMarkup(buttons)


def recent_list(files: list[dict]):
    buttons = []
    for f in files:
        emoji = file_emoji(f["file_type"])
        size = format_size(f.get("file_size", 0))
        name = truncate(f["file_name"], 18)
        folder_info = f" ({truncate(f['folders']['name'], 10)})" if f.get("folders") and f["folders"].get("name") else ""
        buttons.append([InlineKeyboardButton(
            f"{emoji} {name}{folder_info} — {size}",
            callback_data=f"fi:{f['id']}",
        )])
    buttons.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="home_nav")])
    return InlineKeyboardMarkup(buttons)


def share_file_view(file_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 Keamanan & Expired", callback_data=f"fsh_sec:{file_id}")],
        [InlineKeyboardButton("❌ Revoke Link", callback_data=f"fsh_rev:{file_id}"),
         InlineKeyboardButton("⬅️ Back to File", callback_data=f"fi:{file_id}")],
    ])


def share_security_menu(file_id: int, current_sec: dict):
    pin_label = f"🔑 PIN: {current_sec['pin']} (Ubah)" if current_sec.get("pin") else "🔑 Pasang PIN 4-Digit"
    exp_status = "Aktif" if current_sec.get("expires_at") else "Mati"
    burn_status = "Aktif" if current_sec.get("limit") == 1 else "Mati"

    buttons = [
        [InlineKeyboardButton(pin_label, callback_data=f"fsh_pin:{file_id}")],
        [InlineKeyboardButton(f"⏳ Exp: 24 Jam ({exp_status})", callback_data=f"fsh_exp:{file_id}:24h"),
         InlineKeyboardButton(f"⏳ Exp: 7 Hari", callback_data=f"fsh_exp:{file_id}:7d")],
        [InlineKeyboardButton(f"🔥 1x Unduh / Burn ({burn_status})", callback_data=f"fsh_burn:{file_id}")],
        [InlineKeyboardButton("🔓 Hapus Semua Proteksi", callback_data=f"fsh_clear:{file_id}")],
        [InlineKeyboardButton("⬅️ Kembali ke Share Link", callback_data=f"fsh:{file_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def file_tag_view(file_id: int, folder_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Ubah Catatan & Tag", callback_data=f"ftag_edit:{file_id}")],
        [InlineKeyboardButton("🗑 Hapus Catatan/Tag", callback_data=f"ftag_del:{file_id}")],
        [InlineKeyboardButton("⬅️ Kembali ke File", callback_data=f"fi:{file_id}")],
    ])


def share_folder_view(folder_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Revoke Link", callback_data=f"dsh_rev:{folder_id}")],
        [InlineKeyboardButton("⬅️ Back to Folder", callback_data=f"f:{folder_id}")],
    ])


def public_shared_file(file_id: int, can_save: bool = True):
    buttons = [
        [InlineKeyboardButton("📥 Download File", callback_data=f"pdl:{file_id}")],
    ]
    if can_save:
        buttons.append([InlineKeyboardButton("💾 Simpan ke Drive Saya", callback_data=f"psave:{file_id}")])
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


def settings_menu(trash_count: int = 0, lang: str = "id"):
    if lang == "en":
        trash_label = f"🗑 Trash ({trash_count})" if trash_count else "🗑 Trash"
        buttons = [
            [InlineKeyboardButton("📊 Storage Info", callback_data="si"),
             InlineKeyboardButton("🩺 Storage Health", callback_data="sh:menu")],
            [InlineKeyboardButton(trash_label, callback_data="tv"),
             InlineKeyboardButton("📋 Sort Order", callback_data="ss:cycle")],
            [InlineKeyboardButton("🔑 Account Recovery", callback_data="rec:menu"),
             InlineKeyboardButton("⚠️ Reset Storage", callback_data="rst:prompt")],
            [InlineKeyboardButton("🌐 Language: 🇬🇧 English", callback_data="set_lang:prompt")],
            [InlineKeyboardButton("🏠 Home", callback_data="home_nav")],
        ]
    else:
        trash_label = f"🗑 Sampah ({trash_count})" if trash_count else "🗑 Sampah"
        buttons = [
            [InlineKeyboardButton("📊 Info Penyimpanan", callback_data="si"),
             InlineKeyboardButton("🩺 Kesehatan Drive", callback_data="sh:menu")],
            [InlineKeyboardButton(trash_label, callback_data="tv"),
             InlineKeyboardButton("📋 Urutan Sortir", callback_data="ss:cycle")],
            [InlineKeyboardButton("🔑 Pemulihan Akun", callback_data="rec:menu"),
             InlineKeyboardButton("⚠️ Reset Storage", callback_data="rst:prompt")],
            [InlineKeyboardButton("🌐 Bahasa: 🇮🇩 Indonesia", callback_data="set_lang:prompt")],
            [InlineKeyboardButton("🏠 Beranda", callback_data="home_nav")],
        ]
    return InlineKeyboardMarkup(buttons)



def account_recovery_detected(old_user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Pulihkan Data Akun Lama", callback_data=f"rec:link:{old_user_id}")],
        [InlineKeyboardButton("✨ Buat Storage Baru", callback_data="rec:ignore")],
    ])



def storage_health_view(health: dict):
    buttons = []
    for f in health.get("largest_files", [])[:3]:
        emoji = file_emoji(f["file_type"])
        size = format_size(f.get("file_size", 0))
        name = truncate(f["file_name"], 16)
        buttons.append([InlineKeyboardButton(f"{emoji} {name} ({size})", callback_data=f"fi:{f['id']}")])

    if health.get("total_duplicates", 0) > 0:
        buttons.append([InlineKeyboardButton(
            f"🧹 Bersihkan {health['total_duplicates']} Duplikat ({format_size(health['dup_wasted_size'])})",
            callback_data="sh:clean_dup"
        )])

    if health.get("trash_count", 0) > 0:
        buttons.append([InlineKeyboardButton(
            f"🗑 Kosongkan Trash ({format_size(health['trash_size'])})",
            callback_data="te"
        )])

    buttons.append([
        InlineKeyboardButton("⬅️ Back", callback_data="sb"),
        InlineKeyboardButton("🏠 Beranda", callback_data="home_nav"),
    ])
    return InlineKeyboardMarkup(buttons)


def duplicate_warning_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Tetap Simpan", callback_data="dup_force"),
         InlineKeyboardButton("❌ Lewati (Jangan Simpan)", callback_data="dup_skip")],
    ])


def smart_folder_confirm(file_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Ya, Pindahkan", callback_data=f"smf_ok:{file_id}")],
        [InlineKeyboardButton("⬅️ Batal", callback_data=f"fi:{file_id}")],
    ])


def apply_rename_keyboard(file_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Terapkan Nama Ini", callback_data=f"smr_ok:{file_id}")],
        [InlineKeyboardButton("✏️ Ketik Manual", callback_data=f"fr:{file_id}")],
        [InlineKeyboardButton("⬅️ Batal", callback_data=f"fi:{file_id}")],
    ])


def single_upload_keyboard(folder_id: int, file_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 Buka Folder", callback_data=f"f:{folder_id}"),
         InlineKeyboardButton("📁 Pindahkan", callback_data=f"fm:{file_id}")],
        [InlineKeyboardButton("🗑 Bersihkan Notif", callback_data="msg_del")],
    ])


def batch_upload_keyboard(folder_id: int, batch_id: str | None = None, can_smart_sort: bool = False):
    buttons = [
        [InlineKeyboardButton("📂 Buka Folder", callback_data=f"f:{folder_id}")],
    ]
    if can_smart_sort and batch_id:
        buttons.append([InlineKeyboardButton("🗂 Rapikan Otomatis (Smart Sort)", callback_data=f"bsm:{batch_id}")])
    buttons.append([InlineKeyboardButton("🗑 Bersihkan Notif", callback_data="msg_del")])
    return InlineKeyboardMarkup(buttons)

