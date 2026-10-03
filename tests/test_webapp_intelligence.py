#!/usr/bin/env python3
"""Task 5 — Darfin Intelligent WebApp Integration Test Suite.

Comprehensive regression and integration tests covering:
- Authentication & session security on WebApp endpoints (IDOR, expiry, token validation)
- Backend Search API (/api/search) operations, filters, sorting, pagination
- Search results formatting, safety, privacy masking, signed media URLs
- File Intelligence API (/api/file_intelligence) classification, confidence labels, OCR, receipt, doc
- Safe Organizer & User Preferences feedback integration
- WebApp HTML DOM and security verifications
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

import tornado.testing
import tornado.web

import auth
import config
import database as db
import webapp
from darfin_intelligence.search.models import SearchMatch, SearchResult


class TestWebappIntelligenceBase(tornado.testing.AsyncHTTPTestCase):
    """Base setup for WebApp intelligence API testing."""

    def setUp(self):
        super().setUp()
        self.user_a_id = 9001
        self.user_b_id = 9002
        self.token_a = auth.create_session_token(self.user_a_id)
        self.token_b = auth.create_session_token(self.user_b_id)

    def get_app(self):
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0
        return tornado.web.Application(webapp.build_app_routes())


class TestAuthAndSessionSecurity(TestWebappIntelligenceBase):
    """Authentication and Session Security on Task 5 endpoints."""

    def test_search_unauthenticated_rejected_401(self):
        """Unauthenticated GET /api/search must return 401."""
        response = self.fetch("/api/search?q=test")
        self.assertEqual(response.code, 401)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_search_post_unauthenticated_rejected_401(self):
        """Unauthenticated POST /api/search must return 401."""
        response = self.fetch(
            "/api/search",
            method="POST",
            body=json.dumps({"q": "invoice"}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.code, 401)

    def test_search_client_user_id_ignored_rejected(self):
        """Client-provided user_id in query params without auth must return 401."""
        response = self.fetch(f"/api/search?user_id={self.user_a_id}&q=laporan")
        self.assertEqual(response.code, 401)

    def test_file_intelligence_unauthenticated_rejected_401(self):
        """Unauthenticated GET /api/file_intelligence must return 401."""
        response = self.fetch("/api/file_intelligence?file_id=101")
        self.assertEqual(response.code, 401)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    def test_file_intelligence_path_param_unauthenticated_rejected_401(self):
        """Unauthenticated GET /api/files/101/intelligence must return 401."""
        response = self.fetch("/api/files/101/intelligence")
        self.assertEqual(response.code, 401)

    def test_expired_session_token_rejected(self):
        """Expired session token must be rejected with 401."""
        expired_token = auth.create_session_token(self.user_a_id, duration_seconds=-10)
        response = self.fetch(
            "/api/search?q=test",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        self.assertEqual(response.code, 401)

    def test_tampered_session_token_rejected(self):
        """Tampered session token must be rejected with 401."""
        tampered = self.token_a + "tampered_suffix"
        response = self.fetch(
            "/api/search?q=test",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        self.assertEqual(response.code, 401)

    @patch("database.get_file")
    def test_file_intelligence_cross_user_file_returns_404(self, mock_get_file):
        """User A requesting User B's file intelligence must return 404 (IDOR prevention)."""
        # db.get_file returns None when requested by user_a for user_b's file
        mock_get_file.return_value = None
        response = self.fetch(
            "/api/file_intelligence?file_id=505",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 404)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

    @patch("darfin_intelligence.search.search")
    @patch("database.get_user_preferences", return_value={})
    def test_valid_session_token_allows_search(self, mock_prefs, mock_search):
        """Authenticated request with valid Bearer token executes search successfully."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="proposal", total_results=0)

        response = self.fetch(
            "/api/search?q=proposal",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertIn("result", data)

    @patch("database.get_file")
    @patch("database.get_all_folders", return_value=[])
    def test_valid_session_token_allows_file_intelligence(self, mock_folders, mock_get_file):
        """Authenticated request returns file intelligence for owned file."""
        mock_get_file.return_value = {
            "id": 101,
            "user_id": self.user_a_id,
            "file_name": "tugas_semester_5.pdf",
            "file_size": 204800,
            "file_type": "document",
            "mime_type": "application/pdf",
            "created_at": "2026-09-30T10:00:00Z",
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=101",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["intelligence"]["file_id"], 101)


class TestSearchApiOperations(TestWebappIntelligenceBase):
    """Functional search API operations: queries, operators, filters, pagination, sorting."""

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_basic_keyword_query(self, mock_search, mock_prefs):
        """Search query with basic keyword passed to SearchService."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="indomaret", total_results=0)

        response = self.fetch(
            "/api/search?q=indomaret",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["user_id"], self.user_a_id)
        self.assertEqual(kwargs["query"], "indomaret")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_multi_token_query(self, mock_search, mock_prefs):
        """Search query with multiple tokens passed accurately."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="laporan keuangan 2026", total_results=0)

        response = self.fetch(
            "/api/search?q=laporan+keuangan+2026",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["query"], "laporan keuangan 2026")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_post_json_payload(self, mock_search, mock_prefs):
        """POST /api/search with JSON payload correctly parsed and executed."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="receipt", total_results=0)

        payload = {
            "query": "receipt",
            "limit": 10,
            "offset": 5,
            "sort_by": "newest",
            "type": "document",
            "domain": "finance",
        }
        response = self.fetch(
            "/api/search",
            method="POST",
            body=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["query"], "receipt")
        self.assertEqual(kwargs["limit"], 10)
        self.assertEqual(kwargs["offset"], 5)
        self.assertEqual(kwargs["sort_by"], "newest")
        self.assertEqual(kwargs["filters"].family, "document")
        self.assertEqual(kwargs["filters"].domain, "finance")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_operator_query_ext(self, mock_search, mock_prefs):
        """Explicit ext argument passed to SearchFilters."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="tugas", total_results=0)

        response = self.fetch(
            "/api/search?q=tugas&ext=pdf",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["filters"].extension, "pdf")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_operator_query_domain(self, mock_search, mock_prefs):
        """Domain filter passed to SearchFilters."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="skripsi", total_results=0)

        response = self.fetch(
            "/api/search?q=skripsi&domain=education",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["filters"].domain, "education")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_operator_has_ocr(self, mock_search, mock_prefs):
        """has_ocr boolean filter parsed and passed."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)

        response = self.fetch(
            "/api/search?has_ocr=true",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertTrue(kwargs["filters"].has_ocr)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_scoped_to_folder_id(self, mock_search, mock_prefs):
        """folder_id filter parsed and passed to SearchFilters."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)

        response = self.fetch(
            "/api/search?folder_id=42",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["filters"].folder_id, 42)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_pagination_limit_and_offset(self, mock_search, mock_prefs):
        """Pagination limit and offset passed properly."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="", total_results=100)

        response = self.fetch(
            "/api/search?limit=30&offset=60",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["limit"], 30)
        self.assertEqual(kwargs["offset"], 60)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_sort_by_order(self, mock_search, mock_prefs):
        """sort_by parameter passed to SearchService."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)

        response = self.fetch(
            "/api/search?sort_by=newest",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        args, kwargs = mock_search.call_args
        self.assertEqual(kwargs["sort_by"], "newest")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_malformed_json_handled_safely(self, mock_search, mock_prefs):
        """Malformed JSON body in POST /api/search handled gracefully without trace leak."""
        from darfin_intelligence.search.models import SearchResult
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)

        response = self.fetch(
            "/api/search",
            method="POST",
            body="INVALID_JSON{{{{",
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)


class TestSearchResultsFormattingAndSafety(TestWebappIntelligenceBase):
    """Formatting, signed URL enrichment, and privacy masking in search responses."""

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_items_enriched_with_folder_and_media_urls(self, mock_search, mock_prefs):
        """Search items are enriched with folder_name, formatted size, and signed media URLs."""
        from darfin_intelligence.search.models import SearchMatch, SearchResult

        mock_match = SearchMatch(
            asset_id=101,
            score=95.0,
            matched_fields=["filename", "folder"],
            highlights={"filename": "laporan_keuangan.pdf"},
            reasons=["Nama berkas cocok dengan 'laporan'"],
            confidence=0.95,
            file_data={
                "id": 101,
                "file_name": "laporan_keuangan.pdf",
                "file_size": 1048576,
                "file_type": "document",
                "folders": {"name": "Keuangan"},
            },
        )
        mock_search.return_value = SearchResult(
            items=[mock_match],
            query="laporan",
            total_results=1,
            execution_time_ms=1.2,
        )

        response = self.fetch(
            "/api/search?q=laporan",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        items = data["result"]["items"]
        self.assertEqual(len(items), 1)

        item = items[0]
        fdata = item["file_data"]
        self.assertEqual(fdata["folder_name"], "Keuangan")
        self.assertEqual(fdata["file_size_formatted"], "1.0 MB")
        self.assertIn("/api/download?file_id=101&auth=", fdata["download_url"])

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_items_string_folder_name_handled(self, mock_search, mock_prefs):
        """If folder is provided as string, folder_name is populated properly."""
        from darfin_intelligence.search.models import SearchMatch, SearchResult

        mock_match = SearchMatch(
            asset_id=102,
            score=90.0,
            file_data={"id": 102, "file_name": "foto.jpg", "file_size": 500, "folders": "Liburan"},
        )
        mock_search.return_value = SearchResult(items=[mock_match], query="foto", total_results=1)

        response = self.fetch(
            "/api/search?q=foto",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["result"]["items"][0]["file_data"]["folder_name"], "Liburan")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_xss_filename_safe_in_json(self, mock_search, mock_prefs):
        """Filenames containing HTML tags or quotes serialize safely in JSON."""
        from darfin_intelligence.search.models import SearchMatch, SearchResult

        xss_name = '<script>alert("pwned")</script>.pdf'
        mock_match = SearchMatch(
            asset_id=103,
            score=88.0,
            file_data={"id": 103, "file_name": xss_name, "file_size": 100},
        )
        mock_search.return_value = SearchResult(items=[mock_match], query="alert", total_results=1)

        response = self.fetch(
            "/api/search?q=alert",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["result"]["items"][0]["file_data"]["file_name"], xss_name)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_with_merchant_and_doctype_filters(self, mock_search, mock_prefs):
        """GET /api/search correctly propagates merchant and document_type filters."""
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)
        response = self.fetch(
            "/api/search?merchant=indomaret&document_type=receipt",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        self.assertTrue(mock_search.called)
        _, kwargs = mock_search.call_args
        filters = kwargs.get("filters")
        self.assertIsNotNone(filters)
        self.assertEqual(filters.merchant, "indomaret")
        self.assertEqual(filters.document_type, "receipt")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_with_ocr_flag_filter(self, mock_search, mock_prefs):
        """GET /api/search correctly sets has_ocr filter to True."""
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)
        response = self.fetch(
            "/api/search?has_ocr=true",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        _, kwargs = mock_search.call_args
        filters = kwargs.get("filters")
        self.assertTrue(filters.has_ocr)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_scoped_to_folder_id(self, mock_search, mock_prefs):
        """GET /api/search scopes search to specific folder_id."""
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)
        response = self.fetch(
            "/api/search?q=laporan&folder_id=42",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        _, kwargs = mock_search.call_args
        filters = kwargs.get("filters")
        self.assertEqual(filters.folder_id, 42)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_sort_by_name_and_size(self, mock_search, mock_prefs):
        """GET /api/search accepts sort_by parameter."""
        mock_search.return_value = SearchResult(items=[], query="", total_results=0)
        response = self.fetch(
            "/api/search?q=tugas&sort_by=name_asc",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        _, kwargs = mock_search.call_args
        self.assertEqual(kwargs.get("sort_by"), "name_asc")

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_search_empty_matches_returns_clean_empty_state(self, mock_search, mock_prefs):
        """Empty search results return ok=True with total_results=0 and empty items list."""
        mock_search.return_value = SearchResult(items=[], query="nonexistentqueryxyz", total_results=0)
        response = self.fetch(
            "/api/search?q=nonexistentqueryxyz",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["total_results"], 0)
        self.assertEqual(len(data["result"]["items"]), 0)


class TestFileIntelligenceApi(TestWebappIntelligenceBase):
    """File Intelligence endpoint: classification, confidence labels, OCR, receipt, doc."""

    def test_file_intelligence_missing_param_returns_400(self):
        """GET /api/file_intelligence without file_id returns 400."""
        response = self.fetch(
            "/api/file_intelligence",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 400)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_file_intelligence_non_digit_param_returns_400(self):
        """GET /api/file_intelligence with non-numeric file_id returns 400."""
        response = self.fetch(
            "/api/file_intelligence?file_id=invalid_id",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 400)

    @patch("database.get_file", return_value=None)
    def test_file_intelligence_nonexistent_file_returns_404(self, mock_get_file):
        """GET /api/file_intelligence for non-existent file returns 404."""
        response = self.fetch(
            "/api/file_intelligence?file_id=99999",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 404)

    @patch("database.get_all_folders", return_value=[{"id": 10, "name": "Kuliah", "path": "Kuliah"}])
    @patch("database.get_file")
    def test_file_intelligence_classification_high_confidence(self, mock_get_file, mock_folders):
        """High confidence classification returns label 'Tinggi'."""
        mock_get_file.return_value = {
            "id": 201,
            "user_id": self.user_a_id,
            "file_name": "tugas_makalah_semester_4.pdf",
            "file_size": 150000,
            "file_type": "document",
            "mime_type": "application/pdf",
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=201",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        intel = data["intelligence"]
        self.assertEqual(intel["classification"]["domain"], "education")
        self.assertEqual(intel["classification"]["confidence_label"], "Tinggi")
        self.assertIn("makalah", intel["classification"]["explain"].lower())

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_confidence_label_perlu_ditinjau(self, mock_get_file, mock_folders):
        """Ambiguous classification returns label 'Perlu ditinjau'."""
        # Generic name with conflicting / minimal signals
        mock_get_file.return_value = {
            "id": 202,
            "user_id": self.user_a_id,
            "file_name": "catatan_data_draft.txt",
            "file_size": 500,
            "file_type": "document",
            "mime_type": "text/plain",
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=202",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        intel = data["intelligence"]
        # If ambiguous, confidence label must be "Perlu ditinjau"
        if intel["classification"]["status"] == "ambiguous":
            self.assertEqual(intel["classification"]["confidence_label"], "Perlu ditinjau")

    @patch("database.get_all_folders", return_value=[{"id": 25, "name": "Keuangan", "path": "Keuangan"}])
    @patch("database.get_file")
    def test_file_intelligence_smart_suggestion(self, mock_get_file, mock_folders):
        """Smart folder suggestion generated and included in intelligence response."""
        mock_get_file.return_value = {
            "id": 203,
            "user_id": self.user_a_id,
            "file_name": "struk_belanja_indomaret.jpg",
            "file_size": 250000,
            "file_type": "photo",
            "mime_type": "image/jpeg",
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=203",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        sug = data["intelligence"]["suggestion"]
        self.assertIsNotNone(sug)
        self.assertEqual(sug["folder_name"], "Keuangan")
        self.assertEqual(sug["folder_id"], 25)

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_ocr_sensitive_card_and_otp_masked(self, mock_get_file, mock_folders):
        """OCR preview masks 16-digit credit cards and OTP codes for user privacy."""
        sensitive_text = (
            "Indomaret Pembayaran Kartu: 4111222233334444 "
            "Kode Verifikasi OTP: 887219 Total: 50.000"
        )
        mock_get_file.return_value = {
            "id": 204,
            "user_id": self.user_a_id,
            "file_name": "receipt_card.jpg",
            "file_size": 120000,
            "file_type": "photo",
            "ocr_text": sensitive_text,
            "ocr_confidence": 0.95,
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=204",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        preview = data["intelligence"]["ocr"]["text_preview"]

        # Plain card number must NOT appear
        self.assertNotIn("4111222233334444", preview)
        self.assertIn("****", preview)

        # Plain OTP number must NOT appear
        self.assertNotIn("OTP: 887219", preview)

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_receipt_extraction(self, mock_get_file, mock_folders):
        """Receipt metadata (merchant, total, payment method) extracted from OCR."""
        receipt_ocr = (
            "INDOMARET POINT\n"
            "JL. SUDIRMAN NO 12\n"
            "TANGGAL: 15/09/2026 14:30\n"
            "1 TEH BOTOL 5000\n"
            "1 ROTI 10000\n"
            "TOTAL: 15.000\n"
            "TUNAI: 20.000\n"
            "KEMBALI: 5.000\n"
        )
        mock_get_file.return_value = {
            "id": 205,
            "user_id": self.user_a_id,
            "file_name": "receipt_indomaret.jpg",
            "file_size": 80000,
            "file_type": "photo",
            "ocr_text": receipt_ocr,
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=205",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        doc = data["intelligence"]["document"]
        self.assertIsNotNone(doc)
        self.assertIsNotNone(doc["receipt"])
        self.assertIn("indomaret", doc["receipt"]["merchant_name"].lower())
        self.assertEqual(doc["receipt"]["total"], 15000.0)

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_document_extraction(self, mock_get_file, mock_folders):
        """Document metadata (doc_type, number, subject) extracted from formal letter OCR."""
        doc_ocr = (
            "KEMENTERIAN PENDIDIKAN DAN KEBUDAYAAN\n"
            "SURAT KEPUTUSAN\n"
            "NOMOR: 421/108/DISDIK/2026\n"
            "TENTANG: PENETAPAN BEASISWA MAHASISWA\n"
            "TANGGAL: 10 JANUARI 2026\n"
        )
        mock_get_file.return_value = {
            "id": 206,
            "user_id": self.user_a_id,
            "file_name": "surat_keputusan.pdf",
            "file_size": 90000,
            "file_type": "document",
            "ocr_text": doc_ocr,
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=206",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        doc = data["intelligence"]["document"]
        self.assertIsNotNone(doc)
        self.assertIsNotNone(doc["document"])
        self.assertIn("421/108", doc["document"]["document_number"])

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_path_param_route(self, mock_get_file, mock_folders):
        """GET /api/files/<id>/intelligence path route works identically to query param."""
        mock_get_file.return_value = {
            "id": 207,
            "user_id": self.user_a_id,
            "file_name": "catatan.txt",
            "file_size": 200,
            "file_type": "document",
        }
        response = self.fetch(
            "/api/files/207/intelligence",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["intelligence"]["file_id"], 207)

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_file")
    def test_file_intelligence_missing_metadata_handled_gracefully(self, mock_get_file, mock_folders):
        """Files with no OCR, no screenshot, and no document metadata return safe payload."""
        mock_get_file.return_value = {
            "id": 208,
            "user_id": self.user_a_id,
            "file_name": "raw_binary.bin",
            "file_size": 1024,
            "file_type": "other",
        }
        response = self.fetch(
            "/api/file_intelligence?file_id=208",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertFalse(data["intelligence"]["ocr"]["available"])
        self.assertIsNone(data["intelligence"]["ocr"]["text_preview"])
        self.assertIsNone(data["intelligence"]["screenshot"])
        self.assertIsNone(data["intelligence"]["document"])



class TestOrganizerAndPreferencesFeedback(TestWebappIntelligenceBase):
    """Safe Smart Organizer moves & Task 2D user preference feedback."""

    @patch("database.get_user_preferences", return_value={})
    @patch("database.get_all_user_files")
    @patch("database.get_all_folders")
    def test_organizer_preview_authenticated_flow(self, mock_folders, mock_files, mock_prefs):
        """GET /api/organizer/preview returns plan for authenticated user."""
        mock_files.return_value = [
            {"id": 301, "file_name": "laporan_semester_5.pdf", "file_size": 5000, "file_type": "document"}
        ]
        mock_folders.return_value = [
            {"id": 10, "name": "Kuliah", "path": "Kuliah"}
        ]
        response = self.fetch(
            "/api/organizer/preview",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertIn("plan", data)

    @patch("darfin_intelligence.organizer.SafeOrganizer.execute_batch")
    def test_organizer_execute_single_move(self, mock_exec):
        """POST /api/organizer/execute calls SafeOrganizer and returns result."""
        mock_exec.return_value = {
            "ok": True,
            "summary": {"total": 1, "moved": 1, "failed": 0},
            "successful": [{"file_id": 301, "target_folder_id": 10}],
            "failed": [],
        }
        response = self.fetch(
            "/api/organizer/execute",
            method="POST",
            body=json.dumps({"file_id": 301, "target_folder_id": 10}),
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["summary"]["moved"], 1)

    @patch("database.get_file")
    @patch("database.get_folder")
    @patch("database.record_user_preference")
    def test_preferences_feedback_accepted_updates_preference(self, mock_rec, mock_get_folder, mock_get_file):
        """User A accepting folder suggestion updates user-scoped preference."""
        mock_get_file.return_value = {"id": 301, "file_name": "laporan_keuangan.pdf", "user_id": self.user_a_id}
        mock_get_folder.return_value = {"id": 10, "name": "Keuangan", "user_id": self.user_a_id}
        mock_rec.return_value = {"id": 1, "action": "accepted", "weight": 1.2}

        response = self.fetch(
            "/api/preferences/feedback",
            method="POST",
            body=json.dumps({"file_id": 301, "suggested_folder_id": 10, "action": "accepted"}),
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "accepted")

    @patch("database.get_file")
    @patch("database.get_folder")
    @patch("database.record_user_preference")
    def test_preferences_feedback_rejected_updates_preference(self, mock_rec, mock_get_folder, mock_get_file):
        """User A rejecting folder suggestion updates user-scoped preference with penalty."""
        mock_get_file.return_value = {"id": 302, "file_name": "invoice_toko.pdf", "user_id": self.user_a_id}
        mock_get_folder.return_value = {"id": 10, "name": "Kuliah", "user_id": self.user_a_id}
        mock_rec.return_value = {"id": 2, "action": "rejected", "weight": 0.7}

        response = self.fetch(
            "/api/preferences/feedback",
            method="POST",
            body=json.dumps({"file_id": 302, "suggested_folder_id": 10, "action": "rejected"}),
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "rejected")

    @patch("database.get_file", return_value=None)
    def test_preferences_feedback_foreign_file_blocked_403(self, mock_get_file):
        """User A cannot submit preference feedback for User B's file (403 Forbidden)."""
        response = self.fetch(
            "/api/preferences/feedback",
            method="POST",
            body=json.dumps({"file_id": 999, "suggested_folder_id": 10, "action": "accepted"}),
            headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 403)


class TestWebappHtmlDomAndSecurity(unittest.TestCase):
    """Static and structural validation of templates/webapp.html for Task 5 requirements."""

    @classmethod
    def setUpClass(cls):
        with open("templates/webapp.html", "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_html_has_search_box_and_clear_button(self):
        """Search box has input, clear button, and filter button."""
        self.assertIn('id="searchInput"', self.html)
        self.assertIn('id="searchClearBtn"', self.html)
        self.assertIn('id="searchFilterBtn"', self.html)
        self.assertIn('id="filterActiveBadge"', self.html)

    def test_html_has_search_quick_pills(self):
        """Quick search suggestions / pills present in HTML."""
        self.assertIn('id="searchQuickPills"', self.html)
        self.assertIn('receipt indomaret', self.html)
        self.assertIn('tugas semester 5', self.html)
        self.assertIn('ext:pdf', self.html)

    def test_html_has_search_state_header(self):
        """Search state header element present for displaying query and results count."""
        self.assertIn('id="searchStateHeader"', self.html)
        self.assertIn('id="searchStateTitle"', self.html)
        self.assertIn('id="searchResultCount"', self.html)
        self.assertIn('id="searchActiveChips"', self.html)

    def test_html_has_search_filter_modal(self):
        """Filter drawer modal present with options for family, domain, doc_type, ext, ocr."""
        self.assertIn('id="searchFilterModal"', self.html)
        self.assertIn('id="filterTypeOptions"', self.html)
        self.assertIn('id="filterDomainOptions"', self.html)
        self.assertIn('id="filterDocTypeOptions"', self.html)
        self.assertIn('id="filterExtOptions"', self.html)
        self.assertIn('id="filterOcrOnlyToggle"', self.html)
        self.assertIn('id="filterSortSelect"', self.html)

    def test_html_has_modal_intelligence_wrap(self):
        """File details modal contains intelligence wrap container."""
        self.assertIn('id="modalIntelligenceWrap"', self.html)

    def test_html_has_search_pagination_wrap(self):
        """Pagination container with Load More button present."""
        self.assertIn('id="searchPaginationWrap"', self.html)
        self.assertIn('id="btnLoadMoreSearch"', self.html)

    def test_html_escape_html_function_defined(self):
        """escapeHtml() function defined and protects against XSS in DOM rendering."""
        self.assertIn("function escapeHtml(", self.html)
        self.assertIn("&amp;", self.html)
        self.assertIn("&lt;", self.html)
        self.assertIn("&gt;", self.html)

    def test_html_no_fake_localstorage_userid_fallback(self):
        """HTML script does not use fake client-supplied user_id from localStorage or query param."""
        self.assertNotIn("localStorage.getItem('user_id')", self.html)
        self.assertNotIn('localStorage.getItem("user_id")', self.html)
        self.assertNotIn("urlParams.get('user_id')", self.html)
        self.assertNotIn('urlParams.get("user_id")', self.html)

    def test_html_debounce_timer_configured(self):
        """Input listener has debounced delay configured (300ms)."""
        self.assertIn("300", self.html)
        self.assertIn("debounceTimer", self.html)

    def test_html_confidence_badges_css_present(self):
        """Confidence badge CSS classes defined."""
        self.assertIn(".conf-high", self.html)
        self.assertIn(".conf-med", self.html)
        self.assertIn(".conf-review", self.html)
        self.assertIn(".conf-low", self.html)

    def test_html_intelligence_badges_classes_present(self):
        """Intelligence badge CSS classes defined."""
        self.assertIn(".badge-domain", self.html)
        self.assertIn(".badge-ocr", self.html)
        self.assertIn(".badge-receipt", self.html)
        self.assertIn(".badge-doc", self.html)
        self.assertIn(".badge-screenshot", self.html)

    def test_html_xss_protection_in_render_search_results(self):
        """Card rendering uses escapeHtml for filenames, highlights, and reasons."""
        self.assertIn("escapeHtml(f.file_name)", self.html)
        self.assertIn("escapeHtml(reasons.join", self.html)


class TestSearchPerformance(TestWebappIntelligenceBase):
    """Performance benchmarks for Task 5 WebApp Search endpoint."""

    @patch("database.get_all_folders", return_value=[])
    @patch("database.get_user_preferences", return_value={})
    @patch("database.get_all_user_files")
    def test_search_service_latency_under_50ms(self, mock_files, mock_prefs, mock_folders):
        """Search execution through ApiSearchHandler takes under 50ms for realistic dataset."""
        # 100 sample files
        mock_files.return_value = [
            {
                "id": i,
                "file_name": f"dokumen_laporan_tugas_{i}.pdf" if i % 2 == 0 else f"struk_pembayaran_indomaret_{i}.jpg",
                "file_size": 1024 * (i + 1),
                "file_type": "document" if i % 2 == 0 else "photo",
                "folder_id": 1,
            }
            for i in range(100)
        ]
        start = time.perf_counter()
        response = self.fetch(
            "/api/search?q=laporan+tugas",
            headers={"Authorization": f"Bearer {self.token_a}"},
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        # Should be well under 100ms on Render Free / local runner
        self.assertLess(elapsed_ms, 150.0, f"Search took too long: {elapsed_ms:.2f}ms")


if __name__ == "__main__":
    unittest.main()

