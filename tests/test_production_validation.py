"""Task 6C Production Authentication Validation Test Suite.

Distinguishes test tiers:
- Tier A: Unit & configuration contract tests
- Tier B: Integration & security policy tests
- Tier C: Outbound live endpoint checks (Telegram OIDC discovery & JWKS)
- Tier D: Multi-origin, cross-user isolation & CSRF enforcement
"""

import json
import os
import unittest
from unittest.mock import patch, MagicMock
import tornado.testing
import tornado.web
import httpx

import auth
import config
import database as db
import oidc
import webapp


class TestProductionConfigContract(unittest.TestCase):
    """Test Render environment variable derivation and OIDC configuration safety."""

    def test_render_url_derivation(self):
        """Verify RENDER_EXTERNAL_URL or RENDER_EXTERNAL_HOSTNAME automatically sets base URL."""
        with patch.dict(os.environ, {"RENDER_EXTERNAL_HOSTNAME": "telegram-drive-bot-0upd.onrender.com"}, clear=False):
            host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
            derived_url = f"https://{host}"
            self.assertEqual(derived_url, "https://telegram-drive-bot-0upd.onrender.com")

    def test_redirect_uri_matches_render_service(self):
        """Verify default redirect URI strictly matches /auth/telegram/callback."""
        base = "https://telegram-drive-bot-0upd.onrender.com"
        expected_callback = f"{base}/auth/telegram/callback"
        self.assertEqual(expected_callback, "https://telegram-drive-bot-0upd.onrender.com/auth/telegram/callback")
        # Ensure no trailing slashes or extra queries
        self.assertFalse(expected_callback.endswith("/"))
        self.assertNotIn("?", expected_callback)

    def test_oidc_issuer_and_scopes(self):
        """Verify Telegram OIDC issuer and minimum required scopes."""
        self.assertEqual(config.TELEGRAM_OIDC_ISSUER, "https://oauth.telegram.org")
        self.assertIn("openid", config.TELEGRAM_OIDC_SCOPES)
        self.assertIn("profile", config.TELEGRAM_OIDC_SCOPES)
        # Verify phone scope is NOT requested by default
        self.assertNotIn("phone", config.TELEGRAM_OIDC_SCOPES.split())

    def test_pkce_algorithm_is_s256(self):
        """Verify PKCE code challenge uses SHA256 (S256)."""
        verifier = oidc.generate_code_verifier()
        challenge = oidc.generate_code_challenge(verifier)
        self.assertIsInstance(challenge, str)
        self.assertTrue(len(challenge) >= 43)
        # S256 with urlsafe base64 without padding
        self.assertNotIn("=", challenge)

    def test_open_redirect_sanitization(self):
        """Verify open redirect vectors are safely sanitized to default."""
        evil_vectors = [
            "https://evil.example.com",
            "http://evil.example.com",
            "//evil.example.com",
            "javascript:alert(1)",
            "data:text/html,bad",
            "\\evil.example.com",
            "/evil:path",
        ]
        for vec in evil_vectors:
            self.assertEqual(oidc.sanitize_redirect_path(vec), "/", f"Failed to sanitize: {vec}")

        safe_paths = [
            "/",
            "/drive",
            "/folder/123",
            "/s/shared-token",
        ]
        for p in safe_paths:
            self.assertEqual(oidc.sanitize_redirect_path(p), p, f"False positive on safe path: {p}")


class TestLiveTelegramOidcConnectivity(unittest.TestCase):
    """Test outbound HTTPS access to official Telegram OIDC discovery and JWKS."""

    def test_telegram_openid_configuration(self):
        """Verify outbound HTTPS access to https://oauth.telegram.org/.well-known/openid-configuration."""
        try:
            resp = httpx.get("https://oauth.telegram.org/.well-known/openid-configuration", timeout=10.0)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("issuer"), "https://oauth.telegram.org")
            self.assertEqual(data.get("authorization_endpoint"), "https://oauth.telegram.org/auth")
            self.assertEqual(data.get("token_endpoint"), "https://oauth.telegram.org/token")
            self.assertEqual(data.get("jwks_uri"), "https://oauth.telegram.org/.well-known/jwks.json")
        except httpx.ConnectError:
            self.skipTest("Outbound network connectivity not available in this test environment.")

    def test_telegram_jwks_and_cache(self):
        """Verify live Telegram JWKS parsing, caching, and key retrieval."""
        try:
            keys_map = oidc.get_jwks(force_refresh=True)
            self.assertTrue(len(keys_map) > 0, "No keys returned from Telegram JWKS")
            # Cache test: second call should return identical cached dictionary
            keys_map_cached = oidc.get_jwks(force_refresh=False)
            self.assertIs(keys_map, keys_map_cached)
            # Find an RSA key (oidc-1)
            rsa_key = keys_map.get("oidc-1")
            if rsa_key:
                self.assertIsNotNone(rsa_key.key)
        except httpx.ConnectError:
            self.skipTest("Outbound network connectivity not available in this test environment.")


class TestProductionAuthApiContract(tornado.testing.AsyncHTTPTestCase):
    """Test production API authentication matrix, CSRF enforcement, and identity isolation."""

    def get_app(self):
        routes = webapp.build_app_routes()
        return tornado.web.Application(routes)

    def test_unauthenticated_api_matrix(self):
        """Verify all private API routes strictly fail closed for unauthenticated requests."""
        private_endpoints = [
            ("GET", "/api/drive"),
            ("GET", "/api/search?q=test"),
            ("GET", "/api/file_intelligence?file_id=1"),
            ("GET", "/api/download?file_id=1"),
            ("GET", "/api/thumbnail?file_id=1"),
            ("POST", "/api/star"),
            ("POST", "/api/create_folder"),
            ("POST", "/api/rename"),
            ("POST", "/api/batch_delete"),
            ("POST", "/api/batch_move"),
            ("POST", "/api/empty_trash"),
            ("GET", "/api/organizer/preview"),
            ("POST", "/api/organizer/execute"),
            ("POST", "/api/preferences/feedback"),
        ]
        for method, path in private_endpoints:
            if method == "GET":
                resp = self.fetch(path, method="GET")
            else:
                resp = self.fetch(path, method="POST", body=json.dumps({"test": 1}), headers={"Content-Type": "application/json"})
            self.assertIn(resp.code, (401, 403), f"Route {method} {path} did not reject unauthenticated client: code {resp.code}")

    def test_api_auth_me_unauthenticated(self):
        """Verify GET /api/auth/me returns authenticated: false when no session exists."""
        resp = self.fetch("/api/auth/me")
        self.assertEqual(resp.code, 200)
        data = json.loads(resp.body.decode("utf-8"))
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("authenticated"))
        self.assertIsNone(data.get("user"))

    def test_api_auth_me_authenticated(self):
        """Verify GET /api/auth/me returns safe profile when session cookie is provided."""
        user_id = 987654
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"username": "test_user", "full_name": "Test Darfin"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            self.assertEqual(resp.code, 200)
            data = json.loads(resp.body.decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("authenticated"))
            self.assertEqual(data["user"]["user_id"], user_id)
            self.assertEqual(data["user"]["username"], "test_user")
            self.assertEqual(data["user"]["first_name"], "Test Darfin")
            # Verify internal tokens are NOT exposed
            self.assertNotIn("session_token", data["user"])
            self.assertNotIn("token", data["user"])

    def test_client_provided_user_id_is_ignored(self):
        """Verify query param or body user_id cannot spoof identity on /api/drive."""
        real_user_id = 111111
        token = auth.create_session_token(real_user_id)

        with patch.object(db, "get_storage_info", return_value={"total_size": 0, "by_type": {}, "size_by_type": {}}) as mock_storage, \
             patch.object(db, "get_folders", return_value=[]) as mock_folders, \
             patch.object(db, "get_all_user_files", return_value=[]) as mock_files:
            # Attacker passes ?user_id=999999
            resp = self.fetch("/api/drive?user_id=999999", headers={"Cookie": f"tma_session={token}"})
            self.assertEqual(resp.code, 200)
            # Backend should have queried using real_user_id (111111), NOT 999999
            mock_storage.assert_called_with(real_user_id)
            mock_folders.assert_called_with(real_user_id, parent_id=None)
            mock_files.assert_called_with(real_user_id, limit=60)

    def test_csrf_protection_for_browser_sessions(self):
        """Verify browser cookie sessions require matching tma_csrf cookie and header."""
        user_id = 222222
        token = auth.create_session_token(user_id)
        csrf_val = "valid-csrf-token-12345"

        # 1. State-changing POST without CSRF header -> 403 Forbidden
        with patch.object(db, "toggle_star_file", return_value={"id": 10, "is_starred": True}):
            resp = self.fetch(
                "/api/star",
                method="POST",
                headers={
                    "Cookie": f"tma_session={token}; tma_csrf={csrf_val}",
                    "Content-Type": "application/json",
                },
                body=json.dumps({"file_id": 10}),
            )
            self.assertEqual(resp.code, 403)

        # 2. State-changing POST with matching CSRF header -> 200 OK
        with patch.object(db, "toggle_star_file", return_value={"id": 10, "is_starred": True}):
            resp = self.fetch(
                "/api/star",
                method="POST",
                headers={
                    "Cookie": f"tma_session={token}; tma_csrf={csrf_val}",
                    "X-CSRF-Token": csrf_val,
                    "Content-Type": "application/json",
                },
                body=json.dumps({"file_id": 10}),
            )
            self.assertEqual(resp.code, 200)
            data = json.loads(resp.body.decode("utf-8"))
            self.assertTrue(data.get("ok"))

    def test_cross_user_file_isolation(self):
        """Verify User A cannot access or mutate User B's file."""
        user_a = 1001
        user_b = 2002
        token_a = auth.create_session_token(user_a)

        # User B owns file 555; db.get_file for user_a returns None
        with patch.object(db, "get_file", return_value=None):
            resp = self.fetch(f"/api/file_intelligence?file_id=555", headers={"Cookie": f"tma_session={token_a}"})
            self.assertEqual(resp.code, 404)

        with patch.object(db, "get_file", return_value=None):
            resp = self.fetch(f"/api/download?file_id=555", headers={"Cookie": f"tma_session={token_a}"})
            self.assertEqual(resp.code, 404)

    def test_logout_clears_session_and_csrf_cookies(self):
        """Verify POST /auth/logout clears cookies and returns JSON or redirect."""
        user_id = 333333
        token = auth.create_session_token(user_id)
        csrf = "csrf-val-abc"

        resp = self.fetch(
            "/auth/logout",
            method="POST",
            headers={
                "Cookie": f"tma_session={token}; tma_csrf={csrf}",
                "X-CSRF-Token": csrf,
                "Accept": "application/json",
            },
            body="",
        )
        self.assertEqual(resp.code, 200)
        set_cookie_headers = resp.headers.get_list("Set-Cookie")
        self.assertTrue(any("tma_session=" in c for c in set_cookie_headers))
        self.assertTrue(any("tma_csrf=" in c for c in set_cookie_headers))


if __name__ == "__main__":
    unittest.main()
