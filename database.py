from datetime import datetime, timezone
import secrets

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY, FILES_PER_PAGE

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Users ──────────────────────────────────────────────

def upsert_user(user_id: int, username: str | None = None, full_name: str | None = None):
    return db.table("users").upsert({
        "id": user_id,
        "username": username,
        "full_name": full_name,
        "last_active": _now(),
    }).execute()


def get_user(user_id: int):
    res = db.table("users").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None


def update_user(user_id: int, **kwargs):
    return db.table("users").update(kwargs).eq("id", user_id).execute()


# ── Folders ────────────────────────────────────────────

def create_folder(user_id: int, name: str, parent_id: int | None = None):
    data = {"user_id": user_id, "name": name}
    if parent_id:
        data["parent_id"] = parent_id
    res = db.table("folders").insert(data).execute()
    return res.data[0] if res.data else None


def get_or_create_inbox_folder(user_id: int) -> dict:
    """Get or automatically create default '📥 File Masuk' root folder."""
    upsert_user(user_id)
    res = (db.table("folders")
           .select("*")
           .eq("user_id", user_id)
           .is_("parent_id", "null")
           .eq("name", "📥 File Masuk")
           .execute())
    if res.data:
        return res.data[0]
    new_folder = db.table("folders").insert({
        "user_id": user_id,
        "name": "📥 File Masuk",
        "parent_id": None,
    }).execute()
    return new_folder.data[0]


def get_or_create_folder(user_id: int, name: str, parent_id: int | None = None) -> dict:
    """Get existing folder or create new folder with given name."""
    upsert_user(user_id)
    q = db.table("folders").select("*").eq("user_id", user_id).eq("name", name)
    if parent_id:
        q = q.eq("parent_id", parent_id)
    else:
        q = q.is_("parent_id", "null")
    res = q.execute()
    if res.data:
        return res.data[0]
    return create_folder(user_id, name, parent_id)



def get_folders(user_id: int, parent_id: int | None = None) -> list[dict]:
    q = db.table("folders").select("*").eq("user_id", user_id)
    if parent_id:
        q = q.eq("parent_id", parent_id)
    else:
        q = q.is_("parent_id", "null")
    return q.order("name").execute().data


def get_all_folders(user_id: int) -> list[dict]:
    return db.table("folders").select("*").eq("user_id", user_id).order("name").execute().data


def get_folder(folder_id: int) -> dict | None:
    res = db.table("folders").select("*").eq("id", folder_id).execute()
    return res.data[0] if res.data else None


def rename_folder(folder_id: int, name: str):
    return db.table("folders").update({"name": name, "updated_at": _now()}).eq("id", folder_id).execute()


def delete_folder(folder_id: int):
    db.table("files").update({
        "is_trashed": True,
        "trashed_at": _now(),
    }).eq("folder_id", folder_id).eq("is_trashed", False).execute()
    return db.table("folders").delete().eq("id", folder_id).execute()


def get_folder_path(folder_id: int) -> list[dict]:
    path = []
    current = get_folder(folder_id)
    while current:
        path.insert(0, current)
        current = get_folder(current["parent_id"]) if current.get("parent_id") else None
    return path


def get_subfolder_count(folder_id: int) -> int:
    res = db.table("folders").select("id", count="exact").eq("parent_id", folder_id).execute()
    return res.count or 0


# ── Files ──────────────────────────────────────────────

def save_file(user_id: int, folder_id: int, **file_data) -> dict | None:
    data = {"user_id": user_id, "folder_id": folder_id, **file_data}
    res = db.table("files").insert(data).execute()
    return res.data[0] if res.data else None


def get_files(folder_id: int, page: int = 1, per_page: int = FILES_PER_PAGE,
              sort: str = "date_desc", file_type: str | None = None) -> tuple[list[dict], int, int]:
    sort_map = {
        "date_desc": ("created_at", True),
        "date_asc":  ("created_at", False),
        "name_asc":  ("file_name", False),
        "name_desc": ("file_name", True),
        "size_desc": ("file_size", True),
        "size_asc":  ("file_size", False),
    }
    col, desc = sort_map.get(sort, sort_map["date_desc"])
    offset = (page - 1) * per_page

    q = (db.table("files")
         .select("*", count="exact")
         .eq("folder_id", folder_id)
         .eq("is_trashed", False))

    if file_type and file_type != "all":
        q = q.eq("file_type", file_type)

    res = (q.order(col, desc=desc)
           .range(offset, offset + per_page - 1)
           .execute())

    total = res.count or 0
    total_pages = max(1, (total + per_page - 1) // per_page)
    return res.data, total, total_pages


def get_file(file_id: int) -> dict | None:
    res = db.table("files").select("*").eq("id", file_id).execute()
    return res.data[0] if res.data else None


def get_file_count(folder_id: int) -> int:
    res = db.table("files").select("id", count="exact").eq("folder_id", folder_id).eq("is_trashed", False).execute()
    return res.count or 0


def rename_file(file_id: int, name: str):
    return db.table("files").update({"file_name": name, "updated_at": _now()}).eq("id", file_id).execute()


def move_file(file_id: int, folder_id: int):
    return db.table("files").update({"folder_id": folder_id, "updated_at": _now()}).eq("id", file_id).execute()


def trash_file(file_id: int):
    return db.table("files").update({"is_trashed": True, "trashed_at": _now()}).eq("id", file_id).execute()


def restore_file(file_id: int):
    return db.table("files").update({"is_trashed": False, "trashed_at": None}).eq("id", file_id).execute()


def permanent_delete(file_id: int):
    return db.table("files").delete().eq("id", file_id).execute()


def get_trash(user_id: int) -> list[dict]:
    return (db.table("files")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_trashed", True)
            .order("trashed_at", desc=True)
            .limit(50)
            .execute().data)


def empty_trash(user_id: int):
    return db.table("files").delete().eq("user_id", user_id).eq("is_trashed", True).execute()


def search_files(user_id: int, query: str) -> list[dict]:
    return (db.table("files")
            .select("*, folders(name)")
            .eq("user_id", user_id)
            .eq("is_trashed", False)
            .ilike("file_name", f"%{query}%")
            .order("created_at", desc=True)
            .limit(20)
            .execute().data)


def get_storage_info(user_id: int) -> dict:
    files_data = (db.table("files")
                  .select("file_size, file_type")
                  .eq("user_id", user_id)
                  .eq("is_trashed", False)
                  .execute().data)

    total_size = sum(f.get("file_size", 0) for f in files_data)
    by_type: dict[str, int] = {}
    for f in files_data:
        ft = f.get("file_type", "other")
        by_type[ft] = by_type.get(ft, 0) + 1

    folder_res = db.table("folders").select("id", count="exact").eq("user_id", user_id).execute()

    trash_res = db.table("files").select("id", count="exact").eq("user_id", user_id).eq("is_trashed", True).execute()

    return {
        "total_size": total_size,
        "total_files": len(files_data),
        "total_folders": folder_res.count or 0,
        "trash_count": trash_res.count or 0,
        "by_type": by_type,
    }


# ── Starred (Favorites) ────────────────────────────────

def toggle_star_file(file_id: int) -> bool:
    f = get_file(file_id)
    if not f:
        return False
    new_state = not bool(f.get("is_starred"))
    db.table("files").update({"is_starred": new_state, "updated_at": _now()}).eq("id", file_id).execute()
    return new_state


def toggle_star_folder(folder_id: int) -> bool:
    folder = get_folder(folder_id)
    if not folder:
        return False
    new_state = not bool(folder.get("is_starred"))
    db.table("folders").update({"is_starred": new_state, "updated_at": _now()}).eq("id", folder_id).execute()
    return new_state


def get_starred_folders(user_id: int) -> list[dict]:
    return (db.table("folders")
            .select("*")
            .eq("user_id", user_id)
            .eq("is_starred", True)
            .order("name")
            .execute().data)


def get_starred_files(user_id: int) -> list[dict]:
    return (db.table("files")
            .select("*, folders(name)")
            .eq("user_id", user_id)
            .eq("is_trashed", False)
            .eq("is_starred", True)
            .order("created_at", desc=True)
            .limit(50)
            .execute().data)


# ── Recent Files ───────────────────────────────────────

def get_recent_files(user_id: int, limit: int = 15) -> list[dict]:
    return (db.table("files")
            .select("*, folders(name)")
            .eq("user_id", user_id)
            .eq("is_trashed", False)
            .order("created_at", desc=True)
            .limit(limit)
            .execute().data)


# ── Batch Download ─────────────────────────────────────

def get_all_files_in_folder(folder_id: int) -> list[dict]:
    return (db.table("files")
            .select("*")
            .eq("folder_id", folder_id)
            .eq("is_trashed", False)
            .order("created_at", desc=False)
            .execute().data)


# ── Share Links ────────────────────────────────────────

def get_or_create_file_share_token(file_id: int) -> str | None:
    f = get_file(file_id)
    if not f:
        return None
    token = f.get("share_token")
    if token:
        return token
    token = secrets.token_urlsafe(8)
    db.table("files").update({"share_token": token, "updated_at": _now()}).eq("id", file_id).execute()
    return token


def revoke_file_share_token(file_id: int):
    return db.table("files").update({"share_token": None, "updated_at": _now()}).eq("id", file_id).execute()


def get_file_by_share_token(token: str) -> dict | None:
    res = db.table("files").select("*, folders(name)").ilike("share_token", f"{token}%").eq("is_trashed", False).execute()
    return res.data[0] if res.data else None


_UNSET = object()


def update_file_share_security(
    file_id: int,
    expires_at=_UNSET,
    pin=_UNSET,
    limit=_UNSET,
    clear_all: bool = False,
) -> str | None:
    from utils import parse_share_token, encode_share_token
    f = get_file(file_id)
    if not f:
        return None
    raw = f.get("share_token") or secrets.token_urlsafe(8)
    p = parse_share_token(raw)

    if clear_all:
        final_exp = None
        final_pin = None
        final_lim = None
        final_cnt = 0
    else:
        final_exp = p["expires_at"] if expires_at is _UNSET else expires_at
        final_pin = p["pin"] if pin is _UNSET else pin
        final_lim = p["limit"] if limit is _UNSET else limit
        final_cnt = p["count"]

    new_token_str = encode_share_token(p["token"], expires_at=final_exp, pin=final_pin, limit=final_lim, count=final_cnt)
    db.table("files").update({"share_token": new_token_str, "updated_at": _now()}).eq("id", file_id).execute()
    return p["token"]


def record_file_share_download(file_id: int) -> bool:
    from utils import parse_share_token, encode_share_token
    f = get_file(file_id)
    if not f or not f.get("share_token"):
        return False
    p = parse_share_token(f["share_token"])
    new_cnt = p["count"] + 1
    if p["limit"] is not None and new_cnt >= p["limit"]:
        revoke_file_share_token(file_id)
        return True
    new_token_str = encode_share_token(p["token"], expires_at=p["expires_at"], pin=p["pin"], limit=p["limit"], count=new_cnt)
    db.table("files").update({"share_token": new_token_str, "updated_at": _now()}).eq("id", file_id).execute()
    return True


def update_file_notes_and_tags(file_id: int, note: str | None = None, tags: list[str] | None = None) -> bool:
    from utils import parse_file_metadata, encode_file_metadata
    f = get_file(file_id)
    if not f:
        return False
    clean_mime, curr_note, curr_tags = parse_file_metadata(f.get("mime_type"))
    final_note = note if note is not None else curr_note
    final_tags = tags if tags is not None else curr_tags
    new_mime = encode_file_metadata(clean_mime, final_note, final_tags)
    db.table("files").update({"mime_type": new_mime, "updated_at": _now()}).eq("id", file_id).execute()
    return True


def get_or_create_folder_share_token(folder_id: int) -> str | None:
    folder = get_folder(folder_id)
    if not folder:
        return None
    token = folder.get("share_token")
    if token:
        return token
    token = secrets.token_urlsafe(8)
    db.table("folders").update({"share_token": token, "updated_at": _now()}).eq("id", folder_id).execute()
    return token


def revoke_folder_share_token(folder_id: int):
    return db.table("folders").update({"share_token": None, "updated_at": _now()}).eq("id", folder_id).execute()


def get_folder_by_share_token(token: str) -> dict | None:
    res = db.table("folders").select("*").ilike("share_token", f"{token}%").execute()
    return res.data[0] if res.data else None


def copy_file_to_user_folder(source_file: dict, target_user_id: int, target_folder_id: int) -> dict | None:
    data = {
        "user_id": target_user_id,
        "folder_id": target_folder_id,
        "file_name": source_file["file_name"],
        "file_id": source_file["file_id"],
        "file_unique_id": source_file["file_unique_id"],
        "file_type": source_file["file_type"],
        "file_size": source_file.get("file_size", 0),
        "mime_type": source_file.get("mime_type"),
        "thumbnail_file_id": source_file.get("thumbnail_file_id"),
    }
    res = db.table("files").insert(data).execute()
    return res.data[0] if res.data else None


# ── Smart Features (Duplicates & Health) ───────────────

def find_duplicate_file(user_id: int, file_unique_id: str) -> dict | None:
    """Find active file with the same Telegram file_unique_id."""
    res = (db.table("files")
           .select("*, folders(name)")
           .eq("user_id", user_id)
           .eq("file_unique_id", file_unique_id)
           .eq("is_trashed", False)
           .limit(1)
           .execute())
    return res.data[0] if res.data else None


def get_all_user_files(user_id: int, limit: int = 100) -> list[dict]:
    """Retrieve user files for semantic search and AI index."""
    return (db.table("files")
            .select("*, folders(name)")
            .eq("user_id", user_id)
            .eq("is_trashed", False)
            .order("created_at", desc=True)
            .limit(limit)
            .execute().data)


def get_storage_health(user_id: int) -> dict:
    """Calculate storage diagnostics: largest files, duplicates, and trash."""
    default = {
        "largest_files": [],
        "duplicate_groups": [],
        "total_duplicates": 0,
        "dup_wasted_size": 0,
        "trash_count": 0,
        "trash_size": 0,
    }
    try:
        # Top 5 largest files
        largest = (db.table("files")
                   .select("*, folders(name)")
                   .eq("user_id", user_id)
                   .eq("is_trashed", False)
                   .order("file_size", desc=True)
                   .limit(5)
                   .execute().data)

        # Find duplicates
        all_files = (db.table("files")
                     .select("id, file_name, file_size, file_unique_id, folder_id, folders(name)")
                     .eq("user_id", user_id)
                     .eq("is_trashed", False)
                     .execute().data)

        seen: dict[str, list[dict]] = {}
        for f in all_files:
            uid = f.get("file_unique_id")
            if uid:
                seen.setdefault(uid, []).append(f)

        dup_groups = [flist for flist in seen.values() if len(flist) > 1]
        extra_dups = sum(len(d) - 1 for d in dup_groups)
        dup_wasted_size = sum(sum(item.get("file_size", 0) for item in group[1:]) for group in dup_groups)

        # Trash stats
        trash_items = (db.table("files")
                       .select("file_size")
                       .eq("user_id", user_id)
                       .eq("is_trashed", True)
                       .execute().data)
        trash_size = sum(f.get("file_size", 0) for f in trash_items)

        return {
            "largest_files": largest,
            "duplicate_groups": dup_groups,
            "total_duplicates": extra_dups,
            "dup_wasted_size": dup_wasted_size,
            "trash_count": len(trash_items),
            "trash_size": trash_size,
        }
    except Exception as exc:
        log.error("Failed to fetch storage health: %s", exc)
        return default



def clean_duplicate_files(user_id: int) -> int:
    """Move all redundant duplicate files to trash, keeping earliest copy."""
    health = get_storage_health(user_id)
    trashed_count = 0
    for group in health["duplicate_groups"]:
        # Keep group[0], trash the rest
        for extra in group[1:]:
            trash_file(extra["id"])
            trashed_count += 1
    return trashed_count


# ── Storage Reset & Account Recovery ───────────────────

def reset_user_storage(user_id: int):
    """Permanently delete all files and folders of user, recreate default inbox."""
    # Delete all files belonging to user
    db.table("files").delete().eq("user_id", user_id).execute()
    # Delete all folders belonging to user
    db.table("folders").delete().eq("user_id", user_id).execute()
    # Re-create clean inbox folder
    return get_or_create_inbox_folder(user_id)


def find_recoverable_account(new_user_id: int, username: str | None = None) -> dict | None:
    """Find previous account with same username but different user_id."""
    if not username:
        return None
    clean = username.lstrip("@").strip().lower()
    if not clean:
        return None

    try:
        res = db.table("users").select("*").ilike("username", clean).neq("id", new_user_id).execute()
        candidates = res.data or []
        for cand in candidates:
            old_id = cand["id"]
            f_count = db.table("files").select("id", count="exact").eq("user_id", old_id).execute().count or 0
            d_count = db.table("folders").select("id", count="exact").eq("user_id", old_id).execute().count or 0
            if f_count > 0 or d_count > 0:
                return {
                    "old_user_id": old_id,
                    "old_username": cand.get("username"),
                    "old_full_name": cand.get("full_name"),
                    "total_files": f_count,
                    "total_folders": d_count,
                }
    except Exception as exc:
        log.error("Failed to query recoverable account: %s", exc)
    return None


def transfer_user_data(old_user_id: int, new_user_id: int) -> dict:
    """Transfer all folders and files from old_user_id to new_user_id."""
    upsert_user(new_user_id)
    # Transfer all folders
    db.table("folders").update({"user_id": new_user_id}).eq("user_id", old_user_id).execute()
    # Transfer all files
    db.table("files").update({"user_id": new_user_id}).eq("user_id", old_user_id).execute()
    # Mark old user record so username won't conflict
    try:
        old_u = get_user(old_user_id)
        if old_u and old_u.get("username"):
            update_user(old_user_id, username=f"{old_u['username']}_transferred")
    except Exception:
        pass
    # Ensure inbox exists
    get_or_create_inbox_folder(new_user_id)
    return get_storage_info(new_user_id)

