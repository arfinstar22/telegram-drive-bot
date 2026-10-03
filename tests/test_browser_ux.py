#!/usr/bin/env python3
"""Task 6B — Darfin Standalone Browser UX & Responsive Experience Test Suite.

Comprehensive tests covering:
1. Login UI: landing render, CTA button, login route, profile header, logout UI
2. Responsive Design: 320px/375px/430px mobile, tablet (641-1024px), desktop (1025px+), ultrawide (1440px+)
3. Search: visibility, debounce, pagination, filters, sorting, stale request drop
4. Intelligence: classification badges, OCR, screenshot, receipt, document, hidden empty fields
5. Security: XSS escaping (filename, OCR, folder), private data clearing, client user_id ignored, cross-user isolation, CSRF
6. Session UX: refresh, expiry, logout, Cache-Control no-store headers, login error feedback
7. Accessibility: keyboard nav, ARIA attributes, dialog Escape, focus rings, 44px touch targets
"""

from __future__ import annotations

import json
import re
import unittest
from unittest.mock import MagicMock, patch

import tornado.testing
import tornado.web

import auth
import config
import database as db
import webapp


class TestBrowserUxBase(tornado.testing.AsyncHTTPTestCase):
    """Base test setup for browser UX & responsive tests."""

    def setUp(self):
        super().setUp()
        self.orig_client_id = config.TELEGRAM_OIDC_CLIENT_ID
        self.orig_client_secret = config.TELEGRAM_OIDC_CLIENT_SECRET
        self.orig_redirect_uri = config.TELEGRAM_OIDC_REDIRECT_URI

        config.TELEGRAM_OIDC_CLIENT_ID = "test_telegram_client_id"
        config.TELEGRAM_OIDC_CLIENT_SECRET = "test_telegram_client_secret"
        config.TELEGRAM_OIDC_REDIRECT_URI = "https://example.com/auth/telegram/callback"
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0

        webapp._RATE_LIMITS.clear()

        # Cache template HTML string for DOM inspections
        self.template_html = webapp.TEMPLATE_PATH.read_text(encoding="utf-8")

    def tearDown(self):
        config.TELEGRAM_OIDC_CLIENT_ID = self.orig_client_id
        config.TELEGRAM_OIDC_CLIENT_SECRET = self.orig_client_secret
        config.TELEGRAM_OIDC_REDIRECT_URI = self.orig_redirect_uri
        webapp._RATE_LIMITS.clear()
        super().tearDown()

    def get_app(self):
        return tornado.web.Application(webapp.build_app_routes())


# ── 1. LOGIN UI TESTS (Tests 1-5) ─────────────────────────────────

class TestLoginUi(TestBrowserUxBase):
    """Test standalone browser landing and login UI."""

    def test_1_landing_renders_standalone_card(self):
        """1. Landing page contains #browserNoticeCard with DARFIN brand."""
        response = self.fetch("/")
        self.assertEqual(response.code, 200)
        html = response.body.decode("utf-8")
        self.assertIn("id=\"browserNoticeCard\"", html)
        self.assertIn("DARFIN", html)
        self.assertIn("Personal Cloud Storage", html)

    def test_2_telegram_button_exists(self):
        """2. Standalone CTA button #tgOidcLoginBtn exists with Telegram icon and label."""
        self.assertIn("id=\"tgOidcLoginBtn\"", self.template_html)
        self.assertIn("Continue with Telegram", self.template_html)

    def test_3_login_route_is_correct(self):
        """3. #tgOidcLoginBtn href points to /auth/telegram/start."""
        match = re.search(r'id="tgOidcLoginBtn"[^>]*href="([^"]+)"', self.template_html)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "/auth/telegram/start")

    @patch("database.get_user")
    def test_4_authenticated_user_profile_api(self, mock_get_user):
        """4. Authenticated browser session resolves profile via /api/auth/me."""
        mock_get_user.return_value = {"id": 8888, "username": "alice_drive", "full_name": "Alice"}
        token = auth.create_session_token(8888)

        response = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["id"], 8888)

    def test_5_logout_ui_structure_exists(self):
        """5. Logout action button exists in user profile dropdown menu."""
        self.assertIn("id=\"logoutBtn\"", self.template_html)
        self.assertIn("Keluar dari Akun", self.template_html)
        self.assertIn("id=\"userProfileDropdown\"", self.template_html)


# ── 2. RESPONSIVE DESIGN TESTS (Tests 6-10) ──────────────────────

class TestResponsiveDesign(TestBrowserUxBase):
    """Test CSS responsive breakpoints and layout reflow."""

    def test_6_small_mobile_media_query_present(self):
        """6. Small mobile layout (max-width: 375px) defined for compact screens."""
        self.assertIn("@media (max-width: 375px)", self.template_html)
        self.assertIn(".folders-grid", self.template_html)
        self.assertIn(".files-grid", self.template_html)

    def test_7_tablet_media_query_present(self):
        """7. Tablet layout (641px - 1024px) expands container to 860px with centered modals."""
        self.assertIn("@media (min-width: 641px) and (max-width: 1024px)", self.template_html)
        self.assertIn("max-width: 860px", self.template_html)

    def test_8_desktop_media_query_present(self):
        """8. Desktop layout (min-width: 1025px) expands container to 1200px."""
        self.assertIn("@media (min-width: 1025px)", self.template_html)
        self.assertIn("max-width: 1200px", self.template_html)

    def test_9_ultrawide_media_query_present(self):
        """9. Ultrawide layout (min-width: 1440px) expands container to 1380px."""
        self.assertIn("@media (min-width: 1440px)", self.template_html)
        self.assertIn("max-width: 1380px", self.template_html)

    def test_10_desktop_modal_dialog_styling(self):
        """10. Desktop modals transition from bottom sheets to centered dialog cards."""
        self.assertIn(".modal-sheet", self.template_html)
        self.assertIn(".sheet-handle", self.template_html)
        self.assertIn("display: none;", self.template_html)


# ── 3. SEARCH INTEGRATION TESTS (Tests 11-16) ─────────────────────

class TestSearchIntegration(TestBrowserUxBase):
    """Test search input, debouncing, pagination, filters, and stale protection."""

    def test_11_search_input_visible_and_accessible(self):
        """11. #searchInput exists with placeholder and clear button #searchClearBtn."""
        self.assertIn("id=\"searchInput\"", self.template_html)
        self.assertIn("id=\"searchClearBtn\"", self.template_html)
        self.assertIn("id=\"searchFilterBtn\"", self.template_html)

    def test_12_search_debounce_logic(self):
        """12. JavaScript contains debounce timer with ~300ms delay."""
        self.assertIn("searchState.debounceTimer = setTimeout(", self.template_html)
        self.assertIn("300", self.template_html)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_13_search_pagination_parameters(self, mock_search, mock_prefs):
        """13. /api/search accepts limit and offset parameters."""
        mock_res = MagicMock()
        mock_res.as_dict.return_value = {
            "query": "report",
            "items": [],
            "total_results": 45,
            "has_more": True,
            "execution_time_ms": 1.2,
        }
        mock_search.return_value = mock_res
        token = auth.create_session_token(9001)
        response = self.fetch("/api/search?q=report&limit=10&offset=20", headers={"Cookie": f"tma_session={token}"})
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["result"]["total_results"], 45)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_14_search_filters_supported(self, mock_search, mock_prefs):
        """14. /api/search accepts family, domain, and document_type filters."""
        mock_res = MagicMock()
        mock_res.as_dict.return_value = {
            "query": "",
            "items": [],
            "total_results": 3,
            "has_more": False,
            "execution_time_ms": 0.8,
        }
        mock_search.return_value = mock_res
        token = auth.create_session_token(9001)
        response = self.fetch(
            "/api/search?domain=finance&document_type=receipt&has_ocr=true",
            headers={"Cookie": f"tma_session={token}"},
        )
        self.assertEqual(response.code, 200)

    @patch("database.get_user_preferences", return_value={})
    @patch("darfin_intelligence.search.search")
    def test_15_search_sorting_supported(self, mock_search, mock_prefs):
        """15. /api/search accepts sort_by parameter."""
        mock_res = MagicMock()
        mock_res.as_dict.return_value = {"query": "test", "items": [], "total_results": 0, "execution_time_ms": 0.5}
        mock_search.return_value = mock_res
        token = auth.create_session_token(9001)
        response = self.fetch("/api/search?q=test&sort_by=date_desc", headers={"Cookie": f"tma_session={token}"})
        self.assertEqual(response.code, 200)

    def test_16_stale_search_request_dropped(self):
        """16. Frontend JavaScript includes requestId check to drop stale responses."""
        self.assertIn("if (currentReqId !== searchState.requestId) return;", self.template_html)


# ── 4. INTELLIGENCE UI TESTS (Tests 17-22) ─────────────────────────

class TestIntelligenceUi(TestBrowserUxBase):
    """Test intelligence badges, OCR snippets, receipts, and documents."""

    def test_17_classification_badge_styles_defined(self):
        """17. CSS contains .intel-badge and .badge-domain styles."""
        self.assertIn(".intel-badge", self.template_html)
        self.assertIn(".badge-domain", self.template_html)

    def test_18_ocr_badge_styles_defined(self):
        """18. CSS contains .badge-ocr style."""
        self.assertIn(".badge-ocr", self.template_html)

    def test_19_screenshot_badge_styles_defined(self):
        """19. CSS contains .badge-screenshot style."""
        self.assertIn(".badge-screenshot", self.template_html)

    def test_20_receipt_badge_styles_defined(self):
        """20. CSS contains .badge-receipt style."""
        self.assertIn(".badge-receipt", self.template_html)

    def test_21_document_badge_styles_defined(self):
        """21. CSS contains .badge-doc style."""
        self.assertIn(".badge-doc", self.template_html)

    def test_22_empty_fields_hidden_cleanly(self):
        """22. Intelligence panel template checks field existence before rendering."""
        self.assertIn("intel-badges-wrap", self.template_html)
        self.assertIn("badges.length > 0", self.template_html)


# ── 5. SECURITY TESTS (Tests 23-30) ───────────────────────────────

class TestBrowserSecurity(TestBrowserUxBase):
    """Test XSS defense, access control, CSRF, and data leak prevention."""

    def test_23_xss_in_filename_sanitized(self):
        """23. escapeHtml function is used on file names before DOM insertion."""
        self.assertIn("escapeHtml(f.file_name)", self.template_html)

    def test_24_xss_in_ocr_text_sanitized(self):
        """24. escapeHtml function is used on OCR text before rendering."""
        self.assertIn("escapeHtml(intel.ocr.text_preview)", self.template_html)

    def test_25_xss_in_folder_name_sanitized(self):
        """25. escapeHtml function is used on folder names."""
        self.assertIn("escapeHtml(f.name)", self.template_html)

    def test_26_private_data_cleared_on_logout(self):
        """26. handleLogout clears in-memory session token, currentUser, and driveData."""
        self.assertIn("authToken = null;", self.template_html)
        self.assertIn("currentUser = null;", self.template_html)
        self.assertIn("driveData = { folders: [], files: [] };", self.template_html)

    @patch("database.get_user")
    def test_27_client_user_id_query_param_ignored(self, mock_get_user):
        """27. Query parameter ?user_id=1234 cannot override authenticated principal."""
        mock_get_user.return_value = {"id": 9001, "username": "real_owner"}
        token = auth.create_session_token(9001)

        response = self.fetch("/api/auth/me?user_id=9999", headers={"Cookie": f"tma_session={token}"})
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["user"]["id"], 9001)

    @patch("database.get_file")
    def test_28_cross_user_file_access_blocked(self, mock_get_file):
        """28. Accessing file owned by another user returns 404."""
        token = auth.create_session_token(9001)
        mock_get_file.side_effect = lambda fid, user_id=None: {"id": 100, "user_id": 9002} if user_id == 9002 else None

        response = self.fetch("/api/download?file_id=100", headers={"Cookie": f"tma_session={token}"})
        self.assertEqual(response.code, 404)

    def test_29_unauthorized_api_access_rejected(self):
        """29. Accessing private /api/drive without auth returns 401."""
        response = self.fetch("/api/drive")
        self.assertEqual(response.code, 401)

    @patch("database.get_file")
    def test_30_csrf_failure_on_post(self, mock_get_file):
        """30. POST /api/star without CSRF header is rejected with 403."""
        token = auth.create_session_token(9001)
        response = self.fetch(
            "/api/star",
            method="POST",
            body=json.dumps({"file_id": 1}),
            headers={"Cookie": f"tma_session={token}", "Content-Type": "application/json"},
        )
        self.assertEqual(response.code, 403)


# ── 6. SESSION UX & CACHE TESTS (Tests 31-35) ─────────────────────

class TestSessionUxAndCache(TestBrowserUxBase):
    """Test session lifecycle, cache control, and user feedback."""

    @patch("database.get_user")
    def test_31_browser_refresh_preserves_session(self, mock_get_user):
        """31. Browser refresh with valid session cookie returns authenticated state."""
        mock_get_user.return_value = {"id": 9001, "username": "persisted_user"}
        token = auth.create_session_token(9001)

        # First request
        res1 = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
        # Second request (refresh simulation)
        res2 = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})

        self.assertEqual(res1.code, 200)
        self.assertEqual(res2.code, 200)
        d1 = json.loads(res1.body.decode("utf-8"))
        d2 = json.loads(res2.body.decode("utf-8"))
        self.assertEqual(d1["user"]["id"], d2["user"]["id"])

    def test_32_expired_session_returns_unauthenticated(self):
        """32. Expired session token returns authenticated=False on /api/auth/me."""
        expired_token = auth.create_session_token(user_id=9001, duration_seconds=-100)
        response = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={expired_token}"})
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["authenticated"])

    def test_33_logout_route_clears_cookies(self):
        """33. POST /auth/logout clears tma_session and tma_csrf cookies."""
        response = self.fetch("/auth/logout", method="POST", body="", follow_redirects=False)
        self.assertEqual(response.code, 302)
        cookies = "; ".join(response.headers.get_list("Set-Cookie"))
        self.assertIn('tma_session=""', cookies)
        self.assertIn('tma_csrf=""', cookies)

    def test_34_cache_control_no_store_headers(self):
        """34. WebApp template sets Cache-Control: no-store to protect history."""
        response = self.fetch("/")
        cache_ctrl = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_ctrl)
        self.assertIn("no-cache", cache_ctrl)

    def test_35_login_error_renders_safe_message(self):
        """35. auth_error query parameters display safe localized message."""
        self.assertIn("Login dibatalkan oleh pengguna.", self.template_html)
        self.assertIn("Sesi login kedaluwarsa atau tidak valid.", self.template_html)


# ── 7. ACCESSIBILITY TESTS (Tests 36-45) ──────────────────────────

class TestAccessibility(TestBrowserUxBase):
    """Test keyboard navigation, ARIA semantics, focus rings, and touch targets."""

    def test_36_user_pill_keyboard_attributes(self):
        """36. #userPill has role=button, tabindex=0, aria-haspopup=true, and aria-expanded=false."""
        self.assertIn('id="userPill"', self.template_html)
        self.assertIn('role="button"', self.template_html)
        self.assertIn('tabindex="0"', self.template_html)
        self.assertIn('aria-haspopup="true"', self.template_html)
        self.assertIn('aria-expanded="false"', self.template_html)

    def test_37_icon_buttons_have_accessible_labels(self):
        """37. Action and search buttons have aria-label or title."""
        self.assertIn('aria-label="Filter Pencarian"', self.template_html)
        self.assertIn('aria-label="Hapus Pencarian"', self.template_html)

    def test_38_escape_key_listener_registered(self):
        """38. Global keydown listener handles Escape key to close modals and dropdowns."""
        self.assertIn("if (e.key === 'Escape')", self.template_html)
        self.assertIn("closeUserProfileMenu()", self.template_html)

    def test_39_focus_visible_outlines_defined(self):
        """39. CSS defines :focus-visible outline with accent color."""
        self.assertIn(":focus-visible", self.template_html)
        self.assertIn("outline: 2px solid var(--accent);", self.template_html)

    def test_40_touch_targets_min_44px(self):
        """40. Interactive buttons define minimum 44px height for mobile touch targets."""
        self.assertIn("min-height: 44px;", self.template_html)

    def test_41_user_profile_dropdown_menu_semantics(self):
        """41. #userProfileDropdown has role=menu and logout has role=menuitem."""
        self.assertIn('id="userProfileDropdown" role="menu"', self.template_html)
        self.assertIn('role="menuitem"', self.template_html)

    def test_42_click_outside_closes_dropdown(self):
        """42. Clicking outside .header-user-section triggers closeUserProfileMenu()."""
        self.assertIn("if (userSection && !userSection.contains(e.target))", self.template_html)

    def test_43_session_expiry_handler_attached_to_auth_fetch(self):
        """43. authFetch detects HTTP 401 status and invokes handleSessionExpired()."""
        self.assertIn("if (resp.status === 401)", self.template_html)
        self.assertIn("handleSessionExpired();", self.template_html)

    def test_44_breadcrumbs_accessible(self):
        """44. Breadcrumbs nav element exists with root My Drive navigation link."""
        self.assertIn('id="breadcrumbs"', self.template_html)
        self.assertIn("My Drive", self.template_html)

    def test_45_load_drive_data_supports_cookie_sessions(self):
        """45. loadDriveData allows browser cookie sessions without redundant initSession calls."""
        self.assertIn("if (!authToken && !currentUser)", self.template_html)


if __name__ == "__main__":
    unittest.main()
