"""Search index representation for Darfin Search Intelligence Core.

Transforms raw file dictionaries into structured, pre-tokenized index records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from utils import parse_file_metadata
from darfin_intelligence.search.filters import get_file_extension, get_file_family
from darfin_intelligence.search.tokenizer import extract_filename_tokens


@dataclass
class IndexableFile:
    """Pre-processed search document for rapid evaluation."""
    asset_id: int | str
    file_name: str
    file_stem: str
    filename_tokens: list[str] = field(default_factory=list)
    extension: str = ""
    family: str = "other"
    mime_type: str = ""
    folder_id: int | None = None
    folder_name: str = ""
    folder_path: str = ""
    tags: list[str] = field(default_factory=list)
    note: str = ""
    domain: str = ""
    category: str = ""
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    screenshot_category: str = ""
    document_type: str = ""
    merchant_name: str = ""
    receipt_number: str = ""
    document_number: str = ""
    subject: str = ""
    total_amount: float | None = None
    payment_method: str = ""
    important_dates: list[str] = field(default_factory=list)
    created_at: str = ""
    raw_item: dict[str, Any] = field(default_factory=dict)


def build_indexable_file(item: dict[str, Any]) -> IndexableFile:
    """Convert raw database or memory file dict into IndexableFile."""
    fname = str(item.get("file_name", "") or "")
    ext = get_file_extension(fname)
    stem = fname.rsplit(".", 1)[0] if "." in fname else fname
    tokens = extract_filename_tokens(fname)
    fam = get_file_family(item)

    clean_mime, custom_note, custom_tags = parse_file_metadata(item.get("mime_type"))

    # Folder handling
    folder_obj = item.get("folders")
    folder_name = ""
    folder_path = ""
    if isinstance(folder_obj, dict):
        folder_name = folder_obj.get("name", "") or ""
        folder_path = folder_obj.get("path", "") or folder_name
    elif isinstance(folder_obj, str):
        folder_name = folder_obj
        folder_path = folder_obj
    else:
        folder_name = str(item.get("folder_name", "") or "")
        folder_path = str(item.get("folder_path", "") or folder_name)

    # Tags & notes consolidation
    tags_set = set(custom_tags)
    raw_tags = item.get("tags")
    if isinstance(raw_tags, list):
        for t in raw_tags:
            tags_set.add(str(t).lower().lstrip("#"))
    note_val = item.get("note") or custom_note or ""

    # Metadata extraction (Tasks 1, 2A, 3B, 3C)
    raw_meta = item.get("metadata")
    meta = raw_meta if isinstance(raw_meta, dict) else {}

    domain_val = str(item.get("domain") or meta.get("domain") or "").lower()
    category_val = str(item.get("category") or meta.get("category") or "").lower()

    ocr_text = str(item.get("ocr_text") or meta.get("ocr_text") or "")
    ocr_conf = float(item.get("ocr_confidence") or meta.get("ocr_confidence") or 0.0)

    ss_cat = str(item.get("screenshot_category") or meta.get("screenshot_category") or "").lower()
    doc_type = str(item.get("document_type") or meta.get("document_type") or "").lower()
    merchant = str(item.get("merchant_name") or meta.get("merchant_name") or "")
    receipt_no = str(item.get("receipt_number") or meta.get("receipt_number") or "")
    doc_no = str(item.get("document_number") or meta.get("document_number") or "")
    subject = str(item.get("subject") or meta.get("subject") or "")
    pay_method = str(item.get("payment_method") or meta.get("payment_method") or "").lower()

    tot_amt = item.get("total_amount") if item.get("total_amount") is not None else meta.get("total_amount")
    if tot_amt is not None:
        try:
            tot_amt = float(tot_amt)
        except (ValueError, TypeError):
            tot_amt = None

    dates_list: list[str] = []
    raw_dates = item.get("important_dates") or meta.get("important_dates")
    if isinstance(raw_dates, list):
        dates_list = [str(d) for d in raw_dates]

    return IndexableFile(
        asset_id=item.get("id", ""),
        file_name=fname,
        file_stem=stem,
        filename_tokens=tokens,
        extension=ext,
        family=fam,
        mime_type=clean_mime,
        folder_id=item.get("folder_id"),
        folder_name=folder_name,
        folder_path=folder_path,
        tags=sorted(list(tags_set)),
        note=note_val,
        domain=domain_val,
        category=category_val,
        ocr_text=ocr_text,
        ocr_confidence=ocr_conf,
        screenshot_category=ss_cat,
        document_type=doc_type,
        merchant_name=merchant,
        receipt_number=receipt_no,
        document_number=doc_no,
        subject=subject,
        total_amount=tot_amt,
        payment_method=pay_method,
        important_dates=dates_list,
        created_at=str(item.get("created_at") or ""),
        raw_item=item,
    )
