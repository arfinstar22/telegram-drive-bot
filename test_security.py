#!/usr/bin/env python3
"""
Comprehensive Security & Authorization Regression Test Suite
Covers:
- Telegram initData validation (valid, tampered, expired, missing, bad hash)
- Dev auth behavior
- File & Folder Ownership checks (IDOR prevention)
- Relational integrity (moving to foreign folders, circular folder hierarchy)
- Public share token exact matching, server-side expiration, PIN hashing, download limits
- Filename sanitization & XSS prevention
- Account recovery one-time token lifecycle
"""

import time
import json
import hmac
import hashlib
import unittest
from unittest.mock import MagicMock, patch

import config
import auth
import utils
import database

class TestTelegramAuthentication(unittest.TestCase):
    def setUp(self):
        self.bot_token = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_TEST"
        self._orig_bot_token = config.BOT_TOKEN
        self._orig_dev_auth = config.DEV_AUTH_ENABLED
        self._orig_dev_user_id = config.DEV_USER_ID
        config.BOT_TOKEN = self.bot_token
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0

    def tearDown(self):
        config.BOT_TOKEN = self._orig_bot_token
        config.DEV_AUTH_ENABLED = self._orig_dev_auth
        config.DEV_USER_ID = self._orig_dev_user_id

    def _generate_valid_init_data(self, user_id=12345, auth_date=None, extra_params=None):
        if auth_date is None:
            auth_date = int(time.time())
        
        user_dict = {
            "id": user_id,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser"
        }
        params = {
            "auth_date": str(auth_date),
            "query_id": "AAHdF6IQAAAAAN0XohDhr123",
            "user": json.dumps(user_dict, separators=(',', ':'))
        }
        if extra_params:
            params.update(extra_params)
            
        data_check_list = [f"{k}={v}" for k, v in sorted(params.items())]
        data_check_string = "\n".join(data_check_list)
        
        secret_key = hmac.new(b"WebAppData", self.bot_token.encode("utf-8"), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        
        from urllib.parse import urlencode
        params["hash"] = calc_hash
        return urlencode(params)

    def test_valid_init_data_passes(self):
        init_data = self._generate_valid_init_data(user_id=88888)
        user = auth.validate_telegram_init_data(init_data, max_age_seconds=86400)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 88888)
        self.assertEqual(user["username"], "testuser")

    def test_invalid_hash_rejected(self):
        init_data = self._generate_valid_init_data(user_id=88888)
        tampered = init_data.replace("hash=", "hash=deadbeef")
        user = auth.validate_telegram_init_data(tampered)
        self.assertIsNone(user)

    def test_tampered_user_id_rejected(self):
        init_data = self._generate_valid_init_data(user_id=88888)
        tampered = init_data.replace("88888", "99999")
        user = auth.validate_telegram_init_data(tampered)
        self.assertIsNone(user)

    def test_expired_init_data_rejected(self):
        old_date = int(time.time()) - (86400 * 2)
        init_data = self._generate_valid_init_data(user_id=88888, auth_date=old_date)
        user = auth.validate_telegram_init_data(init_data, max_age_seconds=86400)
        self.assertIsNone(user)

    def test_missing_init_data_rejected(self):
        self.assertIsNone(auth.validate_telegram_init_data(""))
        self.assertIsNone(auth.validate_telegram_init_data(None))

    def test_session_token_lifecycle(self):
        token = auth.create_session_token(12345, {"id": 12345, "username": "alice"}, ttl_seconds=1)
        self.assertIsNotNone(token)
        user = auth.get_user_from_session_token(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 12345)

        time.sleep(1.5)
        self.assertIsNone(auth.get_user_from_session_token(token))

    def test_dev_auth_only_when_explicitly_enabled(self):
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 9999
        self.assertIsNone(auth.validate_telegram_init_data("dev_auth_fake"))

        config.DEV_AUTH_ENABLED = True
        user = auth.validate_telegram_init_data("any_thing")
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 9999)


class TestSecurityUtilities(unittest.TestCase):
    def test_filename_sanitization(self):
        dirty = "../../etc/passwd\x00file.png  "
        clean = utils.sanitize_filename(dirty)
        self.assertNotIn("..", clean)
        self.assertNotIn("/", clean)
        self.assertNotIn("\x00", clean)
        self.assertNotIn("\\", clean)
        self.assertEqual(clean, "etc_passwdfile.png")

        self.assertEqual(utils.sanitize_filename(""), "file")
        self.assertEqual(utils.sanitize_filename("   "), "file")

        xss_name = '<script>alert("xss")</script>.jpg'
        sanitized = utils.sanitize_filename(xss_name)
        self.assertNotIn("<", sanitized)
        self.assertNotIn(">", sanitized)
        self.assertNotIn('"', sanitized)

    def test_pin_hashing_and_verification(self):
        pin = "1234"
        hashed = utils.hash_pin(pin)
        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertTrue(utils.verify_pin(pin, hashed))
        self.assertFalse(utils.verify_pin("9999", hashed))
        self.assertFalse(utils.verify_pin("", hashed))

    def test_share_token_parsing_backward_compatibility(self):
        legacy = "xyztoken|exp:1700000000|pin:4321|lim:5|cnt:2"
        info = utils.parse_share_token(legacy)
        self.assertEqual(info["token"], "xyztoken")
        self.assertEqual(info["expires_at"], 1700000000)
        self.assertEqual(info["pin_hash"], "4321")
        self.assertEqual(info["limit"], 5)
        self.assertEqual(info["count"], 2)

        info2 = utils.parse_share_token("puretoken123")
        self.assertEqual(info2["token"], "puretoken123")
        self.assertIsNone(info2["expires_at"])
        self.assertIsNone(info2["pin_hash"])


class TestPublicSharePolicy(unittest.TestCase):
    def setUp(self):
        self.mock_file = {
            "id": 101,
            "user_id": 555,
            "file_name": "secret_doc.pdf",
            "is_trashed": False,
            "share_token": "valid_token_abc"
        }

    def test_public_share_valid(self):
        file_data, err = database.validate_public_share(self.mock_file)
        self.assertIsNotNone(file_data)
        self.assertEqual(file_data["id"], 101)
        self.assertIsNone(err)

    def test_public_share_trashed_file_denied(self):
        trashed_file = dict(self.mock_file, is_trashed=True)
        file_data, err = database.validate_public_share(trashed_file)
        self.assertIsNone(file_data)
        self.assertEqual(err, "NOT_FOUND")

    def test_public_share_expired_denied(self):
        expired_token = f"token123|exp:{int(time.time()) - 3600}"
        expired_file = dict(self.mock_file, share_token=expired_token)
        file_data, err = database.validate_public_share(expired_file)
        self.assertIsNone(file_data)
        self.assertEqual(err, "EXPIRED")

    def test_public_share_pin_protection(self):
        pin_hash = utils.hash_pin("7890")
        pin_token = f"token123|pinhash:{pin_hash}"
        pin_file = dict(self.mock_file, share_token=pin_token)

        # Access with no PIN -> returns (file, PIN_REQUIRED)
        file_data, err = database.validate_public_share(pin_file, pin=None)
        self.assertEqual(err, "PIN_REQUIRED")

        # Access with wrong PIN -> returns (None, PIN_INCORRECT)
        file_data, err = database.validate_public_share(pin_file, pin="0000")
        self.assertIsNone(file_data)
        self.assertEqual(err, "PIN_INCORRECT")

        # Access with correct PIN -> returns (file, None)
        file_data, err = database.validate_public_share(pin_file, pin="7890")
        self.assertIsNotNone(file_data)
        self.assertIsNone(err)

    def test_public_share_download_limit_exhausted(self):
        exhausted_token = "token123|lim:3|cnt:3"
        exhausted_file = dict(self.mock_file, share_token=exhausted_token)
        file_data, err = database.validate_public_share(exhausted_file)
        self.assertIsNone(file_data)
        self.assertEqual(err, "LIMIT_EXHAUSTED")


class TestOwnershipAndRelationalIntegrity(unittest.TestCase):
    @patch("database.get_file")
    def test_get_file_for_user_prevents_idor(self, mock_get_file):
        mock_get_file.side_effect = lambda fid, user_id=None: (
            {"id": 999, "user_id": 2, "file_name": "victim.png"} if user_id == 2 else None
        )
        
        # User 1 cannot access User 2's file
        self.assertIsNone(database.get_file_for_user(999, 1))

        # User 2 can access
        result = database.get_file_for_user(999, 2)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], 999)

    @patch("database.get_folder")
    def test_get_folder_for_user_prevents_idor(self, mock_get_folder):
        mock_get_folder.side_effect = lambda fid, user_id=None: (
            {"id": 50, "user_id": 2, "name": "Private Folder"} if user_id == 2 else None
        )
        
        self.assertIsNone(database.get_folder_for_user(50, 1))
        self.assertIsNotNone(database.get_folder_for_user(50, 2))

    @patch("database.get_folder")
    def test_circular_folder_prevention(self, mock_get_folder):
        folders = {
            1: {"id": 1, "user_id": 10, "parent_id": None},
            2: {"id": 2, "user_id": 10, "parent_id": 1},
            3: {"id": 3, "user_id": 10, "parent_id": 2},
        }
        mock_get_folder.side_effect = lambda fid, user_id=None: folders.get(fid)

        # Cannot move folder into itself
        self.assertFalse(database.move_folder_for_user(1, 10, 1))

        # Cannot move parent (1) into descendant (3)
        self.assertFalse(database.move_folder_for_user(1, 10, 3))


class TestAccountRecoveryCode(unittest.TestCase):
    def test_recovery_code_generation_and_redemption(self):
        user_id = 7777
        code = database.generate_account_recovery_code(user_id, expiry_hours=1)
        self.assertTrue(code.startswith("DREC-"))
        self.assertEqual(len(code), 14) # DREC-xxxx-xxxx

        new_user_id = 8888
        with patch("database.transfer_user_data", return_value={"total_files": 0}):
            ok, msg, stats = database.redeem_account_recovery_code(code, new_user_id)
            self.assertTrue(ok)
            self.assertIn("berhasil", msg.lower())

            # Attempt to reuse code (one-time requirement)
            ok_reuse, msg_reuse, stats_reuse = database.redeem_account_recovery_code(code, new_user_id)
            self.assertFalse(ok_reuse)
            self.assertIn("tidak valid", msg_reuse.lower())


import tornado.testing
import webapp


class TestTornadoHttpEndpoints(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        config.DEV_AUTH_ENABLED = False
        config.DEV_USER_ID = 0
        return tornado.web.Application(webapp.build_app_routes())

    def test_unauthenticated_drive_rejected(self):
        # Raw request without auth header
        response = self.fetch("/api/drive")
        self.assertEqual(response.code, 401)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_client_supplied_user_id_ignored_and_rejected(self):
        # User tries to access another user's drive via query parameter
        response = self.fetch("/api/drive?user_id=999999")
        self.assertEqual(response.code, 401)
        data = json.loads(response.body.decode("utf-8"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "UNAUTHORIZED")

    def test_unauthenticated_post_endpoints_rejected(self):
        for endpoint, payload in [
            ("/api/star", json.dumps({"file_id": 1})),
            ("/api/rename", json.dumps({"id": 1, "new_name": "hacked"})),
            ("/api/create_folder", json.dumps({"name": "evil_folder"})),
            ("/api/batch_delete", json.dumps({"file_ids": [1, 2]})),
            ("/api/batch_move", json.dumps({"file_ids": [1], "target_folder_id": 2})),
            ("/api/clean_duplicates", json.dumps({})),
            ("/api/empty_trash", json.dumps({})),
        ]:
            response = self.fetch(endpoint, method="POST", body=payload, headers={"Content-Type": "application/json"})
            self.assertEqual(response.code, 401, f"{endpoint} did not return 401 when unauthenticated")

    def test_unauthenticated_media_rejected(self):
        response = self.fetch("/api/download?file_id=1")
        self.assertEqual(response.code, 401)

        response2 = self.fetch("/api/thumbnail?file_id=1")
        self.assertEqual(response2.code, 401)

    def test_health_and_ping_accessible(self):
        res1 = self.fetch("/api/ping")
        self.assertEqual(res1.code, 200)
        self.assertIn("awake", res1.body.decode("utf-8"))

        res2 = self.fetch("/health")
        self.assertEqual(res2.code, 200)

    @patch("database.get_folder_by_share_token", return_value=None)
    def test_public_dropzone_info_invalid_token(self, mock_get_folder):
        res = self.fetch("/api/dropzone/info?token=invalid_token_123")
        self.assertEqual(res.code, 404)
        data = json.loads(res.body.decode("utf-8"))
        self.assertFalse(data["ok"])


if __name__ == "__main__":
    unittest.main()
