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
    res = db.table("files").select("*, folders(name)").eq("share_token", token).eq("is_trashed", False).execute()
    return res.data[0] if res.data else None


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
    res = db.table("folders").select("*").eq("share_token", token).execute()
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
