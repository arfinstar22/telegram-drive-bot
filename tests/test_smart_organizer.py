"""Comprehensive test suite for Safe Smart Organizer (Task 2C).

Covers:
- Plan generation & dry-run immutability
- User approval & safe file movement
- Stale plan detection & prevention
- Ownership validation & Cross-user attack resistance
- Batch execution & partial result reporting
- Idempotency & already-in-target no-op
- Trash protection
- Confidence thresholds (low, medium, high)
- Auto-organize enable/disable toggles
- Sensitive category safety (identity, health, legal, finance)
- Audit logging integrity (no credentials or tokens leaked)
- Section 23-28 required tests
- Performance benchmark (1,000 files in pure memory)
"""

import time
import unittest
from typing import Any

from darfin_intelligence.classifier.models import ClassificationResult
from darfin_intelligence.organizer import (
    SafeOrganizer,
    OrganizationPlan,
    OrganizationItem,
    create_plan,
    preview,
    execute_item,
    execute_batch,
    clear_audit_records,
    get_audit_records,
)


class MockDatabase:
    """Mock database simulating user-isolated Supabase storage operations."""

    def __init__(self):
        self.files: dict[int, dict[str, Any]] = {
            101: {
                "id": 101,
                "file_name": "Invoice_2026.pdf",
                "user_id": 1,
                "folder_id": 10,
                "is_trashed": False,
                "updated_at": "2026-09-30T10:00:00Z",
            },
            102: {
                "id": 102,
                "file_name": "Movie_Action_2026.1080p.mkv",
                "user_id": 1,
                "folder_id": 10,
                "is_trashed": False,
                "updated_at": "2026-09-30T10:00:00Z",
            },
            103: {
                "id": 103,
                "file_name": "Old_Draft.pdf",
                "user_id": 1,
                "folder_id": 10,
                "is_trashed": True,
                "updated_at": "2026-09-30T10:00:00Z",
            },
            104: {
                "id": 104,
                "file_name": "Lecture_Notes.pdf",
                "user_id": 1,
                "folder_id": 30,  # Already in Kuliah
                "is_trashed": False,
                "updated_at": "2026-09-30T10:00:00Z",
            },
            201: {
                "id": 201,
                "file_name": "Bob_Private.pdf",
                "user_id": 2,
                "folder_id": 20,
                "is_trashed": False,
                "updated_at": "2026-09-30T10:00:00Z",
            },
            202: {
                "id": 202,
                "file_name": "Bob_Video.mp4",
                "user_id": 2,
                "folder_id": 20,
                "is_trashed": False,
                "updated_at": "2026-09-30T10:00:00Z",
            },
        }

        self.folders: dict[int, dict[str, Any]] = {
            10: {"id": 10, "name": "Inbox", "user_id": 1, "parent_id": None},
            25: {"id": 25, "name": "Film", "user_id": 1, "parent_id": None},
            26: {"id": 26, "name": "Keuangan", "user_id": 1, "parent_id": None},
            30: {"id": 30, "name": "Kuliah", "user_id": 1, "parent_id": None},
            50: {"id": 50, "name": "Bob_Folder", "user_id": 2, "parent_id": None},
        }

    def get_file(self, file_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        f = self.files.get(file_id)
        if not f:
            return None
        if user_id is not None and f["user_id"] != user_id:
            return None
        return dict(f)

    def get_folder(self, folder_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        fold = self.folders.get(folder_id)
        if not fold:
            return None
        if user_id is not None and fold["user_id"] != user_id:
            return None
        return dict(fold)

    def move_file(self, file_id: int, folder_id: int, user_id: int | None = None) -> bool:
        f = self.get_file(file_id, user_id=user_id)
        fold = self.get_folder(folder_id, user_id=user_id)
        if not f or not fold:
            return False
        self.files[file_id]["folder_id"] = folder_id
        self.files[file_id]["updated_at"] = "2026-09-30T12:00:00Z"
        return True


class TestPlanGenerationAndSafety(unittest.TestCase):
    """Test plan creation, safety rules, confidence thresholds, and categories."""

    def setUp(self):
        clear_audit_records()
        self.folders = [
            {"id": 10, "name": "Inbox", "parent_id": None},
            {"id": 25, "name": "Film", "parent_id": None},
            {"id": 26, "name": "Keuangan", "parent_id": None},
            {"id": 30, "name": "Kuliah", "parent_id": None},
        ]

    def test_basic_plan_creation(self):
        files = [
            {"id": 1, "file_name": "The.Matrix.1999.1080p.mkv", "folder_id": 10},
            {"id": 2, "file_name": "Invoice_Vendor_2026.pdf", "folder_id": 10},
        ]
        plan = create_plan(files, self.folders, user_id=1)
        self.assertEqual(plan.total_files, 2)
        self.assertTrue(plan.dry_run)
        self.assertFalse(plan.auto_organize_enabled)

        matrix_item = next(it for it in plan.items if it.file_id == 1)
        self.assertEqual(matrix_item.target_folder_id, 25)
        self.assertEqual(matrix_item.target_folder_name, "Film")
        self.assertEqual(matrix_item.status, "planned")
        self.assertEqual(matrix_item.decision, "suggest")

    def test_default_auto_organize_is_disabled(self):
        """Section 17: Default behavior is SUGGEST_ONLY, auto disabled."""
        files = [{"id": 1, "file_name": "Iron.Man.2008.1080p.BluRay.mkv", "folder_id": 10}]
        plan = create_plan(files, self.folders, auto_organize_enabled=False)
        item = plan.items[0]
        self.assertGreaterEqual(item.confidence, 0.95)
        self.assertEqual(item.decision, "suggest", "Default MUST be suggest even with 95%+ confidence")

    def test_auto_organize_enabled_allows_auto_decision_for_non_sensitive(self):
        """Section 18: Auto mode enables 'auto' decision for high-confidence non-sensitive items."""
        files = [{"id": 1, "file_name": "Inception.2010.1080p.mkv", "folder_id": 10}]
        plan = create_plan(files, self.folders, auto_organize_enabled=True, min_confidence=0.90)
        item = plan.items[0]
        self.assertEqual(item.decision, "auto")
        self.assertEqual(item.status, "planned")

    def test_sensitive_category_safety_blocks_auto_move(self):
        """Section 19: identity, health, legal, finance NEVER auto-move."""
        files = [
            {"id": 1, "file_name": "Invoice_Maret_2026.pdf", "folder_id": 10},  # finance
        ]
        plan = create_plan(files, self.folders, auto_organize_enabled=True, min_confidence=0.50)
        item = plan.items[0]
        self.assertEqual(item.domain, "finance")
        self.assertEqual(item.decision, "suggest", "Sensitive finance files must NEVER be auto-moved")
        self.assertTrue(any("Sensitive domain" in r for r in item.reasons))

    def test_already_in_target_folder_idempotency(self):
        """Section 11: File already in target folder is marked already_in_target and skipped."""
        files = [
            {"id": 1, "file_name": "Movie.mkv", "folder_id": 25},  # Already in Film (id=25)
        ]
        plan = create_plan(files, self.folders)
        item = plan.items[0]
        self.assertEqual(item.status, "already_in_target")
        self.assertEqual(item.decision, "skip")

    def test_trashed_files_skipped(self):
        """Section 13: Files in trash are skipped."""
        files = [
            {"id": 1, "file_name": "Movie.mkv", "folder_id": 10, "is_trashed": True},
        ]
        plan = create_plan(files, self.folders)
        item = plan.items[0]
        self.assertEqual(item.status, "in_trash")
        self.assertEqual(item.decision, "skip")

    def test_no_matching_folder_handled_cleanly(self):
        """Section 18: No matching user folder returns no_match and does NOT create folders."""
        empty_folders = [{"id": 99, "name": "RandomUnrelatedFolder", "parent_id": None}]
        files = [{"id": 1, "file_name": "Doctor_Prescription_Medical.pdf", "folder_id": 10}]
        plan = create_plan(files, empty_folders)
        item = plan.items[0]
        self.assertEqual(item.status, "no_match")
        self.assertEqual(item.decision, "skip")
        self.assertIsNone(item.target_folder_id)

    def test_ambiguous_target_requires_review(self):
        """Section 16: Ambiguous folder suggestions set status=ambiguous, decision=review."""
        ambiguous_folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Movies", "parent_id": None},
        ]
        files = [{"id": 10, "file_name": "Avatar.2009.mkv", "folder_id": None}]
        plan = create_plan(files, ambiguous_folders)
        item = plan.items[0]
        self.assertEqual(item.status, "ambiguous")
        self.assertEqual(item.decision, "review")

    def test_summary_and_serialization(self):
        files = [
            {"id": 1, "file_name": "The.Dark.Knight.2008.mkv", "folder_id": 10},
            {"id": 2, "file_name": "Trashed.pdf", "folder_id": 10, "is_trashed": True},
        ]
        plan = create_plan(files, self.folders)
        data = plan.to_dict()
        self.assertIn("plan_id", data)
        self.assertIn("summary", data)
        self.assertEqual(data["total_files"], 2)
        self.assertEqual(data["summary"]["planned"], 1)
        self.assertEqual(data["summary"]["in_trash"], 1)

    def test_explain_text(self):
        files = [{"id": 1, "file_name": "Inception.mkv", "folder_id": 10}]
        plan = create_plan(files, self.folders)
        item = plan.items[0]
        explanation = item.explain()
        self.assertIn("File: Inception.mkv", explanation)
        self.assertIn("Confidence:", explanation)
        self.assertIn("Reasons:", explanation)

    def test_low_confidence_requires_review(self):
        """Section 15: Low confidence (<0.50) sets status=low_confidence, decision=review."""
        low_conf_classification = ClassificationResult(
            domain="personal",
            category="note",
            confidence=0.35,
            family="document",
        )
        files = [{
            "id": 88,
            "file_name": "Catatan.txt",
            "folder_id": 10,
            "classification": low_conf_classification,
        }]
        plan = create_plan(files, [{"id": 90, "name": "Pribadi", "parent_id": None}])
        item = plan.items[0]
        self.assertEqual(item.status, "low_confidence")
        self.assertEqual(item.decision, "review")

    def test_sensitive_identity_blocks_auto_move(self):
        """Section 19: Identity files never auto-move."""
        files = [{"id": 1, "file_name": "KTP_Darfin.jpg", "folder_id": 10}]
        plan = create_plan(
            files,
            [{"id": 40, "name": "Identitas", "parent_id": None}],
            auto_organize_enabled=True,
            min_confidence=0.50,
        )
        item = plan.items[0]
        self.assertEqual(item.domain, "identity")
        self.assertEqual(item.decision, "suggest")

    def test_sensitive_health_blocks_auto_move(self):
        """Section 19: Health documents never auto-move."""
        files = [{"id": 1, "file_name": "Rekam_Medis_Pasien.pdf", "folder_id": 10}]
        plan = create_plan(
            files,
            [{"id": 41, "name": "Kesehatan", "parent_id": None}],
            auto_organize_enabled=True,
            min_confidence=0.50,
        )
        item = plan.items[0]
        self.assertEqual(item.domain, "health")
        self.assertEqual(item.decision, "suggest")

    def test_sensitive_legal_blocks_auto_move(self):
        """Section 19: Legal contracts never auto-move."""
        files = [{"id": 1, "file_name": "Surat_Perjanjian_Kontrak.pdf", "folder_id": 10}]
        plan = create_plan(
            files,
            [{"id": 42, "name": "Dokumen Hukum", "parent_id": None}],
            auto_organize_enabled=True,
            min_confidence=0.50,
        )
        item = plan.items[0]
        self.assertEqual(item.domain, "legal")
        self.assertEqual(item.decision, "suggest")

    def test_nested_folder_target_path_rendered(self):
        """Nested folder display path correctly populated in item.target_path."""
        folders = [
            {"id": 30, "name": "Kuliah", "parent_id": None},
            {"id": 31, "name": "Pemrograman Web", "parent_id": 30},
        ]
        files = [{"id": 1, "file_name": "Materi_Pemrograman_Web.pdf", "folder_id": 10}]
        plan = create_plan(files, folders)
        item = plan.items[0]
        self.assertEqual(item.target_folder_id, 31)
        self.assertEqual(item.target_path, "Kuliah / Pemrograman Web")



class TestRequiredSections23to28(unittest.TestCase):
    """Explicit compliance with Sections 23-28 required test cases."""

    def setUp(self):
        clear_audit_records()
        self.mock_db = MockDatabase()

    def test_section_23_perusahaan_corporat_pdf_mp4_lifecycle(self):
        """Section 23:
        Input: Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4
        Task 1: video
        Task 2A: media/movie
        Task 2B: Film
        Task 2C: SUGGEST -> Film. If auto=false: DO NOT MOVE. If user approves: MOVE.
        """
        filename = "Perusahaan.Corporat.PDF.2026.UHD.WEB-DL.MP4"
        self.mock_db.files[999] = {
            "id": 999,
            "file_name": filename,
            "user_id": 1,
            "folder_id": 10,
            "is_trashed": False,
            "updated_at": "2026-09-30T10:00:00Z",
        }
        folders = [
            {"id": 10, "name": "Inbox", "parent_id": None},
            {"id": 25, "name": "Film", "parent_id": None},
            {"id": 27, "name": "Office", "parent_id": None},
        ]

        # 1. Generate plan with auto_organize_enabled=False
        plan = create_plan(
            files=[self.mock_db.files[999]],
            folders=folders,
            auto_organize_enabled=False,
            user_id=1,
        )
        item = plan.items[0]

        # Verified suggestion targets Film, NOT Office
        self.assertEqual(item.target_folder_id, 25)
        self.assertEqual(item.target_folder_name, "Film")
        self.assertEqual(item.decision, "suggest")
        self.assertEqual(item.status, "planned")

        # Database state remains untouched before approval
        self.assertEqual(self.mock_db.files[999]["folder_id"], 10)

        # 2. User approves the move
        res = execute_item(
            item,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "executed")
        self.assertEqual(self.mock_db.files[999]["folder_id"], 25)

    def test_section_24_dry_run_leaves_database_untouched(self):
        """Section 24: Dry Run Test: before folder_id=10, dry_run=True -> folder_id remains 10."""
        file_obj = self.mock_db.files[102]
        self.assertEqual(file_obj["folder_id"], 10)

        folders = [
            {"id": 10, "name": "Inbox", "parent_id": None},
            {"id": 25, "name": "Film", "parent_id": None},
        ]
        plan = create_plan([file_obj], folders, dry_run=True, user_id=1)
        self.assertEqual(plan.items[0].target_folder_id, 25)

        # Confirm dry-run did not alter database
        self.assertEqual(self.mock_db.files[102]["folder_id"], 10)

    def test_section_25_user_approval_executes_move(self):
        """Section 25: User approves -> file.folder_id=25 with ownership & destination verified."""
        item = {
            "file_id": 102,
            "target_folder_id": 25,
            "source_folder_id": 10,
            "confidence": 0.98,
        }
        res = execute_item(
            item,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "executed")
        self.assertEqual(self.mock_db.files[102]["folder_id"], 25)

    def test_section_26_stale_plan_rejected(self):
        """Section 26: Stale Plan Test: file moved before approval -> rejected with stale_plan."""
        # Generate plan expecting file 101 to be in folder 10
        item = {
            "file_id": 101,
            "source_folder_id": 10,
            "target_folder_id": 26,
            "confidence": 0.95,
        }

        # User manually moves file 101 to folder 30 in the background
        self.mock_db.files[101]["folder_id"] = 30

        # Now user attempts to execute stale plan
        res = execute_item(
            item,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "stale_plan")
        self.assertIn("Stale plan", res["error"])
        # File folder remains 30, not corrupted to 26
        self.assertEqual(self.mock_db.files[101]["folder_id"], 30)

    def test_section_27_cross_user_attack_denied(self):
        """Section 27: Cross-User Attack Test:
        - Authenticated A: A_FILE -> B_FOLDER -> DENIED
        - Authenticated A: B_FILE -> A_FOLDER -> DENIED
        """
        # Attack 1: User 1 tries moving their own file 101 into Bob's folder 50
        res1 = execute_item(
            {"file_id": 101, "target_folder_id": 50, "source_folder_id": 10},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res1["success"])
        self.assertEqual(res1["status"], "unauthorized")
        self.assertEqual(self.mock_db.files[101]["folder_id"], 10, "A_FILE must not move to B_FOLDER")

        # Attack 2: User 1 tries moving Bob's file 201 into User 1's folder 26
        res2 = execute_item(
            {"file_id": 201, "target_folder_id": 26, "source_folder_id": 20},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res2["success"])
        self.assertEqual(res2["status"], "unauthorized")
        self.assertEqual(self.mock_db.files[201]["folder_id"], 20, "B_FILE must not move to A_FOLDER")

    def test_section_28_batch_attack_isolation(self):
        """Section 28: Batch Attack Test:
        Authenticated A requests [A1, A2, B1].
        Result: A1, A2 processed; B1 unauthorized. B1 is not touched.
        """
        batch_items = [
            {"file_id": 101, "target_folder_id": 26, "source_folder_id": 10},  # A1
            {"file_id": 102, "target_folder_id": 25, "source_folder_id": 10},  # A2
            {"file_id": 201, "target_folder_id": 26, "source_folder_id": 20},  # B1 (attacker target)
        ]

        batch_res = execute_batch(
            batch_items,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )

        self.assertFalse(batch_res["ok"], "Batch with unauthorized items must not return ok=True")
        self.assertEqual(len(batch_res["success"]), 2)
        self.assertEqual(len(batch_res["unauthorized"]), 1)
        self.assertEqual(batch_res["unauthorized"][0]["file_id"], 201)

        # Verify actual database state
        self.assertEqual(self.mock_db.files[101]["folder_id"], 26)
        self.assertEqual(self.mock_db.files[102]["folder_id"], 25)
        self.assertEqual(self.mock_db.files[201]["folder_id"], 20, "Foreign file 201 must not be modified")


class TestExecutionEdgeCasesAndAudit(unittest.TestCase):
    """Test idempotency, audit trail, missing parameters, and edge cases."""

    def setUp(self):
        clear_audit_records()
        self.mock_db = MockDatabase()

    def test_missing_authentication_denied(self):
        res = execute_item(
            {"file_id": 101, "target_folder_id": 26},
            user_id=0,  # Unauthenticated
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "unauthorized")

    def test_missing_item_parameters(self):
        res = execute_item(
            {"file_id": 0, "target_folder_id": None},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "invalid_request")

    def test_execute_trashed_file_rejected(self):
        res = execute_item(
            {"file_id": 103, "target_folder_id": 26, "source_folder_id": 10},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "in_trash")

    def test_idempotent_execution_already_in_target(self):
        res = execute_item(
            {"file_id": 104, "target_folder_id": 30, "source_folder_id": 30},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "already_in_target")

    def test_audit_logging_records_move_without_secrets(self):
        """Section 33: Audit logging records file move without leaking tokens."""
        item = {
            "file_id": 101,
            "target_folder_id": 26,
            "source_folder_id": 10,
            "confidence": 0.94,
            "reasons": ["Matched finance/invoice alias"],
        }
        res = execute_item(
            item,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["success"])

        records = get_audit_records(user_id=1)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["file_id"], 101)
        self.assertEqual(rec["user_id"], 1)
        self.assertEqual(rec["source_folder_id"], 10)
        self.assertEqual(rec["target_folder_id"], 26)
        self.assertEqual(rec["confidence"], 0.94)

        # Check no sensitive keys exist in audit log
        for secret_key in ("token", "session_token", "pin", "bot_token", "secret", "password"):
            self.assertNotIn(secret_key, rec)

    def test_database_move_failure_handled(self):
        """Handle unexpected DB failure gracefully."""
        def failing_move(file_id, folder_id, user_id=None):
            return False

        res = execute_item(
            {"file_id": 101, "target_folder_id": 26, "source_folder_id": 10},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=failing_move,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "failed")

    def test_preview_helper(self):
        files = [{"id": 101, "file_name": "Invoice.pdf", "folder_id": 10}]
        folders = [{"id": 26, "name": "Keuangan", "parent_id": None}]
        plan = preview(files, folders, user_id=1)
        self.assertTrue(plan.dry_run)
        self.assertEqual(len(plan.items), 1)
        self.assertEqual(plan.items[0].target_folder_id, 26)

    def test_batch_all_success_returns_ok_true(self):
        """Batch move where all items succeed returns ok=True."""
        batch_items = [
            {"file_id": 101, "target_folder_id": 26, "source_folder_id": 10},
            {"file_id": 102, "target_folder_id": 25, "source_folder_id": 10},
        ]
        res = execute_batch(
            batch_items,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["success"]), 2)
        self.assertEqual(len(res["failed"]), 0)
        self.assertEqual(len(res["unauthorized"]), 0)
        self.assertEqual(res["summary"]["moved"], 2)

    def test_batch_mixed_already_in_target_and_executed(self):
        """Batch with already-in-target items marks skipped and returns ok=True."""
        batch_items = [
            {"file_id": 104, "target_folder_id": 30, "source_folder_id": 30},  # already in 30
            {"file_id": 102, "target_folder_id": 25, "source_folder_id": 10},  # executes
        ]
        res = execute_batch(
            batch_items,
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["success"]), 1)
        self.assertEqual(len(res["skipped"]), 1)
        self.assertEqual(res["summary"]["moved"], 1)
        self.assertEqual(res["summary"]["skipped"], 1)

    def test_execute_batch_empty_items(self):
        """Empty batch executes cleanly."""
        res = execute_batch(
            [],
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["summary"]["total"], 0)

    def test_execute_item_folder_not_found(self):
        """Destination folder not found or foreign returns unauthorized."""
        res = execute_item(
            {"file_id": 101, "target_folder_id": 99999, "source_folder_id": 10},
            user_id=1,
            get_file_fn=self.mock_db.get_file,
            get_folder_fn=self.mock_db.get_folder,
            move_file_fn=self.mock_db.move_file,
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "unauthorized")



class TestBenchmarkAndDeterminism(unittest.TestCase):
    """Performance & determinism validation."""

    def test_determinism_identical_input_yields_identical_plan(self):
        files = [
            {"id": 1, "file_name": "Movie_01.mkv", "folder_id": 10},
            {"id": 2, "file_name": "KRS_2026.pdf", "folder_id": 10},
            {"id": 3, "file_name": "Receipt_March.pdf", "folder_id": 10},
        ]
        folders = [
            {"id": 25, "name": "Film", "parent_id": None},
            {"id": 26, "name": "Keuangan", "parent_id": None},
            {"id": 30, "name": "Kuliah", "parent_id": None},
        ]

        plan_a = create_plan(files, folders, user_id=1).to_dict()
        plan_b = create_plan(files, folders, user_id=1).to_dict()

        # Ignore auto-generated uuid plan_id and timestamps
        plan_a.pop("plan_id")
        plan_a.pop("created_at")
        plan_b.pop("plan_id")
        plan_b.pop("created_at")

        self.assertEqual(plan_a, plan_b)

    def test_1000_file_plan_generation_performance(self):
        """Section 30: 1000 plans must be generated rapidly in pure memory."""
        folders = [
            {"id": 1, "name": "Film", "parent_id": None},
            {"id": 2, "name": "Kuliah", "parent_id": None},
            {"id": 3, "name": "Keuangan", "parent_id": None},
            {"id": 4, "name": "Dokumen Kantor", "parent_id": None},
            {"id": 5, "name": "Foto Liburan", "parent_id": None},
        ]
        sample_names = [
            "Inception.2010.1080p.mkv",
            "Invoice_Server_2026.pdf",
            "Materi_Kuliah_Web.pdf",
            "Laporan_Bulanan_Kantor.xlsx",
            "IMG_20260315_Liburan.jpg",
        ]

        files = [
            {"id": i, "file_name": sample_names[i % len(sample_names)], "folder_id": 0}
            for i in range(1000)
        ]

        start_time = time.perf_counter()
        plan = create_plan(files, folders, user_id=1)
        elapsed = time.perf_counter() - start_time

        self.assertEqual(plan.total_files, 1000)
        self.assertLess(elapsed, 0.35, f"1000 files took {elapsed:.4f}s, expected < 0.35s")


if __name__ == "__main__":
    unittest.main()
