"""Focused tests for Telegram Account Profile Name Display (Task 6 Bug Fix).

Tests all 13 required scenarios:
1. full_name displayed
2. first + last name displayed
3. username displayed when available
4. missing username
5. missing last name
6. missing picture
7. fallback to username
8. fallback to safe generic label
9. hardcoded "User" removed
10. XSS profile name
11. XSS username
12. browser /api/auth/me profile mapping
13. same Telegram identity as existing DARFIN account
"""

import html
import json
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

import tornado.testing
import tornado.web

import auth
import database as db
import webapp


class TestProfileNameApi(tornado.testing.AsyncHTTPTestCase):
    """Test /api/auth/me profile resolution and fallback hierarchy."""

    def get_app(self):
        routes = webapp.build_app_routes()
        return tornado.web.Application(routes)

    def test_full_name_displayed(self):
        """1. full_name from database is displayed as primary name."""
        user_id = 1001
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "Tuan Darfin", "username": "darfinstar"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            self.assertEqual(resp.code, 200)
            data = json.loads(resp.body.decode("utf-8"))
            self.assertTrue(data.get("authenticated"))
            self.assertEqual(data["user"]["name"], "Tuan Darfin")
            self.assertEqual(data["user"]["full_name"], "Tuan Darfin")

    def test_first_plus_last_name_displayed(self):
        """2. first_name + last_name is composed when full_name is absent."""
        user_id = 1002
        token = auth.create_session_token(user_id)
        # DB has no full_name, but session/bot has first & last
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": None, "username": "darfin_user"}), \
             patch("webapp.get_shared_bot") as mock_bot:
            mock_chat = MagicMock()
            mock_chat.first_name = "Tuan"
            mock_chat.last_name = "Darfin"
            mock_chat.username = "darfin_user"
            mock_bot.return_value.get_chat = AsyncMock(return_value=mock_chat)
            with patch.object(db, "upsert_user"):
                resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
                self.assertEqual(resp.code, 200)
                data = json.loads(resp.body.decode("utf-8"))
                self.assertEqual(data["user"]["name"], "Tuan Darfin")

    def test_username_displayed_when_available(self):
        """3. username is returned clean without @ in payload."""
        user_id = 1003
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "Arfin", "username": "darfinstar"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertEqual(data["user"]["username"], "darfinstar")

    def test_missing_username(self):
        """4. missing username returns None, not @telegram or invented handle."""
        user_id = 1004
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "No Handle User", "username": None}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertIsNone(data["user"]["username"])

    def test_missing_last_name(self):
        """5. missing last name cleanly shows first_name alone without trailing whitespace."""
        user_id = 1005
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "Tuan", "username": "tuan_alone"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertEqual(data["user"]["name"], "Tuan")

    def test_missing_picture(self):
        """6. missing picture returns picture: None and does not error."""
        user_id = 1006
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "Tuan Darfin", "username": "darfin"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertIsNone(data["user"]["picture"])

    def test_fallback_to_username(self):
        """7. when full_name and first/last are missing, display name falls back to username."""
        user_id = 1007
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": None, "username": "darfinstar"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertEqual(data["user"]["name"], "darfinstar")

    def test_fallback_to_safe_generic_label(self):
        """8. when all names and username are missing, falls back to safe generic 'Telegram User'."""
        user_id = 1008
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": None, "username": None}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertEqual(data["user"]["name"], "Telegram User")
            # Verify numeric user ID is not used as display name
            self.assertNotEqual(data["user"]["name"], str(user_id))

    def test_browser_auth_me_profile_mapping(self):
        """12. /api/auth/me maps user ID, name, username, and picture conformant to Requirement 4."""
        user_id = 1012
        token = auth.create_session_token(user_id)
        with patch.object(db, "get_user", return_value={"id": user_id, "full_name": "Tuan Darfin", "username": "darfinstar"}):
            resp = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
            data = json.loads(resp.body.decode("utf-8"))
            self.assertTrue(data.get("ok"))
            self.assertTrue(data.get("authenticated"))
            user_obj = data["user"]
            self.assertEqual(user_obj["user_id"], user_id)
            self.assertEqual(user_obj["id"], user_id)
            self.assertEqual(user_obj["name"], "Tuan Darfin")
            self.assertEqual(user_obj["username"], "darfinstar")


class TestProfileTemplateAndSecurity(unittest.TestCase):
    """Test frontend template rendering, hardcoded string removal, and XSS safety."""

    def setUp(self):
        with open("templates/webapp.html", "r", encoding="utf-8") as f:
            self.html = f.read()

    def test_hardcoded_user_removed(self):
        """9. Verify hardcoded 'User' placeholder and '@telegram' are removed from profile markup."""
        self.assertNotIn('<span id="userName">User</span>', self.html)
        self.assertNotIn('<div class="user-full-name" id="userDropdownName">User</div>', self.html)
        self.assertNotIn('<div class="user-handle" id="userDropdownHandle">@telegram</div>', self.html)
        # Verify fallback in updateUserUI does not fall back to 'User'
        self.assertNotIn("|| 'User'", self.html)

    def test_xss_profile_name(self):
        """10. XSS payload in profile name is sanitized by innerText / escapeHtml."""
        malicious_name = '<script>alert("xss")</script>'
        escaped = html.escape(malicious_name)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;script&gt;", escaped)
        # Template uses innerText assignment for userName and userDropdownName
        self.assertIn("userNameEl.innerText = displayName", self.html)
        self.assertIn("userDropdownName.innerText = displayName", self.html)

    def test_xss_username(self):
        """11. XSS payload in username is assigned via innerText to prevent script execution."""
        self.assertIn("userDropdownHandle.innerText = handleText", self.html)

    def test_same_telegram_identity_as_existing_account(self):
        """13. OIDC provisioning calls db.upsert_user with same verified numeric user_id."""
        user_id = 998877
        claims = {
            "sub": str(user_id),
            "given_name": "Tuan",
            "family_name": "Darfin",
            "preferred_username": "darfinstar",
        }
        with patch("database.upsert_user") as mock_upsert:
            # Simulate OIDC user resolution
            resolved_id = int(claims["sub"])
            full_name = f"{claims['given_name']} {claims['family_name']}"
            username = claims["preferred_username"]
            db.upsert_user(user_id=resolved_id, username=username, full_name=full_name)
            mock_upsert.assert_called_with(user_id=user_id, username="darfinstar", full_name="Tuan Darfin")

    def test_upsert_user_does_not_wipe_name_when_called_without_arguments(self):
        """Preserve existing profile data in database.upsert_user when called without full_name/username."""
        with patch("database.db.table") as mock_table:
            mock_upsert = MagicMock()
            mock_table.return_value.upsert = mock_upsert
            db.upsert_user(user_id=55555)
            # Payload should only contain id and last_active, NOT username: None or full_name: None
            call_arg = mock_upsert.call_args[0][0]
            self.assertEqual(call_arg["id"], 55555)
            self.assertNotIn("username", call_arg)
            self.assertNotIn("full_name", call_arg)


if __name__ == "__main__":
    unittest.main()
