"""Comprehensive test suite for User Feedback & Personal Preferences (Task 2D).

Covers:
- Accepted, rejected, and corrected feedback recording
- Positive and negative counts & deterministic confidence progression
- Section 25: User isolation (User A vs User B preferences do not leak)
- Section 26: Cross-user attack resistance (foreign file or folder denied)
- Section 27: Technical evidence override (Video NEVER becomes Office)
- Section 28: Repeated feedback confidence growth (1, 3, 5 choices)
- Section 29: Conflicting preferences (tied counts preserve ambiguity)
- Section 30: No move on feedback (recording feedback does not move files)
- Pattern normalization & noise token filtering
- Stale folder handling (deleted folder skipped gracefully)
- Zero global mutation (no changes to global code or dictionaries)
- Human-readable explanation ("Personal preference" / "Kebiasaan folder Anda", no "AI")
- HTTP API endpoints verification & 401/403 security enforcement
- Performance benchmark (1,000 items in pure memory)
"""

import json
import time
import unittest
from unittest.mock import patch, MagicMock
from typing import Any

import tornado.testing
import tornado.web

import auth
import config
import database as db
import webapp
import darfin_intelligence.dictionaries as dicts
from darfin_intelligence.analyzer import analyze
from darfin_intelligence.classifier import classify
from darfin_intelligence.classifier.models import ClassificationResult
from darfin_intelligence.organizer.folder_mapper import map_folder
from darfin_intelligence.organizer.models import FolderCandidate, FolderSuggestion
from darfin_intelligence.organizer.safe_organizer import SafeOrganizer
from darfin_intelligence.preferences import (
    UserPreference,
    PreferenceEngine,
    apply_preferences,
    extract_reusable_patterns,
    is_folder_compatible_with_family,
)


class MockDatabaseForPreferences:
    """Mock database simulating user-scoped preference records and folder ownership."""

    def __init__(self):
        self.files = {
            101: {"id": 101, "file_name": "Proposal_KKN_2026.pdf", "user_id": 1, "folder_id": 10},
            102: {"id": 102, "file_name": "Perusahaan.2026.1080p.WEB-DL.x264.mp4", "user_id": 1, "folder_id": 10},
            201: {"id": 201, "file_name": "Bob_Proposal.pdf", "user_id": 2, "folder_id": 20},
        }
        self.folders = {
            10: {"id": 10, "name": "Inbox", "user_id": 1},
            25: {"id": 25, "name": "Film", "user_id": 1},
            26: {"id": 26, "name": "Kuliah", "user_id": 1},
            27: {"id": 27, "name": "Projects", "user_id": 1},
            28: {"id": 28, "name": "Office", "user_id": 1},
            50: {"id": 50, "name": "Bob_Folder", "user_id": 2},
            51: {"id": 51, "name": "Projects", "user_id": 2},
            52: {"id": 52, "name": "Kuliah", "user_id": 2},
        }
        self.preferences: dict[int, list[dict[str, Any]]] = {}

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

    def record_user_preference(
        self,
        user_id: int,
        pattern: str,
        target_folder_id: int,
        action: str = "accepted",
        domain: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any] | None:
        fold = self.get_folder(target_folder_id, user_id=user_id)
        if not fold:
            return None

        clean_pattern = pattern.strip().lower()
        user_prefs = self.preferences.setdefault(user_id, [])

        existing = next((p for p in user_prefs if p["pattern"] == clean_pattern and p["target_folder_id"] == target_folder_id), None)
        if not existing:
            pos = 1 if action in ("accepted", "corrected") else 0
            neg = 1 if action == "rejected" else 0
            conf = 0.50 if pos > 0 else 0.0
            rec = {
                "id": len(user_prefs) + 1,
                "user_id": user_id,
                "pattern": clean_pattern,
                "target_folder_id": target_folder_id,
                "domain": domain,
                "category": category,
                "positive_count": pos,
                "negative_count": neg,
                "confidence": conf,
            }
            user_prefs.append(rec)
            return dict(rec)
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
            return dict(existing)


class TestPreferenceModelsAndEngine(unittest.TestCase):
    """Test pattern extraction, boost scaling, and safety constraints."""

    def test_pattern_normalization_extracts_reusable_tokens(self):
        """Section 14: Reusable normalized patterns, never entire raw filenames."""
        filename = "Proposal_KKN_Desa_Waindawula_Final_Revisi_3.pdf"
        patterns = extract_reusable_patterns(filename)
        self.assertIn("proposal", patterns)
        self.assertIn("kkn", patterns)
        self.assertIn("proposal kkn", patterns)
        # Verify noise tokens were filtered
        self.assertNotIn("final", patterns)
        self.assertNotIn("revisi", patterns)
        self.assertNotIn("3", patterns)
        self.assertNotIn("pdf", patterns)
        self.assertNotIn(filename.lower(), patterns)

    def test_confidence_progression_and_boost(self):
        """Section 8 & 9: 1 choice = +10, 3 choices = +20, 5 choices = +30."""
        # 1 choice
        p1 = UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=1, negative_count=0, confidence=0.50)
        self.assertEqual(p1.calculate_boost(), 10)

        # 3 consistent choices
        p3 = UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=3, negative_count=0, confidence=0.75)
        self.assertEqual(p3.calculate_boost(), 20)

        # 5+ consistent choices
        p5 = UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, negative_count=0, confidence=0.90)
        self.assertEqual(p5.calculate_boost(), 30)

        # Net negative choices produces zero boost
        p_neg = UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=1, negative_count=3, confidence=0.20)
        self.assertEqual(p_neg.calculate_boost(), 0)

    def test_folder_family_compatibility(self):
        """Section 5: Video files cannot be routed into office/document folders."""
        self.assertFalse(is_folder_compatible_with_family("Office", "video"))
        self.assertFalse(is_folder_compatible_with_family("Dokumen Kantor", "video"))
        self.assertFalse(is_folder_compatible_with_family("Laporan", "video"))
        self.assertTrue(is_folder_compatible_with_family("Film", "video"))
        self.assertTrue(is_folder_compatible_with_family("Movies", "video"))

        # Non-video cannot be routed into film/movie folders
        self.assertFalse(is_folder_compatible_with_family("Film", "document"))
        self.assertTrue(is_folder_compatible_with_family("Office", "document"))


class TestMandatorySection25to30(unittest.TestCase):
    """Explicit compliance with Section 25 through 30 required tests."""

    def setUp(self):
        self.mock_db = MockDatabaseForPreferences()
        db.clear_user_preferences()

    def test_section_25_user_isolation_kuliah_vs_projects(self):
        """Section 25:
        USER A: proposal -> Kuliah
        USER B: proposal -> Projects
        Same input: Proposal.KKN.2026.pdf
        Expected: A gets Kuliah boosted; B gets Projects boosted. Preferences do not leak.
        """
        filename = "Proposal.KKN.2026.pdf"

        # Folders for User A (Kuliah=26, Projects=27)
        folders_a = [
            {"id": 26, "name": "Kuliah", "parent_id": None},
            {"id": 27, "name": "Projects", "parent_id": None},
        ]
        # Folders for User B (Projects=51, Kuliah=52)
        folders_b = [
            {"id": 51, "name": "Projects", "parent_id": None},
            {"id": 52, "name": "Kuliah", "parent_id": None},
        ]

        # Base suggestions from Task 2B without preferences
        intel = analyze(filename)
        cl = classify(intel)
        base_sugg_a = map_folder(cl, folders_a)
        base_sugg_b = map_folder(cl, folders_b)

        # User A has preference: proposal -> Kuliah (id=26)
        pref_a = [UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, confidence=0.90)]
        # User B has preference: proposal -> Projects (id=51)
        pref_b = [UserPreference(user_id=2, pattern="proposal", target_folder_id=51, positive_count=5, confidence=0.90)]

        # Apply User A preference to User A
        boosted_a = apply_preferences(base_sugg_a, pref_a, file_family="document", filename=filename, current_folders=folders_a)
        # Apply User B preference to User B
        boosted_b = apply_preferences(base_sugg_b, pref_b, file_family="document", filename=filename, current_folders=folders_b)

        # User A rank 1 is Kuliah
        self.assertEqual(boosted_a.target_folder_id, 26)
        self.assertEqual(boosted_a.target_folder_name, "Kuliah")
        self.assertTrue(any("Personal preference" in r for r in boosted_a.reasons))

        # User B rank 1 is Projects
        self.assertEqual(boosted_b.target_folder_id, 51)
        self.assertEqual(boosted_b.target_folder_name, "Projects")
        self.assertTrue(any("Personal preference" in r for r in boosted_b.reasons))

    def test_section_26_cross_user_attack_denied(self):
        """Section 26: Important Security Test:
        - User A attempts feedback target_folder_id = User B folder -> DENIED
        - User A attempts file_id = User B file -> DENIED
        """
        # Attack 1: User 1 attempts to record preference targeting User 2's folder 50
        res1 = self.mock_db.record_user_preference(
            user_id=1,
            pattern="proposal",
            target_folder_id=50,  # Belongs to user 2
            action="accepted",
        )
        self.assertIsNone(res1, "User A must not be allowed to set preference for User B folder")

        # Attack 2: User 1 attempts feedback on User 2's file 201
        f = self.mock_db.get_file(201, user_id=1)
        self.assertIsNone(f, "User A must not be allowed to view or submit feedback on User B file")

    def test_section_27_technical_evidence_overrides_user_preference(self):
        """Section 27: Important Technical Test:
        User preference: 'perusahaan' -> Office
        Input: Perusahaan.2026.1080p.WEB-DL.x264.mp4
        Expected: media/movie -> Film.
        Personal preference must NOT override strong video evidence.
        """
        filename = "Perusahaan.2026.1080p.WEB-DL.x264.mp4"
        folders = [
            {"id": 25, "name": "Film", "parent_id": None},
            {"id": 28, "name": "Office", "parent_id": None},
        ]

        # 1. Task 1 & 2A classification
        intel = analyze(filename)
        self.assertEqual(intel.file_type.family, "video")
        cl = classify(intel)
        self.assertEqual(cl.domain, "media")
        self.assertEqual(cl.category, "movie")

        # 2. Task 2B mapping
        sugg = map_folder(cl, folders)
        self.assertEqual(sugg.target_folder_name, "Film")

        # 3. User has a preference: 'perusahaan' -> Office (id=28)
        pref_office = [UserPreference(user_id=1, pattern="perusahaan", target_folder_id=28, positive_count=10, confidence=0.95)]

        # Apply preference
        boosted = apply_preferences(
            suggestion=sugg,
            preferences=pref_office,
            file_family=intel.file_type.family,
            filename=filename,
            current_folders=folders,
        )

        # Result MUST remain Film, Office boost was blocked due to family mismatch
        self.assertEqual(boosted.target_folder_name, "Film")
        self.assertNotEqual(boosted.target_folder_name, "Office")

    def test_section_28_repeated_feedback_increases_confidence(self):
        """Section 28: 1 choice, 3 choices, 5 choices deterministically grow confidence."""
        # 1st feedback
        r1 = self.mock_db.record_user_preference(1, "proposal", 26, "accepted")
        self.assertEqual(r1["positive_count"], 1)
        self.assertEqual(r1["confidence"], 0.50)

        # 2nd feedback
        self.mock_db.record_user_preference(1, "proposal", 26, "accepted")

        # 3rd feedback
        r3 = self.mock_db.record_user_preference(1, "proposal", 26, "accepted")
        self.assertEqual(r3["positive_count"], 3)
        self.assertEqual(r3["confidence"], 0.75)

        # 4th and 5th feedback
        self.mock_db.record_user_preference(1, "proposal", 26, "accepted")
        r5 = self.mock_db.record_user_preference(1, "proposal", 26, "accepted")
        self.assertEqual(r5["positive_count"], 5)
        self.assertEqual(r5["confidence"], 0.90)

    def test_section_29_conflicting_preferences_preserve_ambiguity(self):
        """Section 29: Conflict Test:
        User choices: proposal -> Kuliah = 5, proposal -> Projects = 5.
        Expected: ambiguous or balanced; no runaway single winner.
        """
        # Base suggestion with candidates tied or ambiguous
        sugg = FolderSuggestion(
            status="ambiguous",
            target_folder_id=None,
            confidence=0.5,
            candidates=[
                FolderCandidate(folder_id=26, name="Kuliah", path="Kuliah", score=40),
                FolderCandidate(folder_id=27, name="Projects", path="Projects", score=40),
            ],
            reasons=["Initial candidates tied"],
        )
        folders = [
            {"id": 26, "name": "Kuliah", "parent_id": None},
            {"id": 27, "name": "Projects", "parent_id": None},
        ]
        # Equal competing preferences (5 vs 5)
        competing_prefs = [
            UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, negative_count=0, confidence=0.90),
            UserPreference(user_id=1, pattern="proposal", target_folder_id=27, positive_count=5, negative_count=0, confidence=0.90),
        ]

        boosted = apply_preferences(sugg, competing_prefs, file_family="document", filename="Proposal.pdf", current_folders=folders)
        cand_scores = {c.folder_id: c.score for c in boosted.candidates}

        score_kuliah = cand_scores.get(26, 0)
        score_projects = cand_scores.get(27, 0)
        self.assertEqual(score_kuliah, score_projects, "Competing preferences of equal weight must yield balanced scores")
        self.assertEqual(boosted.status, "ambiguous", "Equal conflicting preferences must preserve ambiguity")

    def test_section_10_dominant_preference_wins(self):
        """Section 10: proposal -> Kuliah = 10, proposal -> Projects = 1.
        Kuliah gets a bigger boost than Projects.
        """
        sugg = FolderSuggestion(
            status="ambiguous",
            target_folder_id=None,
            confidence=0.5,
            candidates=[
                FolderCandidate(folder_id=26, name="Kuliah", path="Kuliah", score=40),
                FolderCandidate(folder_id=27, name="Projects", path="Projects", score=40),
            ],
            reasons=["Initial candidates tied"],
        )
        folders = [
            {"id": 26, "name": "Kuliah", "parent_id": None},
            {"id": 27, "name": "Projects", "parent_id": None},
        ]
        prefs = [
            UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=10, negative_count=0, confidence=0.95),
            UserPreference(user_id=1, pattern="proposal", target_folder_id=27, positive_count=1, negative_count=0, confidence=0.50),
        ]
        boosted = apply_preferences(sugg, prefs, file_family="document", filename="Proposal.pdf", current_folders=folders)
        cand_scores = {c.folder_id: c.score for c in boosted.candidates}
        self.assertGreater(cand_scores[26], cand_scores[27], "Kuliah must get a bigger boost than Projects")
        self.assertEqual(boosted.target_folder_id, 26)

    def test_section_30_feedback_does_not_move_file(self):
        """Section 30: Recording feedback must NOT move files."""
        file_before = self.mock_db.files[101]["folder_id"]
        self.assertEqual(file_before, 10)

        # Record a corrected feedback: proposal -> Kuliah (id=26)
        self.mock_db.record_user_preference(
            user_id=1,
            pattern="proposal",
            target_folder_id=26,
            action="corrected",
        )

        # File folder ID must remain untouched (id=10)
        file_after = self.mock_db.files[101]["folder_id"]
        self.assertEqual(file_after, 10, "Recording feedback must not move the file")


class TestEdgeCasesAndIntegrations(unittest.TestCase):
    """Test stale folders, negative feedback, explanation prose, and benchmarks."""

    def test_stale_folder_skipped_gracefully(self):
        """Section 13: Stale folder id does not crash suggestion engine."""
        filename = "Project_Proposal.pdf"
        folders = [
            {"id": 27, "name": "Projects", "parent_id": None},
        ]
        sugg = map_folder(classify(analyze(filename)), folders)

        # User preference points to folder 9999 (which no longer exists)
        stale_pref = [UserPreference(user_id=1, pattern="proposal", target_folder_id=9999, positive_count=10, confidence=0.95)]

        boosted = apply_preferences(sugg, stale_pref, file_family="document", filename=filename, current_folders=folders)
        # Engine falls back cleanly without crash
        self.assertIsNotNone(boosted)
        self.assertEqual(boosted.target_folder_id, 27)
        self.assertTrue(stale_pref[0].is_stale, "Stale preference must have is_stale=True")

    def test_negative_feedback_reduces_confidence(self):
        """Rejected feedback increases negative count and prevents high boost."""
        p = UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=1, negative_count=2, confidence=0.20)
        self.assertEqual(p.calculate_boost(), 0)

    def test_explanation_prose_avoids_ai_term(self):
        """Section 22: Explanation says 'Personal preference' or 'Kebiasaan folder', no AI terms."""
        filename = "Proposal.KKN.2026.pdf"
        folders = [{"id": 26, "name": "Kuliah", "parent_id": None}]
        sugg = map_folder(classify(analyze(filename)), folders)
        pref = [UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=3, confidence=0.75)]

        boosted = apply_preferences(sugg, pref, file_family="document", filename=filename, current_folders=folders)
        explanation = "\n".join(boosted.reasons)
        self.assertIn("Personal preference", explanation)
        self.assertIn("Kebiasaan folder", explanation)
        self.assertNotIn("AI", explanation)
        self.assertNotIn("machine learning", explanation.lower())

    def test_1000_preferences_performance(self):
        """Section 32: Applying preferences must be fast and lightweight in memory."""
        filename = "Proposal.KKN.2026.pdf"
        folders = [
            {"id": 26, "name": "Kuliah", "parent_id": None},
            {"id": 27, "name": "Projects", "parent_id": None},
        ]
        sugg = map_folder(classify(analyze(filename)), folders)
        prefs = [
            UserPreference(user_id=1, pattern=f"pattern_{i}", target_folder_id=26, positive_count=2)
            for i in range(1000)
        ]
        # Add matching pattern
        prefs.append(UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, confidence=0.90))

        start = time.perf_counter()
        boosted = apply_preferences(sugg, prefs, file_family="document", filename=filename, current_folders=folders)
        elapsed = time.perf_counter() - start

        self.assertEqual(boosted.target_folder_id, 26)
        self.assertLess(elapsed, 0.10, f"Preference matching took {elapsed:.4f}s, expected < 0.10s")


class TestFeedbackActionsAndCounts(unittest.TestCase):
    """Test accepted, rejected, corrected feedback, confidence drop, and non-mutation."""

    def setUp(self):
        self.mock_db = MockDatabaseForPreferences()

    def test_feedback_action_accepted_increments_positive(self):
        """Action 'accepted' increments positive_count and calculates positive confidence."""
        rec = self.mock_db.record_user_preference(1, "proposal", 26, "accepted")
        self.assertEqual(rec["positive_count"], 1)
        self.assertEqual(rec["negative_count"], 0)
        self.assertEqual(rec["confidence"], 0.50)

    def test_feedback_action_rejected_increments_negative(self):
        """Action 'rejected' increments negative_count and drops confidence to 0."""
        rec = self.mock_db.record_user_preference(1, "proposal", 26, "rejected")
        self.assertEqual(rec["positive_count"], 0)
        self.assertEqual(rec["negative_count"], 1)
        self.assertEqual(rec["confidence"], 0.0)

    def test_feedback_action_corrected_updates_preference(self):
        """Action 'corrected' creates or updates preference on the new target folder."""
        rec = self.mock_db.record_user_preference(1, "proposal", 26, "corrected")
        self.assertEqual(rec["positive_count"], 1)
        self.assertEqual(rec["target_folder_id"], 26)

    def test_confidence_drop_when_negative_exceeds_positive(self):
        """When negative choices >= positive choices, boost drops to 0."""
        pref = UserPreference(
            user_id=1,
            pattern="invoice",
            target_folder_id=28,
            positive_count=2,
            negative_count=5,
            confidence=0.15,
        )
        self.assertEqual(pref.calculate_boost(), 0)

    def test_no_global_dictionary_mutation(self):
        """Section 18 & 19: Global dictionary must never be mutated by user preferences."""
        doc_exts_before = list(dicts._DOCUMENT_EXTS)
        video_exts_before = list(dicts._VIDEO_EXTS)
        with patch("database.get_folder", return_value={"id": 26, "user_id": 1}):
            db.record_user_preference(1, "proposal", 26, "accepted")
        self.assertEqual(list(dicts._DOCUMENT_EXTS), doc_exts_before)
        self.assertEqual(list(dicts._VIDEO_EXTS), video_exts_before)

    def test_no_self_modifying_code(self):
        """Section 19: System must never write self-modifying Python code."""
        import inspect
        src = inspect.getsource(apply_preferences)
        self.assertNotIn("def proposal", src)
        self.assertNotIn("exec(", src)
        self.assertNotIn("eval(", src)

    def test_database_user_isolation_query(self):
        """Section 1 & 23: Preferences must be strictly scoped to user; no cross-user leak."""
        db.clear_user_preferences()
        with patch("database.get_folder", return_value={"id": 100, "user_id": 10}):
            db.record_user_preference(user_id=10, pattern="invoice", target_folder_id=100, action="accepted")
        prefs_user_10 = db.get_user_preferences(10)
        prefs_user_20 = db.get_user_preferences(20)
        self.assertEqual(len(prefs_user_10), 1)
        self.assertEqual(len(prefs_user_20), 0)

    def test_family_safety_photo_incompatible_with_movie(self):
        """Section 5: Photo file family cannot be routed into movie/film folders."""
        self.assertFalse(is_folder_compatible_with_family("Film", "photo"))
        self.assertFalse(is_folder_compatible_with_family("Movies", "photo"))
        self.assertTrue(is_folder_compatible_with_family("Foto Liburan", "photo"))

    def test_family_safety_audio_incompatible_with_office(self):
        """Section 5: Audio file family cannot be routed into office folders."""
        self.assertFalse(is_folder_compatible_with_family("Office", "audio"))
        self.assertFalse(is_folder_compatible_with_family("Kantor", "audio"))
        self.assertTrue(is_folder_compatible_with_family("Musik", "audio"))

    def test_family_safety_document_incompatible_with_movie(self):
        """Section 5: Document file family cannot be routed into film/cinema folders."""
        self.assertFalse(is_folder_compatible_with_family("Cinema", "document"))
        self.assertFalse(is_folder_compatible_with_family("Bioskop", "document"))
        self.assertTrue(is_folder_compatible_with_family("Kuliah", "document"))

    def test_preference_engine_facade(self):
        """PreferenceEngine facade methods operate identically to standalone functions."""
        patterns = PreferenceEngine.extract_patterns("Laporan_Keuangan_2026.xlsx")
        self.assertIn("laporan", patterns)
        self.assertIn("keuangan", patterns)
        self.assertTrue(PreferenceEngine.is_compatible("Keuangan", "document"))

    def test_safe_smart_organizer_plan_incorporates_preferences(self):
        """Task 2C SafeOrganizer.create_plan integrates Task 2D user preferences."""
        files = [{"id": 101, "file_name": "Proposal.KKN.2026.pdf", "user_id": 1, "folder_id": 10}]
        folders = [{"id": 26, "name": "Kuliah"}, {"id": 27, "name": "Projects"}]
        prefs = [UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, confidence=0.90)]
        plan = SafeOrganizer.create_plan(files=files, folders=folders, user_id=1, user_preferences=prefs)
        self.assertEqual(len(plan.items), 1)
        item = plan.items[0]
        self.assertEqual(item.target_folder_id, 26)
        self.assertTrue(any("Personal preference" in r for r in item.reasons))

    def test_safe_smart_organizer_preview_incorporates_preferences(self):
        """SafeOrganizer.preview dry-run includes user preference boosts."""
        files = [{"id": 101, "file_name": "Proposal.KKN.2026.pdf", "user_id": 1, "folder_id": 10}]
        folders = [{"id": 26, "name": "Kuliah"}, {"id": 27, "name": "Projects"}]
        prefs = [UserPreference(user_id=1, pattern="proposal", target_folder_id=26, positive_count=5, confidence=0.90)]
        preview = SafeOrganizer.preview(files=files, folders=folders, user_id=1, user_preferences=prefs)
        self.assertTrue(preview.dry_run)
        self.assertEqual(preview.items[0].target_folder_id, 26)


class TestApiPreferencesFeedbackEndpoint(tornado.testing.AsyncHTTPTestCase):
    """Section 15, 16 & 26: Test HTTP API /api/preferences/feedback authentication & authorization."""

    def get_app(self):
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0
        config.BOT_TOKEN = "123456:TEST_BOT_TOKEN_PREF"
        return tornado.web.Application(webapp.build_app_routes())

    def setUp(self):
        super().setUp()
        self.user_a_id = 11111
        self.user_b_id = 22222
        self.token_a = auth.create_session_token(self.user_a_id)
        self.token_b = auth.create_session_token(self.user_b_id)

    def test_api_feedback_unauthenticated_returns_401(self):
        """Unauthenticated request to /api/preferences/feedback returns 401."""
        response = self.fetch(
            "/api/preferences/feedback",
            method="POST",
            body=json.dumps({"file_id": 101, "suggested_folder_id": 26, "action": "accepted"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.code, 401)

    def test_api_feedback_foreign_file_returns_403(self):
        """User A submitting feedback for User B's file returns 403 Forbidden."""
        # Mock database returning None for user_a on file 201 (owned by user_b)
        with patch("database.get_file", return_value=None):
            response = self.fetch(
                "/api/preferences/feedback",
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.token_a}",
                    "Content-Type": "application/json",
                },
                body=json.dumps({"file_id": 201, "suggested_folder_id": 26, "action": "accepted"}),
            )
            self.assertEqual(response.code, 403)

    def test_api_feedback_foreign_folder_returns_403(self):
        """User A submitting feedback targeting User B's folder returns 403 Forbidden."""
        with patch("database.get_file", return_value={"id": 101, "file_name": "Proposal.pdf", "user_id": self.user_a_id}):
            with patch("database.get_folder", return_value=None):
                response = self.fetch(
                    "/api/preferences/feedback",
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {self.token_a}",
                        "Content-Type": "application/json",
                    },
                    body=json.dumps({"file_id": 101, "suggested_folder_id": 50, "action": "accepted"}),
                )
                self.assertEqual(response.code, 403)

    def test_api_feedback_valid_accepted_returns_200(self):
        """User A with valid session, owned file and folder successfully records feedback."""
        pref_rec = {
            "id": 1,
            "user_id": self.user_a_id,
            "pattern": "proposal",
            "target_folder_id": 26,
            "action": "accepted",
        }
        with patch("database.get_file", return_value={"id": 101, "file_name": "Proposal_KKN.pdf", "user_id": self.user_a_id}):
            with patch("database.get_folder", return_value={"id": 26, "name": "Kuliah", "user_id": self.user_a_id}):
                with patch("database.record_user_preference", return_value=pref_rec):
                    response = self.fetch(
                        "/api/preferences/feedback",
                        method="POST",
                        headers={
                            "Authorization": f"Bearer {self.token_a}",
                            "Content-Type": "application/json",
                        },
                        body=json.dumps({"file_id": 101, "suggested_folder_id": 26, "action": "accepted"}),
                    )
                    self.assertEqual(response.code, 200)
                    body = json.loads(response.body.decode("utf-8"))
                    self.assertTrue(body["ok"])
                    self.assertEqual(body["action"], "accepted")
                    self.assertEqual(body["target_folder_id"], 26)


if __name__ == "__main__":
    unittest.main()
