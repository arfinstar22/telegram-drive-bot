"""Unit and Integration Test Suite for Darfin Search Intelligence Core (Task 4).

Tests deterministic lexical + metadata search, ranking, multi-signal scoring,
filters, fuzzy matching, privacy protections, IDOR isolation, and robustness.
"""

import unittest
from datetime import datetime, timezone, timedelta

from darfin_intelligence.search import (
    SearchService,
    SearchFilters,
    SearchQuery,
    SearchMatch,
    SearchResult,
    search,
    search_files,
    parse_query,
)
from darfin_intelligence.search.fuzzy import fuzzy_match_token, levenshtein_distance
from darfin_intelligence.search.normalizer import (
    normalize_search_string,
    normalize_token,
    canonical_alias,
    parse_size_str,
    parse_amount_number,
)


class TestSearchIntelligence(unittest.TestCase):
    """Test suite covering all Task 4 requirements."""

    def setUp(self):
        self.service = SearchService(db_module=None)
        self.user_id = 1001

        # Standard sample assets belonging to user 1001
        self.sample_assets = [
            {
                "id": 1,
                "user_id": 1001,
                "file_name": "Kupilih.Jalur.Langit.2026.1080p.WEB.DL.x264.mkv",
                "file_type": "video",
                "file_size": 1500000000,
                "mime_type": "video/x-matroska",
                "folder_id": 10,
                "folders": {"name": "Movies", "path": "Media/Movies"},
                "created_at": "2026-09-20T10:00:00Z",
                "domain": "media",
                "category": "movie",
            },
            {
                "id": 2,
                "user_id": 1001,
                "file_name": "Laporan_Keuangan_Q3_2026.pdf",
                "file_type": "document",
                "file_size": 2500000,
                "mime_type": "application/pdf|NOTE:Laporan resmi kuartal 3|TAGS:finance,q3,audit",
                "folder_id": 20,
                "folders": {"name": "Finance", "path": "Office/Finance"},
                "created_at": "2026-09-25T14:30:00Z",
                "domain": "finance",
                "category": "report",
            },
            {
                "id": 3,
                "user_id": 1001,
                "file_name": "Struk_Belanja_Indomaret.jpg",
                "file_type": "photo",
                "file_size": 850000,
                "mime_type": "image/jpeg",
                "folder_id": 30,
                "folders": {"name": "Receipts", "path": "Finance/Receipts"},
                "created_at": "2026-09-28T09:15:00Z",
                "ocr_text": "INDOMARET JL. RAYA SUDIRMAN TOTAL 25.000 TUNAI 50.000 KEMBALIAN 25.000",
                "ocr_confidence": 0.95,
                "screenshot_category": "receipt_candidate",
                "merchant_name": "Indomaret",
                "total_amount": 25000.0,
                "payment_method": "cash",
                "receipt_number": "REC-9912",
            },
            {
                "id": 4,
                "user_id": 1001,
                "file_name": "KRS_Semester_5_Teknik_Informatika.pdf",
                "file_type": "document",
                "file_size": 420000,
                "mime_type": "application/pdf|TAGS:kuliah,krs,semester5",
                "folder_id": 40,
                "folders": {"name": "Kuliah", "path": "Kuliah/Semester 5/KRS"},
                "created_at": "2026-09-10T08:00:00Z",
                "domain": "education",
                "category": "krs",
                "document_type": "academic_document",
            },
            {
                "id": 5,
                "user_id": 1001,
                "file_name": "Surat_Undangan_Rapat_Dinas.pdf",
                "file_type": "document",
                "file_size": 650000,
                "mime_type": "application/pdf",
                "folder_id": 50,
                "folders": {"name": "Surat", "path": "Office/Surat"},
                "created_at": "2026-09-29T11:00:00Z",
                "document_type": "official_letter",
                "document_number": "421/DP-01/IX/2026",
                "subject": "Undangan Rapat Koordinasi",
            },
            {
                "id": 6,
                "user_id": 1001,
                "file_name": "Screenshot_Chat_Rapat.png",
                "file_type": "photo",
                "file_size": 950000,
                "mime_type": "image/png",
                "folder_id": 60,
                "folders": {"name": "Screenshots", "path": "Screenshots"},
                "created_at": "2026-09-29T16:00:00Z",
                "ocr_text": "Budi: Rapat besok pukul 10:00 jangan lupa bawa materi",
                "ocr_confidence": 0.88,
                "screenshot_category": "reminder",
            },
            {
                "id": 7,
                "user_id": 1001,
                "file_name": "Low_Quality_Scan.png",
                "file_type": "photo",
                "file_size": 320000,
                "mime_type": "image/png",
                "folder_id": 60,
                "folders": {"name": "Screenshots", "path": "Screenshots"},
                "created_at": "2026-09-01T12:00:00Z",
                "ocr_text": "T0TAL b4y4r rp 15.000",
                "ocr_confidence": 0.25,
            },
            {
                "id": 8,
                "user_id": 1001,
                "file_name": "Old_Archive_Backup.zip",
                "file_type": "archive",
                "file_size": 50000000,
                "mime_type": "application/zip",
                "folder_id": 70,
                "folders": {"name": "Backups", "path": "Archive/Backups"},
                "created_at": "2025-01-10T00:00:00Z",
            },
        ]

    # ── Basic Search (Tests 1-10) ──────────────────────────

    def test_01_exact_filename(self):
        res = self.service.search(self.user_id, "Kupilih.Jalur.Langit.2026.1080p.WEB.DL.x264.mkv", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)
        self.assertIn("file_name_exact", res.items[0].matched_fields)
        self.assertGreaterEqual(res.items[0].score, 100.0)

    def test_02_case_insensitive(self):
        res = self.service.search(self.user_id, "kupilih jalur langit", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_03_punctuation_insensitive(self):
        res = self.service.search(self.user_id, "Kupilih - Jalur: Langit!", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_04_multi_token_filename(self):
        res = self.service.search(self.user_id, "jalur langit 1080p", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)
        self.assertGreater(res.items[0].score, 100.0)

    def test_05_partial_filename(self):
        res = self.service.search(self.user_id, "Keuangan_Q3", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 2)

    def test_06_extension_search(self):
        res = self.service.search(self.user_id, "ext:pdf", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        for item in res.items:
            self.assertTrue(item.file_data["file_name"].endswith(".pdf"))

    def test_07_mime_search(self):
        filters = SearchFilters(mime_type="video/")
        res = self.service.search(self.user_id, "", filters=filters, assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        for item in res.items:
            self.assertEqual(item.file_data["file_type"], "video")

    def test_08_empty_query(self):
        res = self.service.search(self.user_id, "", assets=self.sample_assets)
        self.assertEqual(res.total_results, len(self.sample_assets))
        # Empty query sorts deterministically (newest first, id 6 is 2026-09-29T16:00:00Z)
        self.assertEqual(res.items[0].asset_id, 6)

    def test_09_pagination(self):
        res_page1 = self.service.search(self.user_id, "", limit=3, offset=0, assets=self.sample_assets)
        self.assertEqual(len(res_page1.items), 3)
        self.assertEqual(res_page1.total_results, len(self.sample_assets))

        res_page2 = self.service.search(self.user_id, "", limit=3, offset=3, assets=self.sample_assets)
        self.assertEqual(len(res_page2.items), 3)

        # Disjoint pages
        ids1 = {m.asset_id for m in res_page1.items}
        ids2 = {m.asset_id for m in res_page2.items}
        self.assertEqual(len(ids1.intersection(ids2)), 0)

    def test_10_deterministic_ordering(self):
        res1 = self.service.search(self.user_id, "pdf", assets=self.sample_assets)
        res2 = self.service.search(self.user_id, "pdf", assets=self.sample_assets)
        self.assertEqual([m.asset_id for m in res1.items], [m.asset_id for m in res2.items])

    # ── Media (Tests 11-18) ────────────────────────────────

    def test_11_media_1080p(self):
        res = self.service.search(self.user_id, "1080p", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_12_media_720p_query(self):
        sample = [{"id": 99, "user_id": 1001, "file_name": "Naruto.E100.720p.HDTV.mkv", "file_type": "video"}]
        res = self.service.search(self.user_id, "720p", assets=sample)
        self.assertEqual(res.total_results, 1)
        self.assertIn("file_name_token", res.items[0].matched_fields)

    def test_13_media_web_dl(self):
        res = self.service.search(self.user_id, "web-dl", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_14_media_x264(self):
        res = self.service.search(self.user_id, "x264", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_15_media_x265_hevc_alias(self):
        sample = [{"id": 98, "user_id": 1001, "file_name": "Movie.2026.HEVC.mp4", "file_type": "video"}]
        res = self.service.search(self.user_id, "x265", assets=sample)
        self.assertEqual(res.total_results, 1)

    def test_16_media_episode_season(self):
        sample = [{"id": 97, "user_id": 1001, "file_name": "Attack.on.Titan.S02E03.1080p.mkv", "file_type": "video"}]
        res = self.service.search(self.user_id, "S02E03", assets=sample)
        self.assertEqual(res.items[0].asset_id, 97)

    def test_17_movie_keyword(self):
        res = self.service.search(self.user_id, "film", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_18_series_keyword(self):
        sample = [{"id": 96, "user_id": 1001, "file_name": "Stranger.Things.Series.1080p.mkv", "file_type": "video"}]
        res = self.service.search(self.user_id, "series", assets=sample)
        self.assertEqual(res.items[0].asset_id, 96)

    # ── Domain (Tests 19-24) ───────────────────────────────

    def test_19_domain_education(self):
        res = self.service.search(self.user_id, "kuliah", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 4)

    def test_20_domain_finance(self):
        res = self.service.search(self.user_id, "domain:finance", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        for item in res.items:
            self.assertEqual(item.file_data.get("domain"), "finance")

    def test_21_domain_project(self):
        sample = [{"id": 95, "user_id": 1001, "file_name": "Project_Proposal.pdf", "file_type": "document", "domain": "project"}]
        res = self.service.search(self.user_id, "domain:project", assets=sample)
        self.assertEqual(res.total_results, 1)

    def test_22_domain_media(self):
        res = self.service.search(self.user_id, "domain:media", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 1)

    def test_23_domain_office(self):
        res = self.service.search(self.user_id, "surat", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertIn(res.items[0].asset_id, (5,))

    def test_24_classification_aware_ranking(self):
        # A file with domain=finance should rank high for finance query
        res = self.service.search(self.user_id, "finance", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 2)

    # ── Folder Context (Tests 25-28) ───────────────────────

    def test_25_folder_name(self):
        res = self.service.search(self.user_id, "folder:Kuliah", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 4)

    def test_26_nested_folder(self):
        res = self.service.search(self.user_id, "folder:\"Semester 5\"", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 4)

    def test_27_folder_path(self):
        res = self.service.search(self.user_id, "Office Surat", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 5)

    def test_28_folder_context_ranking(self):
        # "Receipts" in folder path should match Struk Indomaret
        res = self.service.search(self.user_id, "Receipts", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 3)

    # ── OCR / Screenshot (Tests 29-35) ─────────────────────

    def test_29_ocr_text_match(self):
        res = self.service.search(self.user_id, "sudirman", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 3)
        self.assertIn("ocr_text", res.items[0].matched_fields)

    def test_30_low_ocr_confidence_dampening(self):
        # Low quality scan OCR should score lower than high quality
        res = self.service.search(self.user_id, "b4y4r", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertLess(res.items[0].confidence, 0.5)

    def test_31_screenshot_category_search(self):
        res = self.service.search(self.user_id, "receipt_candidate", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 3)

    def test_32_reminder_search(self):
        res = self.service.search(self.user_id, "reminder", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 6)

    def test_33_conversation_search(self):
        sample = [{"id": 94, "user_id": 1001, "file_name": "Chat.png", "file_type": "photo", "screenshot_category": "conversation"}]
        res = self.service.search(self.user_id, "conversation", assets=sample)
        self.assertEqual(res.items[0].asset_id, 94)

    def test_34_webpage_search(self):
        sample = [{"id": 93, "user_id": 1001, "file_name": "Web.png", "file_type": "photo", "screenshot_category": "webpage"}]
        res = self.service.search(self.user_id, "webpage", assets=sample)
        self.assertEqual(res.items[0].asset_id, 93)

    def test_35_code_search(self):
        sample = [{"id": 92, "user_id": 1001, "file_name": "Error.png", "file_type": "photo", "screenshot_category": "code"}]
        res = self.service.search(self.user_id, "code", assets=sample)
        self.assertEqual(res.items[0].asset_id, 92)

    # ── Receipt & Document (Tests 36-43) ───────────────────

    def test_36_merchant_search(self):
        res = self.service.search(self.user_id, "merchant:Indomaret", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 3)

    def test_37_receipt_number(self):
        res = self.service.search(self.user_id, "REC-9912", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 3)

    def test_38_total_amount(self):
        res = self.service.search(self.user_id, "25000", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 3)

    def test_39_payment_method(self):
        res = self.service.search(self.user_id, "method:cash", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 3)

    def test_40_invoice_number(self):
        sample = [{"id": 91, "user_id": 1001, "file_name": "Invoice.pdf", "file_type": "document", "receipt_number": "INV-2026-001"}]
        res = self.service.search(self.user_id, "INV-2026-001", assets=sample)
        self.assertEqual(res.items[0].asset_id, 91)

    def test_41_document_number(self):
        res = self.service.search(self.user_id, "421/DP-01/IX/2026", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 5)

    def test_42_subject_perihal(self):
        res = self.service.search(self.user_id, "Koordinasi", assets=self.sample_assets)
        self.assertEqual(res.items[0].asset_id, 5)

    def test_43_academic_document(self):
        res = self.service.search(self.user_id, "document:academic_document", assets=self.sample_assets)
        self.assertEqual(res.total_results, 1)
        self.assertEqual(res.items[0].asset_id, 4)

    # ── Fuzzy Matching (Tests 44-46) ───────────────────────

    def test_44_fuzzy_small_typo(self):
        # "indomarett" (typo) should match Indomaret via fuzzy
        res = self.service.search(self.user_id, "indomarett", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 3)
        self.assertIn("fuzzy_match", res.items[0].matched_fields)

    def test_45_fuzzy_score_lower_than_exact(self):
        sample = [
            {"id": 101, "user_id": 1001, "file_name": "indomaret.pdf", "file_type": "document"},
            {"id": 102, "user_id": 1001, "file_name": "indomarett.pdf", "file_type": "document"},
        ]
        res = self.service.search(self.user_id, "indomaret", assets=sample)
        self.assertEqual(res.items[0].asset_id, 101)  # Exact match ranks first
        self.assertGreater(res.items[0].score, res.items[1].score)

    def test_46_fuzzy_threshold_rejection(self):
        # "indonesia" vs "indomaret": similarity is too low (< 0.80), should not match
        res = self.service.search(self.user_id, "indonesia", assets=self.sample_assets)
        matching_ids = [m.asset_id for m in res.items]
        self.assertNotIn(3, matching_ids)

    # ── Ranking Mechanics (Tests 47-51) ────────────────────

    def test_47_filename_beats_weak_ocr(self):
        sample = [
            {"id": 201, "user_id": 1001, "file_name": "Sudirman_Project.pdf", "file_type": "document"},
            {"id": 202, "user_id": 1001, "file_name": "Receipt.jpg", "file_type": "photo", "ocr_text": "jl sudirman", "ocr_confidence": 0.5},
        ]
        res = self.service.search(self.user_id, "sudirman", assets=sample)
        self.assertEqual(res.items[0].asset_id, 201)

    def test_48_exact_beats_fuzzy(self):
        sample = [
            {"id": 203, "user_id": 1001, "file_name": "Laporan_Tahunan.pdf", "file_type": "document"},
            {"id": 204, "user_id": 1001, "file_name": "Laporan_Tahunann.pdf", "file_type": "document"},
        ]
        res = self.service.search(self.user_id, "Tahunan", assets=sample)
        self.assertEqual(res.items[0].asset_id, 203)

    def test_49_strong_metadata_beats_weak_token(self):
        sample = [
            {"id": 205, "user_id": 1001, "file_name": "file1.pdf", "file_type": "document", "domain": "finance", "tags": ["finance"]},
            {"id": 206, "user_id": 1001, "file_name": "random_finance_note.txt", "file_type": "document", "domain": "other"},
        ]
        res = self.service.search(self.user_id, "finance", assets=sample)
        # file1 has domain + tag match = 75 pts, file2 has token match = 50 pts
        self.assertEqual(res.items[0].asset_id, 205)

    def test_50_recency_cannot_overpower_strong_relevance(self):
        sample = [
            {"id": 207, "user_id": 1001, "file_name": "Invoice_Super_Exact.pdf", "file_type": "document", "created_at": "2020-01-01T00:00:00Z"},
            {"id": 208, "user_id": 1001, "file_name": "Brand_New_File.pdf", "file_type": "document", "created_at": "2026-09-30T12:00:00Z", "note": "invoice"},
        ]
        res = self.service.search(self.user_id, "Invoice Super Exact", assets=sample)
        self.assertEqual(res.items[0].asset_id, 207)

    def test_51_deterministic_tie_break(self):
        sample = [
            {"id": 301, "user_id": 1001, "file_name": "report.pdf", "file_type": "document", "created_at": "2026-09-01T00:00:00Z"},
            {"id": 302, "user_id": 1001, "file_name": "report.pdf", "file_type": "document", "created_at": "2026-09-01T00:00:00Z"},
        ]
        res = self.service.search(self.user_id, "report", assets=sample)
        self.assertEqual(len(res.items), 2)
        # Tie-breaker is stable: same score and created_at -> asset_id DESC
        self.assertEqual(res.items[0].asset_id, 302)
        self.assertEqual(res.items[1].asset_id, 301)

    # ── Security & Adversarial (Tests 52-57) ────────────────

    def test_52_user_isolation(self):
        # User 1002 searches: should not see user 1001's files
        res = self.service.search(1002, "Kupilih", assets=self.sample_assets)
        self.assertEqual(res.total_results, 0)

    def test_53_cross_user_file_cannot_appear(self):
        mixed = list(self.sample_assets) + [
            {"id": 999, "user_id": 2002, "file_name": "Secret_User2_File.pdf", "file_type": "document"}
        ]
        res = self.service.search(1001, "Secret", assets=mixed)
        self.assertEqual(res.total_results, 0)

    def test_54_cross_user_folder_cannot_appear(self):
        mixed = [
            {"id": 998, "user_id": 2002, "file_name": "Doc.pdf", "folders": {"name": "User2Folder"}}
        ]
        res = self.service.search(1001, "User2Folder", assets=mixed)
        self.assertEqual(res.total_results, 0)

    def test_55_client_user_id_rejected(self):
        # Invalid user_id must immediately fail
        res = self.service.search(0, "test", assets=self.sample_assets)
        self.assertEqual(res.total_results, 0)
        self.assertIn("Invalid user_id", res.warnings[0])

    def test_56_hidden_ocr_data_cannot_leak(self):
        # Low quality OCR should not leak sensitive raw strings unchecked
        res = self.service.search(self.user_id, "b4y4r", assets=self.sample_assets)
        for item in res.items:
            for highlight in item.highlights.values():
                self.assertNotIn("4532-1234-5678-9012", highlight)

    def test_57_sensitive_card_and_otp_masked_in_reasons(self):
        sample = [{
            "id": 401,
            "user_id": 1001,
            "file_name": "payment_screen.png",
            "file_type": "photo",
            "ocr_text": "Pembayaran berhasil kartu 4532 1234 5678 9012 kode verifikasi 998811",
        }]
        res = self.service.search(self.user_id, "pembayaran", assets=sample)
        self.assertEqual(res.total_results, 1)
        for reason in res.items[0].reasons:
            self.assertNotIn("4532 1234 5678 9012", reason)
            self.assertNotIn("998811", reason)

    # ── Robustness (Tests 58-65) ───────────────────────────

    def test_58_empty_ocr(self):
        sample = [{"id": 501, "user_id": 1001, "file_name": "blank.png", "ocr_text": "", "ocr_confidence": 0.0}]
        res = self.service.search(self.user_id, "blank", assets=sample)
        self.assertEqual(res.total_results, 1)

    def test_59_malformed_metadata(self):
        sample = [{"id": 502, "user_id": 1001, "file_name": "corrupt.pdf", "mime_type": None, "folders": 12345, "metadata": "not_a_dict"}]
        res = self.service.search(self.user_id, "corrupt", assets=sample)
        self.assertEqual(res.total_results, 1)

    def test_60_long_query(self):
        long_q = "laporan " * 100
        res = self.service.search(self.user_id, long_q, assets=self.sample_assets)
        self.assertIsInstance(res, SearchResult)

    def test_61_unicode_query(self):
        sample = [{"id": 503, "user_id": 1001, "file_name": "dokumen_café_résumé.pdf", "file_type": "document"}]
        res = self.service.search(self.user_id, "café", assets=sample)
        self.assertEqual(res.total_results, 1)

    def test_62_mixed_language_query(self):
        # Indonesian + English query: "undangan meeting"
        res = self.service.search(self.user_id, "undangan meeting", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 5)

    def test_63_repeated_tokens(self):
        res = self.service.search(self.user_id, "pdf pdf pdf pdf", assets=self.sample_assets)
        self.assertGreater(res.total_results, 0)

    def test_64_weird_punctuation(self):
        res = self.service.search(self.user_id, "??!!@@##$$%%^^&&**", assets=self.sample_assets)
        self.assertIsInstance(res, SearchResult)

    def test_65_large_result_candidate_set(self):
        # Benchmark scale: 500 generated assets evaluated
        large_candidates = []
        for i in range(500):
            large_candidates.append({
                "id": i + 1000,
                "user_id": 1001,
                "file_name": f"Document_Archive_Batch_{i}.pdf",
                "file_type": "document",
                "file_size": 1024 * (i + 1),
                "folder_id": 10,
                "folders": {"name": "Archive"},
                "created_at": "2026-09-01T00:00:00Z",
            })
        res = self.service.search(self.user_id, "Batch 250", assets=large_candidates)
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 1250)
    def test_66_search_deep_candidates_beyond_500_limit(self):
        # Verify search reaches items placed deep in catalog (>500 items)
        class MockDB:
            def __init__(self):
                self.files = [
                    {
                        "id": i + 1,
                        "user_id": 1001,
                        "file_name": f"Document_{i}.pdf",
                        "file_type": "document",
                        "file_size": 1000,
                        "is_trashed": False,
                    }
                    for i in range(1200)
                ]
                # Target item placed at index 850 (exceeds old 500 limit)
                self.files[850] = {
                    "id": 9999,
                    "user_id": 1001,
                    "file_name": "Intro Video.mov",
                    "file_type": "video",
                    "file_size": 8700000,
                    "is_trashed": False,
                    "folders": {"name": "UKM FOKUS"},
                }

            def is_user_files_cached(self, user_id, is_trashed=False):
                return True

            def get_all_user_files(self, user_id, limit=None, is_trashed=False, use_cache=True):
                if limit is None:
                    return list(self.files)
                return list(self.files[:limit])

        svc = SearchService(db_module=MockDB())
        res = svc.search(1001, "intro")
        self.assertGreater(res.total_results, 0)
        self.assertEqual(res.items[0].asset_id, 9999)
        self.assertEqual(res.items[0].file_data.get("file_name"), "Intro Video.mov")

    def test_67_cache_and_invalidation(self):
        import database
        uid = 999999
        database.invalidate_user_files_cache(uid)
        self.assertFalse(database.is_user_files_cached(uid))

        # Manually populate cache
        database._USER_FILES_CACHE[(uid, False)] = (datetime.now().timestamp(), [{"id": 1, "file_name": "test.txt"}])
        self.assertTrue(database.is_user_files_cached(uid))

        # Test invalidation
        database.invalidate_user_files_cache(uid)
        self.assertFalse(database.is_user_files_cached(uid))


if __name__ == "__main__":
    unittest.main()

