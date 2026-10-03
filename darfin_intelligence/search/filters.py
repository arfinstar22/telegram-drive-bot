"""Deterministic filter evaluation for Darfin Search Intelligence Core.

Applies explicit search filters as hard inclusion/exclusion gates before scoring.
"""

from __future__ import annotations

from typing import Any
from darfin_intelligence.dictionaries import EXTENSION_FAMILIES, mime_to_family
from darfin_intelligence.search.models import SearchFilters


def get_file_extension(filename: str) -> str:
    """Extract lowercase file extension without dot."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower().strip()


def get_file_family(file_item: dict[str, Any]) -> str:
    """Determine file family using file_type, extension, or MIME."""
    ftype = file_item.get("file_type")
    if ftype and ftype in ("video", "photo", "image", "document", "audio", "archive", "application"):
        if ftype in ("photo", "image"):
            return "image"
        return ftype

    ext = get_file_extension(file_item.get("file_name", ""))
    if ext in EXTENSION_FAMILIES:
        return EXTENSION_FAMILIES[ext]

    mime = file_item.get("mime_type")
    if mime:
        fam = mime_to_family(mime.split("|")[0])
        if fam:
            return fam

    return "other"


def apply_filters(file_item: dict[str, Any], filters: SearchFilters) -> tuple[bool, str | None]:
    """Check if a file item satisfies all active filters.

    Returns:
        (True, None) if satisfies all filters, (False, reason) otherwise.
    """
    # 1. Trashed filter: default is False (exclude trashed files)
    is_trashed = bool(file_item.get("is_trashed", False))
    if is_trashed != filters.is_trashed:
        return False, "trashed_mismatch"

    # 2. Extension filter
    if filters.extension:
        target_ext = filters.extension.lower().lstrip(".")
        file_ext = get_file_extension(file_item.get("file_name", ""))
        if file_ext != target_ext:
            return False, f"extension_mismatch: {file_ext} != {target_ext}"

    # 3. Family / File Type filter
    if filters.family:
        target_fam = filters.family.lower()
        if target_fam in ("photo", "picture", "img"):
            target_fam = "image"
        elif target_fam in ("doc", "docs", "surat"):
            target_fam = "document"
        elif target_fam in ("film", "vidio", "movie"):
            target_fam = "video"
        elif target_fam in ("musik", "lagu", "mp3"):
            target_fam = "audio"

        actual_fam = get_file_family(file_item)
        if actual_fam != target_fam:
            return False, f"family_mismatch: {actual_fam} != {target_fam}"

    # 4. MIME filter
    if filters.mime_type:
        clean_mime = (file_item.get("mime_type") or "").split("|")[0].lower()
        target_mime = filters.mime_type.lower()
        if not clean_mime.startswith(target_mime):
            return False, f"mime_mismatch: {clean_mime} != {target_mime}"

    # 5. Domain filter (Task 2A)
    if filters.domain:
        target_domain = filters.domain.lower()
        meta = file_item.get("metadata") or {}
        actual_domain = (file_item.get("domain") or meta.get("domain") or "").lower()
        if actual_domain != target_domain:
            return False, f"domain_mismatch: {actual_domain} != {target_domain}"

    # 6. Folder ID filter
    if filters.folder_id is not None:
        if file_item.get("folder_id") != filters.folder_id:
            return False, "folder_id_mismatch"

    # 7. Folder Name filter
    if filters.folder_name:
        target_folder = filters.folder_name.lower().strip()
        folder_obj = file_item.get("folders")
        actual_folder_name = ""
        actual_folder_path = ""
        if isinstance(folder_obj, dict):
            actual_folder_name = folder_obj.get("name", "") or ""
            actual_folder_path = folder_obj.get("path", "") or ""
        elif isinstance(folder_obj, str):
            actual_folder_name = folder_obj
            actual_folder_path = folder_obj
        else:
            actual_folder_name = str(file_item.get("folder_name", "") or "")
            actual_folder_path = str(file_item.get("folder_path", "") or "")

        if target_folder not in actual_folder_name.lower() and target_folder not in actual_folder_path.lower():
            return False, f"folder_name_mismatch: {target_folder} not in {actual_folder_name} or {actual_folder_path}"

    # 8. File size filters
    size = file_item.get("file_size", 0) or 0
    if filters.size_min is not None and size < filters.size_min:
        return False, f"size_too_small: {size} < {filters.size_min}"
    if filters.size_max is not None and size > filters.size_max:
        return False, f"size_too_large: {size} > {filters.size_max}"

    # 9. Date filters (created_at or metadata date)
    created_at = str(file_item.get("created_at") or "")
    if filters.date_from and created_at and created_at < filters.date_from:
        return False, f"date_before_min: {created_at} < {filters.date_from}"
    if filters.date_to and created_at:
        # compare up to date_to end of day
        date_to_bound = filters.date_to if "T" in filters.date_to else f"{filters.date_to}T23:59:59"
        if created_at > date_to_bound:
            return False, f"date_after_max: {created_at} > {date_to_bound}"

    # 10. OCR presence filter
    if filters.has_ocr is not None:
        meta = file_item.get("metadata") or {}
        has_ocr_content = bool(file_item.get("ocr_text") or meta.get("ocr_text"))
        if has_ocr_content != filters.has_ocr:
            return False, "has_ocr_mismatch"

    # 11. Document type filter (Task 3C)
    if filters.document_type:
        target_doc = filters.document_type.lower()
        meta = file_item.get("metadata") or {}
        actual_doc = (file_item.get("document_type") or meta.get("document_type") or "").lower()
        if actual_doc != target_doc:
            return False, f"document_type_mismatch: {actual_doc} != {target_doc}"

    # 12. Merchant filter (Task 3C)
    if filters.merchant:
        target_merch = filters.merchant.lower()
        meta = file_item.get("metadata") or {}
        actual_merch = (file_item.get("merchant_name") or meta.get("merchant_name") or "").lower()
        if target_merch not in actual_merch:
            return False, f"merchant_mismatch: {target_merch} not in {actual_merch}"

    # 13. Payment method filter (Task 3C)
    if filters.payment_method:
        target_pay = filters.payment_method.lower()
        meta = file_item.get("metadata") or {}
        actual_pay = (file_item.get("payment_method") or meta.get("payment_method") or "").lower()
        if actual_pay != target_pay:
            return False, f"payment_method_mismatch: {actual_pay} != {target_pay}"

    return True, None
