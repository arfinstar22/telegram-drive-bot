"""Smart Folder Mapping package for Darfin Storage (Task 2B).

Maps Task 2A ClassificationResult to existing user folders with ranking,
confidence, explanation, ambiguity detection, and hierarchy path resolution.
Purely read-only calculation — never touches the database or files.
"""

from __future__ import annotations

from darfin_intelligence.organizer.models import (
    FolderCandidate,
    FolderSuggestion,
    OrganizationItem,
    OrganizationPlan,
)
from darfin_intelligence.organizer.folder_matcher import build_folder_index
from darfin_intelligence.organizer.folder_mapper import map_folder, FolderMapper
from darfin_intelligence.organizer.safe_organizer import (
    SafeOrganizer,
    create_plan,
    preview,
    execute_item,
    execute_batch,
    record_audit,
    get_audit_records,
    clear_audit_records,
)

__all__ = [
    "map_folder",
    "FolderMapper",
    "FolderCandidate",
    "FolderSuggestion",
    "build_folder_index",
    "OrganizationItem",
    "OrganizationPlan",
    "SafeOrganizer",
    "create_plan",
    "preview",
    "execute_item",
    "execute_batch",
    "record_audit",
    "get_audit_records",
    "clear_audit_records",
]

