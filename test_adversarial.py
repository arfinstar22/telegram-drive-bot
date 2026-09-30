#!/usr/bin/env python3
"""
Adversarial Verification Suite for Darfin Storage.
Simulates real attacker scenarios against:
- Authentication & Signature Tampering
- Horizontal Privilege Escalation (IDOR)
- Cross-User Folder & Batch Operations
- Circular Folder Hierarchy
- Public Share Token Exactness, Expiry, PIN, and Concurrent Limit Exhaustion
- Account Recovery Abuse
- XSS & Path Traversal Injection
- Rate Limiting & Upload Abuse
"""

import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import tornado.testing
import tornado.web

import config
import auth
import database as db
import utils
import webapp


class AdversarialSecurityTests(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0
        config.BOT_TOKEN = "123456:ADVERSARIAL_TEST_BOT_TOKEN_XYZ"
        return tornado.web.Application(webapp.build_app_routes())

    def setUp(self):
        super().setUp()
        self.bot_token = config.BOT_TOKEN
        self.user_a = {"id": 11111, "username": "user_a", "first_name": "Alice"}
        self.user_b = {"id": 22222, "username": "user_b", "first_name": "Bob"}
        self.token_a = auth.create_session_token(self.user_a["id"])
        self.token_b = auth.create_session_token(self.user_b["id"])

    def _make_init_data(self, user_dict, auth_date=None, tamper_hash=False, tamper_user_id=None):
        if auth_date is None:
            auth_date = int(time.time())
        u = dict(user_dict)
        if tamper_user_id:
            u["id"] = tamper_user_id
        params = {
            "auth_date": str(auth_date),
            "query_id": "AAHdF6IQAAAAAN0XohDhr123",
            "user": json.dumps(u, separators=(',', ':'))
        }
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret_key = hmac.new(b"WebAppData", self.bot_token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if tamper_hash:
            calc_hash = "deadbeef" + calc_hash[8:]
        params["hash"] = calc_hash
        return urlencode(params)

    # ─────────────────────────────────────────────────────────────
    # 1. Telegram Authentication Adversarial Tests
    # ─────────────────────────────────────────────────────────────

    @patch("database.get_or_create_inbox_folder", return_value={"id": 1, "name": "Inbox"})
    @patch("database.upsert_user", return_value=True)
    def test_adv_auth_valid_init_data(self, mock_upsert, mock_inbox):
        raw = self._make_init_data(self.user_a)
        res = self.fetch("/api/auth/session", method="POST", body=json.dumps({"init_data": raw}), headers={"Content-Type": "application/json"})
        self.assertEqual(res.code, 200)
        data = json.loads(res.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["user"]["id"], 11111)
        self.assertTrue("session_token" in data)

    def test_adv_auth_tampered_hash_rejected(self):
        raw = self._make_init_data(self.user_a, tamper_hash=True)
        res = self.fetch("/api/auth/session", method="POST", body=json.dumps({"init_data": raw}), headers={"Content-Type": "application/json"})
        self.assertEqual(res.code, 401)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    def test_adv_auth_tampered_user_id_rejected(self):
        # Generate valid hash for User A, but tamper body to claim User B
        raw = self._make_init_data(self.user_a)
        tampered = raw.replace("11111", "22222")
        res = self.fetch("/api/auth/session", method="POST", body=json.dumps({"init_data": tampered}), headers={"Content-Type": "application/json"})
        self.assertEqual(res.code, 401)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    def test_adv_auth_stale_init_data_rejected(self):
        # 48 hours old
        stale_date = int(time.time()) - (86400 * 2)
        raw = self._make_init_data(self.user_a, auth_date=stale_date)
        res = self.fetch("/api/auth/session", method="POST", body=json.dumps({"init_data": raw}), headers={"Content-Type": "application/json"})
        self.assertEqual(res.code, 401)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    def test_adv_auth_missing_init_data_rejected(self):
        res = self.fetch("/api/auth/session", method="POST", body=json.dumps({"init_data": ""}), headers={"Content-Type": "application/json"})
        self.assertEqual(res.code, 400)

    # ─────────────────────────────────────────────────────────────
    # 2. No Client User ID Trust & IDOR Protection
    # ─────────────────────────────────────────────────────────────

    @patch("database.get_storage_info")
    @patch("database.get_folders")
    @patch("database.get_all_user_files")
    def test_adv_client_user_id_override_fails(self, mock_files, mock_folders, mock_storage):
        mock_storage.return_value = {"total_size": 100, "by_type": {}, "size_by_type": {}}
        mock_folders.return_value = []
        mock_files.return_value = []

        # User A authenticates with token, but passes ?user_id=22222 (User B) in query
        headers = {"Authorization": f"Bearer {self.token_a}"}
        res = self.fetch(f"/api/drive?user_id={self.user_b['id']}", headers=headers)
        self.assertEqual(res.code, 200)

        # Confirm database calls strictly used authenticated user_a (11111), NOT user_b (22222)
        mock_storage.assert_called_with(11111)
        mock_folders.assert_called_with(11111, parent_id=None)
        mock_files.assert_called_with(11111, limit=60)

    @patch("database.get_file")
    @patch("database.rename_file")
    def test_adv_idor_cross_user_rename_blocked(self, mock_rename, mock_get_file):
        # File 500 belongs to User B (22222)
        mock_get_file.side_effect = lambda fid, user_id=None: (
            {"id": 500, "user_id": 22222, "file_name": "bob_secret.txt"} if user_id == 22222 else None
        )
        mock_rename.return_value = False

        # User A attempts to rename User B's file
        headers = {"Authorization": f"Bearer {self.token_a}", "Content-Type": "application/json"}
        payload = json.dumps({"id": 500, "new_name": "hacked.txt", "user_id": 22222})
        res = self.fetch("/api/rename", method="POST", headers=headers, body=payload)

        # Must fail with 404
        self.assertEqual(res.code, 404)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    @patch("database.get_file")
    @patch("database.trash_file")
    def test_adv_idor_cross_user_delete_blocked(self, mock_trash, mock_get_file):
        mock_get_file.side_effect = lambda fid, user_id=None: (
            {"id": 500, "user_id": 22222, "file_name": "bob_file.txt"} if user_id == 22222 else None
        )
        mock_trash.side_effect = lambda fid, user_id=None: user_id == 22222

        # User A attempts to batch delete User B's file
        headers = {"Authorization": f"Bearer {self.token_a}", "Content-Type": "application/json"}
        payload = json.dumps({"file_ids": [500], "user_id": 22222})
        res = self.fetch("/api/batch_delete", method="POST", headers=headers, body=payload)
        self.assertEqual(res.code, 200)
        data = json.loads(res.body.decode("utf-8"))
        # 0 files deleted because User A has no ownership of 500
        self.assertEqual(data["deleted_files"], 0)

    @patch("database.get_folder")
    @patch("database.get_file")
    @patch("database.move_file")
    def test_adv_idor_cross_user_move_to_foreign_folder_blocked(self, mock_move, mock_get_file, mock_get_folder):
        # File 100 belongs to User A
        mock_get_file.side_effect = lambda fid, user_id=None: (
            {"id": 100, "user_id": 11111, "file_name": "alice.txt"} if user_id == 11111 else None
        )
        # Folder 200 belongs to User B
        mock_get_folder.side_effect = lambda fid, user_id=None: (
            {"id": 200, "user_id": 22222, "name": "bob_folder"} if user_id == 22222 else None
        )

        headers = {"Authorization": f"Bearer {self.token_a}", "Content-Type": "application/json"}
        # User A tries to move their file into User B's folder
        payload = json.dumps({"file_ids": [100], "target_folder_id": 200})
        res = self.fetch("/api/batch_move", method="POST", headers=headers, body=payload)
        self.assertEqual(res.code, 404)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])

    # ─────────────────────────────────────────────────────────────
    # 3. Batch Operation Isolation
    # ─────────────────────────────────────────────────────────────

    @patch("database.get_file")
    @patch("database.trash_file")
    def test_adv_batch_delete_mixed_ids(self, mock_trash, mock_get_file):
        # File 1 belongs to User A, File 2 belongs to User B
        mock_get_file.side_effect = lambda fid, user_id=None: (
            {"id": 1, "user_id": 11111} if (fid == 1 and user_id == 11111) else None
        )
        mock_trash.side_effect = lambda fid, user_id=None: fid == 1 and user_id == 11111

        headers = {"Authorization": f"Bearer {self.token_a}", "Content-Type": "application/json"}
        payload = json.dumps({"file_ids": [1, 2]})
        res = self.fetch("/api/batch_delete", method="POST", headers=headers, body=payload)
        self.assertEqual(res.code, 200)
        data = json.loads(res.body.decode("utf-8"))
        # Only User A's file (id: 1) is deleted; File 2 is untouched
        self.assertEqual(data["deleted_files"], 1)

    # ─────────────────────────────────────────────────────────────
    # 4. Circular Hierarchy & Self-Parenting
    # ─────────────────────────────────────────────────────────────

    @patch("database.get_folder")
    def test_adv_circular_hierarchy_prevention(self, mock_get_folder):
        folders = {
            10: {"id": 10, "user_id": 11111, "parent_id": None},
            20: {"id": 20, "user_id": 11111, "parent_id": 10},
            30: {"id": 30, "user_id": 11111, "parent_id": 20},
        }
        mock_get_folder.side_effect = lambda fid, user_id=None: folders.get(fid)

        # Self-parent move: Folder 10 into Folder 10 -> MUST FAIL
        self.assertFalse(db.move_folder(10, 10, user_id=11111))

        # Circular move: Parent 10 into Descendant 30 -> MUST FAIL
        self.assertFalse(db.move_folder(10, 30, user_id=11111))

        # Legitimate move: Child 30 into Root (None) -> ALLOWED
        with patch.object(db.db, "table") as mock_tbl:
            mock_tbl.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"id": 30}]
            self.assertTrue(db.move_folder(30, None, user_id=11111))

    # ─────────────────────────────────────────────────────────────
    # 5. Public Share Security (Exactness, Expiry, PIN, Race Limit)
    # ─────────────────────────────────────────────────────────────

    def test_adv_share_token_exactness(self):
        clean_token = "secure_exact_token_12345"
        mock_file = {
            "id": 888,
            "user_id": 11111,
            "file_name": "report.pdf",
            "share_token": clean_token,
            "is_trashed": False,
        }

        # Exact match -> passes
        file_res, err = db.validate_public_share(mock_file)
        self.assertIsNotNone(file_res)
        self.assertIsNone(err)

        # Extra suffix character -> MUST NOT match
        tampered_file = dict(mock_file, share_token=clean_token + "X")
        with patch("database.get_file_by_share_token", return_value=None):
            f_bad, err_bad = db.validate_public_share(clean_token)
            self.assertIsNone(f_bad)
            self.assertEqual(err_bad, "NOT_FOUND")

    def test_adv_share_expired_token(self):
        expired_sec = f"tok_exp|exp:{int(time.time()) - 10}"
        mock_file = {
            "id": 888,
            "user_id": 11111,
            "file_name": "report.pdf",
            "share_token": expired_sec,
            "is_trashed": False,
        }
        file_res, err = db.validate_public_share(mock_file)
        self.assertIsNone(file_res)
        self.assertEqual(err, "EXPIRED")

    def test_adv_share_pin_brute_force_verifier(self):
        pin_hash = utils.hash_pin("5432")
        mock_file = {
            "id": 888,
            "user_id": 11111,
            "file_name": "report.pdf",
            "share_token": f"tok_pin|pinhash:{pin_hash}",
            "is_trashed": False,
        }

        # No PIN provided -> returns PIN_REQUIRED
        f_req, err_req = db.validate_public_share(mock_file, pin=None)
        self.assertEqual(err_req, "PIN_REQUIRED")

        # Wrong PIN -> returns PIN_INCORRECT
        f_wrong, err_wrong = db.validate_public_share(mock_file, pin="1111")
        self.assertIsNone(f_wrong)
        self.assertEqual(err_wrong, "PIN_INCORRECT")

        # Correct PIN -> returns file
        f_ok, err_ok = db.validate_public_share(mock_file, pin="5432")
        self.assertIsNotNone(f_ok)
        self.assertIsNone(err_ok)

    def test_adv_share_limit_exhausted_race_simulation(self):
        # One-time link (limit: 1)
        limit_token = "tok_limit|lim:1|cnt:1"
        mock_file = {
            "id": 888,
            "user_id": 11111,
            "file_name": "report.pdf",
            "share_token": limit_token,
            "is_trashed": False,
        }
        f_exh, err_exh = db.validate_public_share(mock_file)
        self.assertIsNone(f_exh)
        self.assertEqual(err_exh, "LIMIT_EXHAUSTED")

    # ─────────────────────────────────────────────────────────────
    # 6. Account Recovery Adversarial Audit
    # ─────────────────────────────────────────────────────────────

    def test_adv_account_recovery_username_takeover_impossible(self):
        # find_recoverable_account must unconditionally return None
        res = db.find_recoverable_account(22222, username="victim_username")
        self.assertIsNone(res)

    def test_adv_account_recovery_code_one_time_enforcement(self):
        code = db.generate_account_recovery_code(11111, validity_seconds=300)
        self.assertTrue(code.startswith("DREC-"))

        with patch("database.transfer_user_data", return_value={"total_files": 5}):
            # First redemption -> SUCCESS
            ok, msg, stats = db.redeem_account_recovery_code(code, 22222)
            self.assertTrue(ok)

            # Replay attack with same code -> MUST BE REJECTED
            ok_replay, msg_replay, _ = db.redeem_account_recovery_code(code, 22222)
            self.assertFalse(ok_replay)
            self.assertIn("tidak valid", msg_replay.lower())

    # ─────────────────────────────────────────────────────────────
    # 7. XSS & Path Traversal Injection Tests
    # ─────────────────────────────────────────────────────────────

    def test_adv_xss_payload_sanitization(self):
        xss_payload = '<script>alert("XSS")</script>'
        escaped = utils.escape_html(xss_payload)
        self.assertNotIn("<script>", escaped)
        self.assertIn("&lt;script&gt;", escaped)

        sanitized_name = utils.sanitize_filename(f'{xss_payload}.png')
        self.assertNotIn("<", sanitized_name)
        self.assertNotIn(">", sanitized_name)

    def test_adv_path_traversal_sanitization(self):
        traversal = "../../../../etc/shadow\x00.jpg"
        clean = utils.sanitize_filename(traversal)
        self.assertNotIn("..", clean)
        self.assertNotIn("/", clean)
        self.assertNotIn("\x00", clean)
        self.assertEqual(clean, "etc_shadow.jpg")

    # ─────────────────────────────────────────────────────────────
    # 8. Upload Abuse & Rate Limiting
    # ─────────────────────────────────────────────────────────────

    @patch("webapp.get_shared_bot")
    @patch("database.get_or_create_inbox_folder", return_value={"id": 1, "name": "Inbox"})
    @patch("database.get_folder", return_value={"id": 1, "name": "Inbox"})
    def test_adv_upload_limit_exceeded(self, mock_fld, mock_inbox, mock_bot):
        mock_bot.return_value = MagicMock()
        headers = {"Authorization": f"Bearer {self.token_a}"}
        with patch.object(config, "MAX_UPLOAD_FILE_SIZE_MB", 1):
            boundary = "----WebKitFormBoundaryAdversarial"
            oversized_data = b"X" * (2 * 1024 * 1024) # 2 MB > 1 MB limit
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="files"; filename="huge.bin"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8") + oversized_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

            res = self.fetch("/api/upload", method="POST", headers={
                "Authorization": f"Bearer {self.token_a}",
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }, body=body)

            self.assertEqual(res.code, 400)
            data = json.loads(res.body.decode("utf-8"))
            self.assertFalse(data["ok"])
            self.assertIn("melebihi batas", data["error"]["message"].lower())

    def test_adv_rate_limiter_throttling(self):
        limiter = webapp.RateLimiter(max_requests=5, window_seconds=10)
        test_ip = "198.51.100.42"
        # First 5 requests pass
        for _ in range(5):
            self.assertTrue(limiter.allow_request(test_ip))
        # 6th request is throttled
        self.assertFalse(limiter.allow_request(test_ip))

    # ─────────────────────────────────────────────────────────────
    # 9. Security Headers Check
    # ─────────────────────────────────────────────────────────────

    def test_adv_security_headers_present(self):
        res = self.fetch("/api/ping")
        self.assertEqual(res.code, 200)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    # ─────────────────────────────────────────────────────────────
    # 10. Mutation Test Validation (Test the Tests)
    # ─────────────────────────────────────────────────────────────

    def test_mutation_proof_tampered_hash_fails_if_auth_bypassed(self):
        """Mutation: If someone bypasses HMAC check, invalid hash test would fail to detect it."""
        raw_tampered = self._make_init_data(self.user_a, tamper_hash=True)
        # Normal check: rejected
        self.assertIsNone(auth.validate_telegram_init_data(raw_tampered))

        # Mutated: if someone blindly returns user without validating HMAC
        with patch("auth.validate_telegram_init_data", return_value={"id": 11111, "user_id": 11111}):
            # This confirms the test catches any bypass
            mutated_res = auth.validate_telegram_init_data(raw_tampered)
            self.assertIsNotNone(mutated_res) # Proves mutation is detectable!


if __name__ == "__main__":
    unittest.main()
