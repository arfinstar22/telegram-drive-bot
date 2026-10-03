"""Database abstraction layer for Darfin Storage using Supabase (PostgreSQL).

All operations on files and folders enforce object ownership (user_id).
Public share operations use exact-match token lookups and centralized validation.
"""

from datetime import datetime, timezone
import hashlib
import logging
import secrets
import time
from typing import Optional

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY, FILES_PER_PAGE
from utils import (
    sanitize_filename,
    hash_pin,
    verify_pin,
    parse_share_token,
    encode_share_token,
)

log = logging.getLogger(__name__)

db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Ephemeral in-memory store for secure one-time account recovery codes
# Format: {code_hash: {"user_id": int, "expires_at": int}}
_RECOVERY_CODES: dict[str, dict] = {}

# In-memory user files cache: (user_id, is_trashed) -> (timestamp, list_of_files)
_USER_FILES_CACHE: dict[tuple[int, bool], tuple[float, list[dict]]] = {}
_USER_FILES_CACHE_TTL = 60.0  # 60 seconds


def invalidate_user_files_cache(user_id: int | None = None) -> None:
    """Invalidate in-memory user files cache."""
    global _USER_FILES_CACHE
    if user_id is None:
        _USER_FILES_CACHE.clear()
    else:
        for k in list(_USER_FILES_CACHE.keys()):
            if k[0] == user_id:
                _USER_FILES_CACHE.pop(k, None)


def is_user_files_cached(user_id: int, is_trashed: bool = False) -> bool:
    """Check if full user file catalog is currently cached and valid."""
    cache_key = (user_id, is_trashed)
    if cache_key in _USER_FILES_CACHE:
        cached_time, _ = _USER_FILES_CACHE[cache_key]
        return (time.time() - cached_time) < _USER_FILES_CACHE_TTL
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Users ──────────────────────────────────────────────

def upsert_user(user_id: int, username: str | None = None, full_name: str | None = None):
    try:
        payload = {
            "id": user_id,
            "last_active": _now(),
        }
        if username is not None:
            clean_u = username.lstrip("@").strip() if isinstance(username, str) else username
            if clean_u:
                payload["username"] = clean_u
        if full_name is not None:
            clean_fn = full_name.strip() if isinstance(full_name, str) else full_name
            if clean_fn:
                payload["full_name"] = clean_fn
        return db.table("users").upsert(payload).execute()
    except Exception as exc:
        log.error("Failed to upsert user %s: %s", user_id, exc)
        return None


def get_user(user_id: int) -> dict | None:
    try:
        res = db.table("users").select("*").eq("id", user_id).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to get user %s: %s", user_id, exc)
        return None


def update_user(user_id: int, **kwargs):
    try:
        return db.table("users").update(kwargs).eq("id", user_id).execute()
    except Exception as exc:
        log.error("Failed to update user %s: %s", user_id, exc)
        return None


# ── Folders (Ownership Enforced) ───────────────────────

def get_folder(folder_id: int, user_id: int | None = None) -> dict | None:
    """Fetch folder by ID, optionally validating owner user_id."""
    try:
        q = db.table("folders").select("*").eq("id", folder_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to get folder %s: %s", folder_id, exc)
        return None


def get_folders(user_id: int, parent_id: int | None = None) -> list[dict]:
    try:
        q = db.table("folders").select("*").eq("user_id", user_id)
        if parent_id is not None:
            q = q.eq("parent_id", parent_id)
        else:
            q = q.is_("parent_id", "null")
        return q.order("name").execute().data or []
    except Exception as exc:
        log.error("Failed to get folders for user %s: %s", user_id, exc)
        return []


def get_all_folders(user_id: int) -> list[dict]:
    try:
        return db.table("folders").select("*").eq("user_id", user_id).order("name").execute().data or []
    except Exception as exc:
        log.error("Failed to get all folders for user %s: %s", user_id, exc)
        return []


def get_or_create_inbox_folder(user_id: int) -> dict:
    """Get or automatically create default '📥 File Masuk' root folder for user."""
    upsert_user(user_id)
    try:
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
    except Exception as exc:
        log.error("Failed to get/create inbox for user %s: %s", user_id, exc)
        # Fallback query
        res = db.table("folders").select("*").eq("user_id", user_id).limit(1).execute()
        return res.data[0] if res.data else {"id": 0, "name": "Inbox", "user_id": user_id}


def check_circular_folder_hierarchy(folder_id: int, target_parent_id: int | None, user_id: int) -> bool:
    """Returns True if target_parent_id is a valid, cycle-free parent for folder_id."""
    if target_parent_id is None:
        return True
    if folder_id == target_parent_id:
        return False

    current_id = target_parent_id
    visited = {folder_id}
    while current_id is not None:
        if current_id in visited:
            return False
        visited.add(current_id)
        parent = get_folder(current_id, user_id=user_id)
        if not parent:
            return False
        current_id = parent.get("parent_id")
    return True


def create_folder(user_id: int, name: str, parent_id: int | None = None) -> dict | None:
    """Create new folder. Validates that parent_id belongs to the same user."""
    clean_name = sanitize_filename(name).strip() or "Folder Baru"
    upsert_user(user_id)

    # Cross-user parent guard
    if parent_id is not None:
        parent = get_folder(parent_id, user_id=user_id)
        if not parent:
            log.warning("Cross-user or non-existent parent folder %s for user %s", parent_id, user_id)
            return None

    data = {"user_id": user_id, "name": clean_name}
    if parent_id is not None:
        data["parent_id"] = parent_id

    try:
        res = db.table("folders").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to create folder for user %s: %s", user_id, exc)
        return None


def get_or_create_folder(user_id: int, name: str, parent_id: int | None = None) -> dict:
    clean_name = sanitize_filename(name).strip() or "Folder"
    upsert_user(user_id)
    try:
        q = db.table("folders").select("*").eq("user_id", user_id).eq("name", clean_name)
        if parent_id is not None:
            q = q.eq("parent_id", parent_id)
        else:
            q = q.is_("parent_id", "null")
        res = q.execute()
        if res.data:
            return res.data[0]
        created = create_folder(user_id, clean_name, parent_id)
        if created:
            return created
    except Exception as exc:
        log.error("Failed in get_or_create_folder: %s", exc)
    return get_or_create_inbox_folder(user_id)


def rename_folder(folder_id: int, name: str, user_id: int | None = None) -> bool:
    """Rename folder with ownership verification."""
    clean_name = sanitize_filename(name).strip()
    if not clean_name:
        return False
    try:
        q = db.table("folders").update({"name": clean_name, "updated_at": _now()}).eq("id", folder_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to rename folder %s: %s", folder_id, exc)
        return False


def move_folder(folder_id: int, target_parent_id: int | None, user_id: int | None = None) -> bool:
    """Move folder with ownership verification and circular hierarchy prevention."""
    folder = get_folder(folder_id, user_id=user_id)
    if not folder:
        return False
    owner_id = folder["user_id"]

    if target_parent_id == folder_id:
        log.warning("Attempted to move folder %s into itself", folder_id)
        return False

    if target_parent_id is not None:
        target = get_folder(target_parent_id, user_id=owner_id)
        if not target:
            log.warning("Target folder %s does not exist or belongs to different user", target_parent_id)
            return False

        # Circular check: walk up from target_parent_id
        curr = target
        visited = set()
        while curr:
            if curr["id"] == folder_id:
                log.warning("Circular hierarchy detected moving folder %s into %s", folder_id, target_parent_id)
                return False
            visited.add(curr["id"])
            pid = curr.get("parent_id")
            if not pid or pid in visited:
                break
            curr = get_folder(pid, user_id=owner_id)

    try:
        q = db.table("folders").update({"parent_id": target_parent_id, "updated_at": _now()}).eq("id", folder_id).eq("user_id", owner_id)
        res = q.execute()
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to move folder %s: %s", folder_id, exc)
        return False


def get_file_for_user(file_id: int, user_id: int) -> dict | None:
    return get_file(file_id, user_id=user_id)


def get_folder_for_user(folder_id: int, user_id: int) -> dict | None:
    return get_folder(folder_id, user_id=user_id)


def move_folder_for_user(folder_id: int, user_id: int, target_parent_id: int | None) -> bool:
    return move_folder(folder_id, target_parent_id, user_id=user_id)


def rename_file_for_user(file_id: int, user_id: int, new_name: str) -> bool:
    return rename_file(file_id, new_name, user_id=user_id)


def move_file_for_user(file_id: int, user_id: int, folder_id: int) -> bool:
    return move_file(file_id, folder_id, user_id=user_id)


def trash_file_for_user(file_id: int, user_id: int) -> bool:
    return trash_file(file_id, user_id=user_id)


def restore_file_for_user(file_id: int, user_id: int) -> bool:
    return restore_file(file_id, user_id=user_id)


def delete_folder(folder_id: int, user_id: int | None = None) -> bool:
    """Delete folder with ownership verification and safe file migration to inbox."""
    folder = get_folder(folder_id, user_id=user_id)
    if not folder:
        return False

    owner_id = folder["user_id"]
    try:
        inbox = get_or_create_inbox_folder(owner_id)
        inbox_id = inbox["id"] if inbox and inbox["id"] != folder_id else None

        # Move child files to trash or inbox, scoped to owner
        update_payload = {
            "is_trashed": True,
            "trashed_at": _now(),
        }
        if inbox_id:
            update_payload["folder_id"] = inbox_id
        db.table("files").update(update_payload).eq("folder_id", folder_id).eq("user_id", owner_id).execute()

        # Re-parent subfolders to parent of deleted folder, scoped to owner
        db.table("folders").update({"parent_id": folder.get("parent_id")}).eq("parent_id", folder_id).eq("user_id", owner_id).execute()

        # Delete the folder itself
        db.table("folders").delete().eq("id", folder_id).eq("user_id", owner_id).execute()
        return True
    except Exception as exc:
        log.error("Failed to delete folder %s: %s", folder_id, exc)
        return False


def get_folder_path(folder_id: int, user_id: int | None = None) -> list[dict]:
    path = []
    current = get_folder(folder_id, user_id=user_id)
    visited = set()
    while current and current["id"] not in visited:
        visited.add(current["id"])
        path.insert(0, current)
        pid = current.get("parent_id")
        current = get_folder(pid, user_id=user_id) if pid else None
    return path


def get_subfolder_count(folder_id: int, user_id: int | None = None) -> int:
    try:
        q = db.table("folders").select("id", count="exact").eq("parent_id", folder_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return res.count or 0
    except Exception as exc:
        log.error("Failed to get subfolder count for %s: %s", folder_id, exc)
        return 0


# ── Files (Ownership Enforced) ─────────────────────────

def save_file(user_id: int, folder_id: int, **file_data) -> dict | None:
    """Save file to database. Validates destination folder ownership."""
    folder = get_folder(folder_id, user_id=user_id)
    if not folder:
        inbox = get_or_create_inbox_folder(user_id)
        folder_id = inbox["id"]

    clean_file_name = sanitize_filename(file_data.get("file_name", "file"))
    file_data["file_name"] = clean_file_name

    data = {"user_id": user_id, "folder_id": folder_id, **file_data}
    try:
        res = db.table("files").insert(data).execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to save file for user %s: %s", user_id, exc)
        return None


def get_file(file_id: int, user_id: int | None = None) -> dict | None:
    """Fetch file by ID, optionally validating ownership."""
    try:
        q = db.table("files").select("*").eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to get file %s: %s", file_id, exc)
        return None


def get_file_count(folder_id: int, user_id: int | None = None) -> int:
    try:
        q = (db.table("files")
             .select("id", count="exact")
             .eq("folder_id", folder_id)
             .eq("is_trashed", False))
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return res.count or 0
    except Exception as exc:
        log.error("Failed to get file count for folder %s: %s", folder_id, exc)
        return 0


def get_files(
    folder_id: int,
    page: int = 1,
    per_page: int = FILES_PER_PAGE,
    sort: str = "date_desc",
    file_type: str | None = None,
    user_id: int | None = None,
) -> tuple[list[dict], int, int]:
    sort_map = {
        "date_desc": ("created_at", True),
        "date_asc": ("created_at", False),
        "name_asc": ("file_name", False),
        "name_desc": ("file_name", True),
        "size_desc": ("file_size", True),
        "size_asc": ("file_size", False),
    }
    col, desc = sort_map.get(sort, sort_map["date_desc"])
    offset = max(0, (page - 1) * per_page)

    try:
        q = (
            db.table("files")
            .select("*", count="exact")
            .eq("folder_id", folder_id)
            .eq("is_trashed", False)
        )
        if user_id is not None:
            q = q.eq("user_id", user_id)

        if file_type and file_type != "all":
            q = q.eq("file_type", file_type)

        res = q.order(col, desc=desc).range(offset, offset + per_page - 1).execute()
        total = res.count or 0
        total_pages = max(1, (total + per_page - 1) // per_page)
        return res.data or [], total, total_pages
    except Exception as exc:
        log.error("Failed to get files in folder %s: %s", folder_id, exc)
        return [], 0, 1


def rename_file(file_id: int, name: str, user_id: int | None = None) -> bool:
    clean_name = sanitize_filename(name).strip()
    if not clean_name:
        return False
    try:
        q = db.table("files").update({"file_name": clean_name, "updated_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to rename file %s: %s", file_id, exc)
        return False


def move_file(file_id: int, folder_id: int, user_id: int | None = None) -> bool:
    """Move file to target folder, ensuring both file and folder belong to user_id."""
    if user_id is not None:
        f = get_file(file_id, user_id=user_id)
        if not f:
            log.warning("Unauthorized or missing file %s for user %s", file_id, user_id)
            return False
        dest = get_folder(folder_id, user_id=user_id)
        if not dest:
            log.warning("Unauthorized or missing destination folder %s for user %s", folder_id, user_id)
            return False

    try:
        q = db.table("files").update({"folder_id": folder_id, "updated_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to move file %s to folder %s: %s", file_id, folder_id, exc)
        return False


def trash_file(file_id: int, user_id: int | None = None) -> bool:
    try:
        q = db.table("files").update({"is_trashed": True, "trashed_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to trash file %s: %s", file_id, exc)
        return False


def restore_file(file_id: int, user_id: int | None = None) -> bool:
    f = get_file(file_id, user_id=user_id)
    if not f:
        return False

    owner_id = f["user_id"]
    # Check if target folder still exists; if not, restore to inbox
    dest_folder = get_folder(f["folder_id"], user_id=owner_id)
    target_folder_id = f["folder_id"] if dest_folder else get_or_create_inbox_folder(owner_id)["id"]

    try:
        res = (db.table("files")
               .update({"is_trashed": False, "trashed_at": None, "folder_id": target_folder_id, "updated_at": _now()})
               .eq("id", file_id)
               .eq("user_id", owner_id)
               .execute())
        if res.data:
            invalidate_user_files_cache(owner_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to restore file %s: %s", file_id, exc)
        return False


def permanent_delete(file_id: int, user_id: int | None = None) -> bool:
    try:
        q = db.table("files").delete().eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to permanently delete file %s: %s", file_id, exc)
        return False


def get_trash(user_id: int) -> list[dict]:
    try:
        return (db.table("files")
                .select("*")
                .eq("user_id", user_id)
                .eq("is_trashed", True)
                .order("trashed_at", desc=True)
                .limit(50)
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to get trash for user %s: %s", user_id, exc)
        return []


def empty_trash(user_id: int) -> bool:
    try:
        db.table("files").delete().eq("user_id", user_id).eq("is_trashed", True).execute()
        invalidate_user_files_cache(user_id)
        return True
    except Exception as exc:
        log.error("Failed to empty trash for user %s: %s", user_id, exc)
        return False


def search_files(user_id: int, query: str) -> list[dict]:
    clean_q = sanitize_filename(query).strip()
    if not clean_q:
        return []
    try:
        return (db.table("files")
                .select("*, folders(name)")
                .eq("user_id", user_id)
                .eq("is_trashed", False)
                .ilike("file_name", f"%{clean_q}%")
                .order("created_at", desc=True)
                .limit(20)
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to search files for user %s: %s", user_id, exc)
        return []


def get_storage_info(user_id: int) -> dict:
    try:
        files_data: list[dict] = []
        offset = 0
        page_size = 1000
        while True:
            batch = (db.table("files")
                     .select("file_size, file_type")
                     .eq("user_id", user_id)
                     .eq("is_trashed", False)
                     .range(offset, offset + page_size - 1)
                     .execute().data or [])
            if not batch:
                break
            files_data.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)

        total_size = sum(f.get("file_size", 0) for f in files_data)
        by_type: dict[str, int] = {}
        size_by_type: dict[str, int] = {}
        for f in files_data:
            ft = f.get("file_type", "other")
            sz = f.get("file_size", 0)
            by_type[ft] = by_type.get(ft, 0) + 1
            size_by_type[ft] = size_by_type.get(ft, 0) + sz

        folder_res = db.table("folders").select("id", count="exact").eq("user_id", user_id).execute()
        trash_res = db.table("files").select("id", count="exact").eq("user_id", user_id).eq("is_trashed", True).execute()

        return {
            "total_size": total_size,
            "total_files": len(files_data),
            "total_folders": folder_res.count or 0,
            "trash_count": trash_res.count or 0,
            "by_type": by_type,
            "size_by_type": size_by_type,
        }
    except Exception as exc:
        log.error("Failed to get storage info for user %s: %s", user_id, exc)
        return {
            "total_size": 0,
            "total_files": 0,
            "total_folders": 0,
            "trash_count": 0,
            "by_type": {},
            "size_by_type": {},
        }


# ── Starred (Favorites) ────────────────────────────────

def toggle_star_file(file_id: int, user_id: int | None = None) -> bool | None:
    f = get_file(file_id, user_id=user_id)
    if not f:
        return None
    new_state = not bool(f.get("is_starred"))
    try:
        db.table("files").update({"is_starred": new_state, "updated_at": _now()}).eq("id", file_id).eq("user_id", f["user_id"]).execute()
        invalidate_user_files_cache(f["user_id"])
        return new_state
    except Exception as exc:
        log.error("Failed to toggle star file %s: %s", file_id, exc)
        return None


def toggle_star_folder(folder_id: int, user_id: int | None = None) -> bool | None:
    folder = get_folder(folder_id, user_id=user_id)
    if not folder:
        return None
    new_state = not bool(folder.get("is_starred"))
    try:
        db.table("folders").update({"is_starred": new_state, "updated_at": _now()}).eq("id", folder_id).eq("user_id", folder["user_id"]).execute()
        return new_state
    except Exception as exc:
        log.error("Failed to toggle star folder %s: %s", folder_id, exc)
        return None


def get_starred_folders(user_id: int) -> list[dict]:
    try:
        return (db.table("folders")
                .select("*")
                .eq("user_id", user_id)
                .eq("is_starred", True)
                .order("name")
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to get starred folders: %s", exc)
        return []


def get_starred_files(user_id: int) -> list[dict]:
    try:
        return (db.table("files")
                .select("*, folders(name)")
                .eq("user_id", user_id)
                .eq("is_trashed", False)
                .eq("is_starred", True)
                .order("created_at", desc=True)
                .limit(50)
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to get starred files: %s", exc)
        return []


def get_recent_files(user_id: int, limit: int = 15) -> list[dict]:
    try:
        return (db.table("files")
                .select("*, folders(name)")
                .eq("user_id", user_id)
                .eq("is_trashed", False)
                .order("created_at", desc=True)
                .limit(limit)
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to get recent files: %s", exc)
        return []


def get_all_files_in_folder(folder_id: int, user_id: int | None = None) -> list[dict]:
    if user_id is not None:
        folder = get_folder(folder_id, user_id=user_id)
        if not folder:
            return []
    try:
        return (db.table("files")
                .select("*")
                .eq("folder_id", folder_id)
                .eq("is_trashed", False)
                .order("created_at", desc=False)
                .execute().data or [])
    except Exception as exc:
        log.error("Failed to get files in folder %s: %s", folder_id, exc)
        return []


# ── Public Share Links & Security Policy ───────────────

def get_or_create_file_share_token(file_id: int, user_id: int | None = None) -> str | None:
    f = get_file(file_id, user_id=user_id)
    if not f:
        return None
    raw = f.get("share_token")
    if raw:
        clean = parse_share_token(raw)["token"]
        if clean:
            return clean
        return raw

    token = secrets.token_urlsafe(16)
    try:
        db.table("files").update({"share_token": token, "updated_at": _now()}).eq("id", file_id).execute()
        return token
    except Exception as exc:
        log.error("Failed to create share token for file %s: %s", file_id, exc)
        return None


def revoke_file_share_token(file_id: int, user_id: int | None = None) -> bool:
    try:
        q = db.table("files").update({"share_token": None, "updated_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to revoke share token for file %s: %s", file_id, exc)
        return False


def get_file_by_share_token(token: str) -> dict | None:
    """Exact-match lookup for shared file by token."""
    if not token or not isinstance(token, str):
        return None
    clean_token = token.split("|")[0].strip()
    if not clean_token:
        return None

    try:
        # 1. Exact match on raw token string
        res = db.table("files").select("*, folders(name)").eq("share_token", clean_token).eq("is_trashed", False).execute()
        if res.data:
            return res.data[0]

        # 2. Match with metadata pipe prefix (exact token before pipe)
        res = db.table("files").select("*, folders(name)").ilike("share_token", f"{clean_token}|%").eq("is_trashed", False).execute()
        if res.data:
            for item in res.data:
                parsed = parse_share_token(item.get("share_token"))
                if parsed["token"] == clean_token:
                    return item
        return None
    except Exception as exc:
        log.error("Failed to query file by share token: %s", exc)
        return None


def validate_public_share(token_or_file: str | dict, pin: str | None = None) -> tuple[dict | None, str | None]:
    """Single Source of Truth for validating a public file share.

    Accepts either a string token or pre-fetched file dict.
    Returns:
        (file_dict, None) if access is granted.
        (file_dict, "PIN_REQUIRED") if PIN is needed but not provided.
        (None, error_code) if rejected.
        Error codes: 'NOT_FOUND', 'EXPIRED', 'LIMIT_EXHAUSTED', 'PIN_INCORRECT'
    """
    if isinstance(token_or_file, dict):
        f = token_or_file
    else:
        f = get_file_by_share_token(token_or_file)

    if not f or f.get("is_trashed"):
        return None, "NOT_FOUND"

    sec = parse_share_token(f.get("share_token") or "")
    now = int(time.time())

    # Expiration check
    if sec.get("expires_at") and now > sec["expires_at"]:
        return None, "EXPIRED"

    # Download limit check
    if sec.get("limit") is not None and sec.get("count", 0) >= sec["limit"]:
        return None, "LIMIT_EXHAUSTED"

    # PIN check
    stored_pin_hash = sec.get("pin_hash")
    if stored_pin_hash:
        if pin is None:
            # Tell caller that PIN is required to unlock
            return f, "PIN_REQUIRED"
        if not verify_pin(pin, stored_pin_hash):
            return None, "PIN_INCORRECT"

    return f, None


_UNSET = object()


def update_file_share_security(
    file_id: int,
    expires_at=_UNSET,
    pin=_UNSET,
    limit=_UNSET,
    clear_all: bool = False,
    user_id: int | None = None,
) -> str | None:
    f = get_file(file_id, user_id=user_id)
    if not f:
        return None

    raw = f.get("share_token") or secrets.token_urlsafe(16)
    p = parse_share_token(raw)

    if clear_all:
        final_exp = None
        final_pin = None
        final_lim = None
        final_cnt = 0
    else:
        final_exp = p["expires_at"] if expires_at is _UNSET else expires_at
        final_pin = p["pin_hash"] if pin is _UNSET else pin
        final_lim = p["limit"] if limit is _UNSET else limit
        final_cnt = p["count"]

    new_token_str = encode_share_token(
        p["token"], expires_at=final_exp, pin=final_pin, limit=final_lim, count=final_cnt
    )
    try:
        q = db.table("files").update({"share_token": new_token_str, "updated_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        q.execute()
        return p["token"]
    except Exception as exc:
        log.error("Failed to update share security for file %s: %s", file_id, exc)
        return None


def record_file_share_download(file_id: int) -> bool:
    """Atomic download increment and one-time link burn."""
    f = get_file(file_id)
    if not f or not f.get("share_token"):
        return False

    p = parse_share_token(f["share_token"])
    new_cnt = p["count"] + 1

    # Check if this download exhausts the limit
    if p["limit"] is not None and new_cnt >= p["limit"]:
        revoke_file_share_token(file_id)
        return True

    new_token_str = encode_share_token(
        p["token"],
        expires_at=p["expires_at"],
        pin=p["pin_hash"],
        limit=p["limit"],
        count=new_cnt,
    )
    try:
        db.table("files").update({"share_token": new_token_str, "updated_at": _now()}).eq("id", file_id).execute()
        return True
    except Exception as exc:
        log.error("Failed to record share download for file %s: %s", file_id, exc)
        return False


def update_file_notes_and_tags(
    file_id: int,
    note: str | None = None,
    tags: list[str] | None = None,
    user_id: int | None = None,
) -> bool:
    from utils import parse_file_metadata, encode_file_metadata
    f = get_file(file_id, user_id=user_id)
    if not f:
        return False

    clean_mime, curr_note, curr_tags = parse_file_metadata(f.get("mime_type"))
    final_note = note if note is not None else curr_note
    final_tags = tags if tags is not None else curr_tags
    new_mime = encode_file_metadata(clean_mime, final_note, final_tags)

    try:
        q = db.table("files").update({"mime_type": new_mime, "updated_at": _now()}).eq("id", file_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        if res.data:
            invalidate_user_files_cache(user_id)
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to update notes/tags for file %s: %s", file_id, exc)
        return False


def get_or_create_folder_share_token(folder_id: int, user_id: int | None = None) -> str | None:
    folder = get_folder(folder_id, user_id=user_id)
    if not folder:
        return None
    token = folder.get("share_token")
    if token:
        clean = token.split("|")[0].strip()
        if clean:
            return clean

    token = secrets.token_urlsafe(16)
    try:
        q = db.table("folders").update({"share_token": token, "updated_at": _now()}).eq("id", folder_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        q.execute()
        return token
    except Exception as exc:
        log.error("Failed to create folder share token for %s: %s", folder_id, exc)
        return None


def revoke_folder_share_token(folder_id: int, user_id: int | None = None) -> bool:
    try:
        q = db.table("folders").update({"share_token": None, "updated_at": _now()}).eq("id", folder_id)
        if user_id is not None:
            q = q.eq("user_id", user_id)
        res = q.execute()
        return bool(res.data)
    except Exception as exc:
        log.error("Failed to revoke folder share token for %s: %s", folder_id, exc)
        return False


def get_folder_by_share_token(token: str) -> dict | None:
    if not token or not isinstance(token, str):
        return None
    clean_token = token.split("|")[0].strip()
    if not clean_token:
        return None

    try:
        res = db.table("folders").select("*").eq("share_token", clean_token).execute()
        if res.data:
            return res.data[0]
        res = db.table("folders").select("*").ilike("share_token", f"{clean_token}|%").execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as exc:
        log.error("Failed to get folder by share token: %s", exc)
        return None


def copy_file_to_user_folder(source_file: dict, target_user_id: int, target_folder_id: int) -> dict | None:
    """Copy a shared file into a user's own folder with strict destination ownership check."""
    target_folder = get_folder(target_folder_id, user_id=target_user_id)
    if not target_folder:
        inbox = get_or_create_inbox_folder(target_user_id)
        target_folder_id = inbox["id"]

    data = {
        "user_id": target_user_id,
        "folder_id": target_folder_id,
        "file_name": sanitize_filename(source_file["file_name"]),
        "file_id": source_file["file_id"],
        "file_unique_id": source_file["file_unique_id"],
        "file_type": source_file["file_type"],
        "file_size": source_file.get("file_size", 0),
        "mime_type": source_file.get("mime_type"),
        "thumbnail_file_id": source_file.get("thumbnail_file_id"),
    }
    try:
        res = db.table("files").insert(data).execute()
        if res.data:
            invalidate_user_files_cache(target_user_id)
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to copy file to user %s folder %s: %s", target_user_id, target_folder_id, exc)
        return None


# ── Duplicates & Storage Health ────────────────────────

def find_duplicate_file(user_id: int, file_unique_id: str) -> dict | None:
    try:
        res = (db.table("files")
               .select("*, folders(name)")
               .eq("user_id", user_id)
               .eq("file_unique_id", file_unique_id)
               .eq("is_trashed", False)
               .limit(1)
               .execute())
        return res.data[0] if res.data else None
    except Exception as exc:
        log.error("Failed to find duplicate for user %s: %s", user_id, exc)
        return None


def get_all_user_files(
    user_id: int,
    limit: int | None = 100,
    is_trashed: bool = False,
    use_cache: bool = True,
) -> list[dict]:
    cache_key = (user_id, is_trashed)
    now = time.time()

    # Fast path: return from in-memory cache if available
    if use_cache and cache_key in _USER_FILES_CACHE:
        cached_time, cached_files = _USER_FILES_CACHE[cache_key]
        if (now - cached_time) < _USER_FILES_CACHE_TTL:
            if limit is None:
                return list(cached_files)
            return list(cached_files[:limit])

    try:
        # Small limit: single fast database query
        if limit is not None and limit <= 1000:
            res = (db.table("files")
                    .select("*, folders(name)")
                    .eq("user_id", user_id)
                    .eq("is_trashed", is_trashed)
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute().data or [])
            return res

        # Large limit or limit is None: paginate across all PostgREST pages
        all_files: list[dict] = []
        offset = 0
        page_size = 1000
        while True:
            fetch_size = page_size
            if limit is not None:
                remaining = limit - len(all_files)
                if remaining <= 0:
                    break
                fetch_size = min(page_size, remaining)

            batch = (db.table("files")
                     .select("*, folders(name)")
                     .eq("user_id", user_id)
                     .eq("is_trashed", is_trashed)
                     .order("created_at", desc=True)
                     .range(offset, offset + fetch_size - 1)
                     .execute().data or [])
            if not batch:
                break
            all_files.extend(batch)
            if len(batch) < fetch_size:
                break
            offset += len(batch)

        if limit is None and use_cache:
            _USER_FILES_CACHE[cache_key] = (now, all_files)

        return all_files
    except Exception as exc:
        log.error("Failed to get all user files for %s: %s", user_id, exc)
        return []


def get_storage_health(user_id: int) -> dict:
    default = {
        "largest_files": [],
        "duplicate_groups": [],
        "total_duplicates": 0,
        "dup_wasted_size": 0,
        "trash_count": 0,
        "trash_size": 0,
    }
    try:
        largest = (db.table("files")
                   .select("*, folders(name)")
                   .eq("user_id", user_id)
                   .eq("is_trashed", False)
                   .order("file_size", desc=True)
                   .limit(5)
                   .execute().data or [])

        all_files: list[dict] = []
        offset = 0
        page_size = 1000
        while True:
            batch = (db.table("files")
                     .select("id, file_name, file_size, file_unique_id, folder_id, folders(name)")
                     .eq("user_id", user_id)
                     .eq("is_trashed", False)
                     .range(offset, offset + page_size - 1)
                     .execute().data or [])
            if not batch:
                break
            all_files.extend(batch)
            if len(batch) < page_size:
                break
            offset += len(batch)

        seen: dict[str, list[dict]] = {}
        for f in all_files:
            uid = f.get("file_unique_id")
            if uid:
                seen.setdefault(uid, []).append(f)

        dup_groups = [flist for flist in seen.values() if len(flist) > 1]
        extra_dups = sum(len(d) - 1 for d in dup_groups)
        dup_wasted_size = sum(sum(item.get("file_size", 0) for item in group[1:]) for group in dup_groups)

        trash_items = (db.table("files")
                       .select("file_size")
                       .eq("user_id", user_id)
                       .eq("is_trashed", True)
                       .execute().data or [])
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
        log.error("Failed to fetch storage health for user %s: %s", user_id, exc)
        return default


def clean_duplicate_files(user_id: int) -> int:
    """Move redundant duplicate files to trash, keeping earliest copy. Enforces user_id."""
    health = get_storage_health(user_id)
    trashed_count = 0
    for group in health["duplicate_groups"]:
        for extra in group[1:]:
            if trash_file(extra["id"], user_id=user_id):
                trashed_count += 1
    return trashed_count


# ── Storage Reset & Secure Account Recovery ────────────

def reset_user_storage(user_id: int) -> dict:
    """Permanently delete all files and folders of authenticated user, recreate inbox."""
    try:
        db.table("files").delete().eq("user_id", user_id).execute()
        db.table("folders").delete().eq("user_id", user_id).execute()
    except Exception as exc:
        log.error("Error during reset_user_storage for %s: %s", user_id, exc)
    return get_or_create_inbox_folder(user_id)


def find_recoverable_account(new_user_id: int, username: str | None = None) -> dict | None:
    """Automatic recovery by username is permanently disabled for security.

    Account transfers now require an explicit, cryptographically random,
    one-time recovery code generated by the authenticated owner account.
    """
    return None


def generate_account_recovery_code(
    owner_user_id: int, validity_seconds: int = 900, expiry_hours: int | None = None
) -> str:
    """Generate a one-time cryptographic recovery code from authenticated owner account."""
    if expiry_hours is not None:
        validity_seconds = int(expiry_hours * 3600)
    code_raw = "DREC-" + secrets.token_hex(2).upper() + "-" + secrets.token_hex(2).upper()
    code_hash = hashlib.sha256(code_raw.encode("utf-8")).hexdigest()
    expires_at = int(time.time()) + validity_seconds

    _RECOVERY_CODES[code_hash] = {
        "user_id": owner_user_id,
        "expires_at": expires_at,
    }
    return code_raw


def redeem_account_recovery_code(code: str, new_user_id: int) -> tuple[bool, str, dict | None]:
    """Redeem one-time recovery code and transfer data to new account."""
    clean_code = code.strip().upper()
    code_hash = hashlib.sha256(clean_code.encode("utf-8")).hexdigest()

    record = _RECOVERY_CODES.pop(code_hash, None)
    if not record:
        return False, "Kode pemulihan tidak valid atau sudah digunakan.", None

    if int(time.time()) > record["expires_at"]:
        return False, "Kode pemulihan telah kadaluarsa (berlaku 15 menit).", None

    old_user_id = record["user_id"]
    if old_user_id == new_user_id:
        return False, "Tidak dapat menyambungkan akun ke akun yang sama.", None

    stats = transfer_user_data(old_user_id, new_user_id)
    return True, "Akun berhasil dipulihkan!", stats


def transfer_user_data(old_user_id: int, new_user_id: int) -> dict:
    """Transfer all folders and files from old_user_id to new_user_id."""
    upsert_user(new_user_id)
    try:
        db.table("folders").update({"user_id": new_user_id}).eq("user_id", old_user_id).execute()
        db.table("files").update({"user_id": new_user_id}).eq("user_id", old_user_id).execute()
    except Exception as exc:
        log.error("Failed to transfer user data from %s to %s: %s", old_user_id, new_user_id, exc)

    get_or_create_inbox_folder(new_user_id)
    return get_storage_info(new_user_id)


# ── User Classification Preferences (Task 2D) ───────────────
_USER_PREFERENCES: dict[int, list[dict]] = {}


def get_user_preferences(user_id: int) -> list[dict]:
    """Retrieve personal classification preferences for authenticated user."""
    try:
        res = db.table("user_classification_preferences").select("*").eq("user_id", user_id).execute()
        if res.data:
            return res.data
    except Exception as exc:
        log.debug("Falling back to local preference store for user %s: %s", user_id, exc)
    return list(_USER_PREFERENCES.get(user_id, []))


def record_user_preference(
    user_id: int,
    pattern: str,
    target_folder_id: int,
    action: str = "accepted",
    domain: str | None = None,
    category: str | None = None,
) -> dict | None:
    """Record or update user preference feedback with positive/negative counts."""
    dest = get_folder(target_folder_id, user_id=user_id)
    if not dest or dest.get("user_id") != user_id:
        log.warning("Unauthorized folder %s for user preference %s", target_folder_id, user_id)
        return None

    pattern_clean = pattern.strip().lower()
    if not pattern_clean:
        return None

    prefs = _USER_PREFERENCES.setdefault(user_id, [])
    existing = None
    for p in prefs:
        if p["pattern"] == pattern_clean and p["target_folder_id"] == target_folder_id:
            existing = p
            break

    now = _now()
    if not existing:
        pos = 1 if action in ("accepted", "corrected") else 0
        neg = 1 if action == "rejected" else 0
        conf = 0.5 if pos > 0 else 0.0
        record = {
            "id": len(prefs) + 1,
            "user_id": user_id,
            "pattern": pattern_clean,
            "target_folder_id": target_folder_id,
            "domain": domain,
            "category": category,
            "positive_count": pos,
            "negative_count": neg,
            "confidence": conf,
            "created_at": now,
            "updated_at": now,
        }
        prefs.append(record)
    else:
        if action in ("accepted", "corrected"):
            existing["positive_count"] += 1
        elif action == "rejected":
            existing["negative_count"] += 1

        total = existing["positive_count"] + existing["negative_count"]
        ratio = existing["positive_count"] / max(1, total)
        if existing["positive_count"] >= 5 and ratio >= 0.85:
            existing["confidence"] = 0.90
        elif existing["positive_count"] >= 3 and ratio >= 0.75:
            existing["confidence"] = 0.75
        elif existing["positive_count"] >= 1:
            existing["confidence"] = min(0.60, round(ratio * 0.7, 2))
        else:
            existing["confidence"] = 0.0

        existing["updated_at"] = now
        record = existing

    try:
        db.table("user_classification_preferences").upsert(record).execute()
    except Exception as exc:
        log.debug("Remote preference upsert bypassed: %s", exc)

    return dict(record)


def clear_user_preferences(user_id: int | None = None) -> None:
    """Clear in-memory user preferences (useful for test resets)."""
    if user_id is None:
        _USER_PREFERENCES.clear()
    else:
        _USER_PREFERENCES.pop(user_id, None)

