#!/usr/bin/env python3
"""Task 6A — Darfin Standalone Browser Authentication Test Suite.

Comprehensive test suite covering:
1. Configuration validation
2. PKCE code_verifier and S256 code_challenge generation
3. State and Nonce generation, HMAC signing, expiration, tampering rejection
4. OIDC Start handler (/auth/telegram/start)
5. OIDC Callback handler (/auth/telegram/callback)
6. Token exchange and ID token cryptographic validation
7. Identity resolution and account consistency with Telegram Mini App
8. Session creation, cookie security (HttpOnly, Secure, SameSite)
9. CSRF protection on cookie-authenticated state-changing requests
10. Open redirect protection
11. Rate limiting on authentication routes
12. Logout handler (/auth/logout)
13. User profile endpoint (/api/auth/me)
14. Security: secret exposure prevention, XSS safety, CORS integrity
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import unittest
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
import tornado.testing
import tornado.web

import auth
import config
import database as db
import oidc
import webapp


class TestBrowserAuthBase(tornado.testing.AsyncHTTPTestCase):
    """Base setup for browser authentication test cases."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Generate persistent RSA key pair for testing token signatures
        cls.priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pub_key = cls.priv_key.public_key()
        cls.kid = "test-kid-1"
        cls.mock_jwk = MagicMock()
        cls.mock_jwk.key = cls.pub_key

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

        # Reset in-memory caches and rate limits for deterministic tests
        webapp._RATE_LIMITS.clear()
        oidc._JWKS_CACHE.clear()

    def tearDown(self):
        config.TELEGRAM_OIDC_CLIENT_ID = self.orig_client_id
        config.TELEGRAM_OIDC_CLIENT_SECRET = self.orig_client_secret
        config.TELEGRAM_OIDC_REDIRECT_URI = self.orig_redirect_uri
        webapp._RATE_LIMITS.clear()
        super().tearDown()

    def get_app(self):
        return tornado.web.Application(webapp.build_app_routes())

    def create_test_id_token(
        self,
        sub: str = "778899",
        aud: str = "test_telegram_client_id",
        iss: str = "https://oauth.telegram.org",
        exp_delta: int = 3600,
        nonce: str | None = None,
        kid: str = "test-kid-1",
        name: str = "Darfin User",
        username: str = "darfin_user",
    ) -> str:
        payload = {
            "sub": sub,
            "id": int(sub) if sub.isdigit() else sub,
            "aud": aud,
            "iss": iss,
            "exp": int(time.time()) + exp_delta,
            "iat": int(time.time()),
            "name": name,
            "preferred_username": username,
        }
        if nonce is not None:
            payload["nonce"] = nonce
        return jwt.encode(payload, self.priv_key, algorithm="RS256", headers={"kid": kid})


# ── 1. CONFIGURATION TESTS (Tests 1-5) ─────────────────────────────

class TestOidcConfiguration(unittest.TestCase):
    """Test configuration guardrails and missing environment variables."""

    def test_missing_client_id_raises_value_error(self):
        """1. build_authorization_url raises ValueError if client ID is missing."""
        with self.assertRaises(ValueError) as ctx:
            oidc.build_authorization_url(state="st", code_challenge="ch", client_id="", redirect_uri="https://ex.com/cb")
        self.assertIn("TELEGRAM_OIDC_CLIENT_ID", str(ctx.exception))

    def test_missing_redirect_uri_raises_value_error(self):
        """2. build_authorization_url raises ValueError if redirect URI is missing."""
        with self.assertRaises(ValueError) as ctx:
            oidc.build_authorization_url(state="st", code_challenge="ch", client_id="cid", redirect_uri="")
        self.assertIn("TELEGRAM_OIDC_REDIRECT_URI", str(ctx.exception))

    def test_token_exchange_missing_client_secret(self):
        """3. exchange_code_for_tokens raises ValueError if client secret is missing."""
        with self.assertRaises(ValueError) as ctx:
            oidc.exchange_code_for_tokens(code="c", code_verifier="v", client_id="cid", client_secret="", redirect_uri="https://ex.com/cb")
        self.assertIn("TELEGRAM_OIDC_CLIENT_SECRET", str(ctx.exception))

    def test_token_exchange_missing_client_id(self):
        """4. exchange_code_for_tokens raises ValueError if client_id is missing."""
        with self.assertRaises(ValueError) as ctx:
            oidc.exchange_code_for_tokens(code="c", code_verifier="v", client_id="", client_secret="sec", redirect_uri="https://ex.com/cb")
        self.assertIn("TELEGRAM_OIDC_CLIENT_ID", str(ctx.exception))

    def test_default_issuer_points_to_official_telegram(self):
        """5. Default issuer points to official Telegram OAuth authority."""
        self.assertEqual(config.TELEGRAM_OIDC_ISSUER, "https://oauth.telegram.org")
        self.assertEqual(config.TELEGRAM_OIDC_AUTH_URL, "https://oauth.telegram.org/auth")
        self.assertEqual(config.TELEGRAM_OIDC_TOKEN_URL, "https://oauth.telegram.org/token")


# ── 2. PKCE TESTS (Tests 6-10) ───────────────────────────────────

class TestOidcPKeyExchange(unittest.TestCase):
    """Test RFC 7636 PKCE S256 code challenge and verifier mechanics."""

    def test_code_verifier_length_and_entropy(self):
        """6. Code verifier is URL-safe and of sufficient length."""
        v1 = oidc.generate_code_verifier(64)
        v2 = oidc.generate_code_verifier(64)
        self.assertNotEqual(v1, v2)
        self.assertGreaterEqual(len(v1), 43)

    def test_code_challenge_s256_computation(self):
        """7. Code challenge matches S256 base64url(SHA256(verifier))."""
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        actual = oidc.generate_code_challenge(verifier)
        self.assertEqual(actual, expected)

    def test_code_challenge_reproducibility(self):
        """8. Identical verifier produces identical challenge."""
        v = "test_fixed_verifier_12345"
        self.assertEqual(oidc.generate_code_challenge(v), oidc.generate_code_challenge(v))

    def test_code_challenge_mismatch(self):
        """9. Different verifiers produce different challenges."""
        v1 = oidc.generate_code_verifier()
        v2 = oidc.generate_code_verifier()
        self.assertNotEqual(oidc.generate_code_challenge(v1), oidc.generate_code_challenge(v2))

    def test_code_challenge_no_padding(self):
        """10. Code challenge contains no base64 padding '=' characters."""
        for _ in range(5):
            verifier = oidc.generate_code_verifier()
            challenge = oidc.generate_code_challenge(verifier)
            self.assertNotIn("=", challenge)


# ── 3. STATE AND NONCE TESTS (Tests 11-18) ───────────────────────

class TestOidcStateAndNonce(unittest.TestCase):
    """Test CSRF state and replay-prevention nonce generation and verification."""

    def test_state_generation_unique(self):
        """11. Generated states are cryptographically random and unique."""
        s1 = oidc.generate_state()
        s2 = oidc.generate_state()
        self.assertNotEqual(s1, s2)
        self.assertGreaterEqual(len(s1), 32)

    def test_nonce_generation_unique(self):
        """12. Generated nonces are cryptographically random and unique."""
        n1 = oidc.generate_nonce()
        n2 = oidc.generate_nonce()
        self.assertNotEqual(n1, n2)
        self.assertGreaterEqual(len(n1), 32)

    def test_state_cookie_roundtrip_valid(self):
        """13. Valid state cookie value verifies successfully."""
        state = oidc.generate_state()
        nonce = oidc.generate_nonce()
        verifier = oidc.generate_code_verifier()
        cookie_val = oidc.create_state_cookie_value(state, verifier, nonce, next_path="/webapp", max_age=300)

        verified = oidc.verify_state_cookie_value(cookie_val, expected_state=state)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["state"], state)
        self.assertEqual(verified["nonce"], nonce)
        self.assertEqual(verified["verifier"], verifier)
        self.assertEqual(verified["next_path"], "/webapp")

    def test_state_cookie_mismatched_state_rejected(self):
        """14. Mismatched query state versus cookie state returns None."""
        state = oidc.generate_state()
        cookie_val = oidc.create_state_cookie_value(state, "verif", "nonce", next_path="/")
        result = oidc.verify_state_cookie_value(cookie_val, expected_state="different_forged_state")
        self.assertIsNone(result)

    def test_state_cookie_tampered_signature_rejected(self):
        """15. Tampered cookie value fails HMAC signature check."""
        state = oidc.generate_state()
        cookie_val = oidc.create_state_cookie_value(state, "verif", "nonce", next_path="/")
        tampered = cookie_val[:-4] + "ffff"
        result = oidc.verify_state_cookie_value(tampered, expected_state=state)
        self.assertIsNone(result)

    def test_state_cookie_expired_rejected(self):
        """16. Expired state cookie returns None."""
        state = oidc.generate_state()
        cookie_val = oidc.create_state_cookie_value(state, "verif", "nonce", max_age=-10)
        result = oidc.verify_state_cookie_value(cookie_val, expected_state=state)
        self.assertIsNone(result)

    def test_state_cookie_malformed_rejected(self):
        """17. Malformed state cookie string returns None without throwing."""
        self.assertIsNone(oidc.verify_state_cookie_value("invalid:cookie", "state"))
        self.assertIsNone(oidc.verify_state_cookie_value("", "state"))
        self.assertIsNone(oidc.verify_state_cookie_value(None, "state"))

    def test_state_cookie_tampered_payload_rejected(self):
        """18. Tampering with payload invalidates signature check."""
        state = oidc.generate_state()
        cookie_val = oidc.create_state_cookie_value(state, "verif", "nonce", next_path="/")
        tampered_val = ("A" if cookie_val[0] != "A" else "B") + cookie_val[1:]
        self.assertIsNone(oidc.verify_state_cookie_value(tampered_val, expected_state=state))


# ── 4. OPEN REDIRECT SANITIZATION (Tests 19-24) ──────────────────

class TestOpenRedirectProtection(unittest.TestCase):
    """Test sanitization of redirect destinations."""

    def test_relative_path_allowed(self):
        """19. Standard relative paths are permitted."""
        self.assertEqual(oidc.sanitize_redirect_path("/drive"), "/drive")
        self.assertEqual(oidc.sanitize_redirect_path("/webapp?folder=1"), "/webapp?folder=1")

    def test_external_scheme_rejected(self):
        """20. Absolute external URLs fallback to root."""
        self.assertEqual(oidc.sanitize_redirect_path("https://evil.example.com/pwn"), "/")
        self.assertEqual(oidc.sanitize_redirect_path("http://attacker.com"), "/")

    def test_protocol_relative_url_rejected(self):
        """21. Protocol-relative // URLs fallback to root."""
        self.assertEqual(oidc.sanitize_redirect_path("//evil.example.com"), "/")

    def test_backslash_rejected(self):
        """22. Backslash URLs fallback to root."""
        self.assertEqual(oidc.sanitize_redirect_path("/\\evil.com"), "/")

    def test_javascript_scheme_rejected(self):
        """23. Javascript scheme fallbacks to root."""
        self.assertEqual(oidc.sanitize_redirect_path("javascript:alert(1)"), "/")

    def test_empty_or_none_defaults_to_root(self):
        """24. None, empty, or non-string inputs fallback to root."""
        self.assertEqual(oidc.sanitize_redirect_path(""), "/")
        self.assertEqual(oidc.sanitize_redirect_path(None), "/")


# ── 5. ID TOKEN CRYPTOGRAPHIC VALIDATION (Tests 25-33) ────────────

class TestOidcIdTokenValidation(TestBrowserAuthBase):
    """Test cryptographic validation of Telegram ID Tokens."""

    def test_valid_id_token_verifies_successfully(self):
        """25. Valid token with correct signature, issuer, audience, and nonce succeeds."""
        token = self.create_test_id_token(sub="10001", nonce="valid_nonce_123")
        claims = oidc.validate_id_token(
            token,
            expected_nonce="valid_nonce_123",
            client_id="test_telegram_client_id",
            issuer="https://oauth.telegram.org",
            jwks_keys={self.kid: self.mock_jwk},
        )
        self.assertEqual(claims["sub"], "10001")
        self.assertEqual(claims["name"], "Darfin User")

    def test_expired_id_token_rejected(self):
        """26. Expired ID token raises ValueError."""
        token = self.create_test_id_token(exp_delta=-60)
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(token, client_id="test_telegram_client_id", jwks_keys={self.kid: self.mock_jwk})
        self.assertIn("expired", str(ctx.exception).lower())

    def test_audience_mismatch_rejected(self):
        """27. ID token with wrong audience raises ValueError."""
        token = self.create_test_id_token(aud="different_client_id")
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(token, client_id="test_telegram_client_id", jwks_keys={self.kid: self.mock_jwk})
        self.assertIn("audience", str(ctx.exception).lower())

    def test_issuer_mismatch_rejected(self):
        """28. ID token with wrong issuer raises ValueError."""
        token = self.create_test_id_token(iss="https://fake-oauth.example.com")
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(token, client_id="test_telegram_client_id", jwks_keys={self.kid: self.mock_jwk})
        self.assertIn("issuer", str(ctx.exception).lower())

    def test_nonce_mismatch_rejected(self):
        """29. ID token with mismatched nonce raises ValueError."""
        token = self.create_test_id_token(nonce="actual_nonce")
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(
                token,
                expected_nonce="expected_different_nonce",
                client_id="test_telegram_client_id",
                jwks_keys={self.kid: self.mock_jwk},
            )
        self.assertIn("nonce", str(ctx.exception).lower())

    def test_unknown_kid_rejected(self):
        """30. ID token with unknown key ID raises ValueError."""
        token = self.create_test_id_token(kid="unknown-kid")
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(
                token,
                client_id="test_telegram_client_id",
                jwks_keys={self.kid: self.mock_jwk},
            )
        self.assertIn("unknown key id", str(ctx.exception).lower())

    def test_bad_signature_rejected(self):
        """31. ID token signed with different key raises ValueError."""
        other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        tampered_token = jwt.encode(
            {"sub": "10001", "aud": "test_telegram_client_id", "iss": "https://oauth.telegram.org", "exp": 9999999999},
            other_priv,
            algorithm="RS256",
            headers={"kid": self.kid},
        )
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(
                tampered_token,
                client_id="test_telegram_client_id",
                jwks_keys={self.kid: self.mock_jwk},
            )
        self.assertIn("signature validation failed", str(ctx.exception).lower())

    def test_missing_sub_rejected(self):
        """32. ID token missing 'sub' claim raises ValueError."""
        payload = {
            "aud": "test_telegram_client_id",
            "iss": "https://oauth.telegram.org",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, self.priv_key, algorithm="RS256", headers={"kid": self.kid})
        with self.assertRaises(ValueError) as ctx:
            oidc.validate_id_token(token, client_id="test_telegram_client_id", jwks_keys={self.kid: self.mock_jwk})
        self.assertIn("sub", str(ctx.exception).lower())

    def test_malformed_jwt_string_rejected(self):
        """33. Arbitrary non-JWT string raises ValueError."""
        with self.assertRaises(ValueError):
            oidc.validate_id_token("not.a.valid.jwt", client_id="test_telegram_client_id", jwks_keys={self.kid: self.mock_jwk})


# ── 6. TELEGRAM IDENTITY RESOLUTION (Tests 34-39) ────────────────

class TestTelegramIdentityResolution(unittest.TestCase):
    """Test extracting and validating Telegram numeric user ID."""

    def test_numeric_sub_string_resolved(self):
        """34. Numeric sub string resolves to integer."""
        self.assertEqual(oidc.resolve_telegram_user_id({"sub": "98765432"}), 98765432)

    def test_numeric_id_integer_resolved(self):
        """35. Numeric id integer resolves to integer."""
        self.assertEqual(oidc.resolve_telegram_user_id({"id": 12345678}), 12345678)

    def test_negative_or_zero_id_rejected(self):
        """36. Non-positive IDs are rejected with ValueError."""
        with self.assertRaises(ValueError):
            oidc.resolve_telegram_user_id({"sub": "0"})
        with self.assertRaises(ValueError):
            oidc.resolve_telegram_user_id({"sub": "-100"})

    def test_non_numeric_sub_rejected(self):
        """37. Text string sub is rejected."""
        with self.assertRaises(ValueError):
            oidc.resolve_telegram_user_id({"sub": "not_a_number"})

    def test_missing_sub_and_id_rejected(self):
        """38. Claims without sub or id are rejected."""
        with self.assertRaises(ValueError):
            oidc.resolve_telegram_user_id({"username": "john_doe"})

    def test_username_does_not_control_identity(self):
        """39. Username claim does NOT override Telegram numeric ID."""
        claims = {"sub": "55555", "preferred_username": "other_user"}
        self.assertEqual(oidc.resolve_telegram_user_id(claims), 55555)


# ── 7. OIDC START & CALLBACK ENDPOINT INTEGRATION (Tests 40-47) ───

class TestOidcEndpoints(TestBrowserAuthBase):
    """Integration tests for /auth/telegram/start and /auth/telegram/callback."""

    def test_oidc_start_redirects_to_telegram(self):
        """40. GET /auth/telegram/start sets tg_oidc_state cookie and redirects to Telegram."""
        response = self.fetch("/auth/telegram/start", follow_redirects=False)
        self.assertEqual(response.code, 302)
        location = response.headers.get("Location", "")
        self.assertIn("oauth.telegram.org/auth", location)
        self.assertIn("client_id=test_telegram_client_id", location)
        self.assertIn("response_type=code", location)
        self.assertIn("code_challenge=", location)
        self.assertIn("code_challenge_method=S256", location)

        # Check state cookie was set
        set_cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("tg_oidc_state=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)

    def test_oidc_start_503_when_unconfigured(self):
        """41. GET /auth/telegram/start returns 503 if client ID is unconfigured."""
        config.TELEGRAM_OIDC_CLIENT_ID = ""
        response = self.fetch("/auth/telegram/start", follow_redirects=False)
        self.assertEqual(response.code, 503)

    def test_oidc_callback_missing_params_redirects_error(self):
        """42. Callback with missing code/state redirects to /?auth_error=missing_params."""
        response = self.fetch("/auth/telegram/callback", follow_redirects=False)
        self.assertEqual(response.code, 302)
        self.assertIn("auth_error=missing_params", response.headers.get("Location", ""))

    def test_oidc_callback_user_cancelled_redirects_error(self):
        """43. Callback with error=access_denied redirects to /?auth_error=cancelled."""
        response = self.fetch("/auth/telegram/callback?error=access_denied", follow_redirects=False)
        self.assertEqual(response.code, 302)
        self.assertIn("auth_error=cancelled", response.headers.get("Location", ""))

    def test_oidc_callback_mismatched_state_rejected(self):
        """44. Callback with state not matching cookie redirects to /?auth_error=invalid_state."""
        valid_cookie = oidc.create_state_cookie_value("state_abc", "verifier", "nonce")
        response = self.fetch(
            "/auth/telegram/callback?code=mock_code&state=forged_state",
            headers={"Cookie": f"tg_oidc_state={valid_cookie}"},
            follow_redirects=False,
        )
        self.assertEqual(response.code, 302)
        self.assertIn("auth_error=invalid_state", response.headers.get("Location", ""))

    @patch("database.get_or_create_inbox_folder")
    @patch("database.upsert_user")
    @patch("oidc.validate_id_token")
    @patch("oidc.exchange_code_for_tokens")
    def test_oidc_callback_successful_login_flow(self, mock_exchange, mock_validate, mock_upsert, mock_inbox):
        """45. Successful OIDC callback sets session and CSRF cookies, redirects to destination."""
        state = "state_12345"
        verifier = "verifier_67890"
        nonce = "nonce_abcde"
        state_cookie = oidc.create_state_cookie_value(state, verifier, nonce, next_path="/webapp")

        mock_exchange.return_value = {"id_token": "mock.jwt.token", "access_token": "mock_at"}
        mock_validate.return_value = {
            "sub": "9001",
            "name": "Alex Telegram",
            "preferred_username": "alex_tg",
        }

        response = self.fetch(
            f"/auth/telegram/callback?code=valid_tg_code&state={state}",
            headers={"Cookie": f"tg_oidc_state={state_cookie}"},
            follow_redirects=False,
        )
        self.assertEqual(response.code, 302)
        self.assertEqual(response.headers.get("Location"), "/webapp")

        # Verify cookies
        set_cookies = response.headers.get_list("Set-Cookie")
        cookie_str = "; ".join(set_cookies)
        self.assertIn("tma_session=", cookie_str)
        self.assertIn("tma_csrf=", cookie_str)
        self.assertIn("HttpOnly", cookie_str)

        # Verify upsert user was called with Telegram user ID 9001
        mock_upsert.assert_called_once_with(user_id=9001, username="alex_tg", full_name="Alex Telegram")

    @patch("oidc.exchange_code_for_tokens", side_effect=Exception("Connection refused"))
    def test_oidc_callback_token_exchange_failure_handled_safely(self, mock_exchange):
        """46. Upstream network failure during token exchange redirects safely to auth_error."""
        state = "state_999"
        cookie = oidc.create_state_cookie_value(state, "v", "n")
        response = self.fetch(
            f"/auth/telegram/callback?code=mock_code&state={state}",
            headers={"Cookie": f"tg_oidc_state={cookie}"},
            follow_redirects=False,
        )
        self.assertEqual(response.code, 302)
        self.assertIn("auth_error=", response.headers.get("Location", ""))

    def test_oidc_logout_clears_cookies(self):
        """47. POST /auth/logout clears tma_session and tma_csrf cookies."""
        response = self.fetch("/auth/logout", method="POST", body="", follow_redirects=False)
        self.assertEqual(response.code, 302)
        cookie_headers = response.headers.get_list("Set-Cookie")
        cookie_str = "; ".join(cookie_headers)
        self.assertIn('tma_session=""', cookie_str)
        self.assertIn('tma_csrf=""', cookie_str)


# ── 8. CSRF PROTECTION TESTS (Tests 48-52) ────────────────────────

class TestCsrfProtection(TestBrowserAuthBase):
    """Test CSRF protection on browser cookie-authenticated requests."""

    def setUp(self):
        super().setUp()
        self.user_id = 9001
        self.session_token = auth.create_session_token(self.user_id)
        self.csrf_token = "valid_csrf_token_123"

    @patch("database.get_all_user_files", return_value=[])
    @patch("database.get_folders", return_value=[])
    @patch("database.get_storage_info", return_value={"total_size": 0, "by_type": {}, "size_by_type": {}})
    @patch("database.get_user", return_value={"id": 9001, "username": "test_user"})
    def test_get_request_cookie_auth_succeeds_without_csrf(self, mock_user, mock_storage, mock_folders, mock_files):
        """48. GET /api/drive does not require CSRF token for cookie-authenticated browser."""
        response = self.fetch(
            "/api/drive",
            headers={"Cookie": f"tma_session={self.session_token}"},
        )
        self.assertEqual(response.code, 200)

    @patch("database.get_file")
    def test_post_request_cookie_auth_fails_without_csrf(self, mock_get_file):
        """49. State-changing POST request with cookie auth but no CSRF token is rejected with 403."""
        mock_get_file.return_value = {"id": 1, "user_id": self.user_id}
        response = self.fetch(
            "/api/star",
            method="POST",
            body=json.dumps({"file_id": 1}),
            headers={
                "Cookie": f"tma_session={self.session_token}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 403)
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["error"]["code"], "CSRF_ERROR")

    @patch("database.toggle_star_file")
    @patch("database.get_file")
    def test_post_request_cookie_auth_succeeds_with_valid_csrf(self, mock_get_file, mock_star):
        """50. State-changing POST request with matching X-CSRF-Token and tma_csrf cookie succeeds."""
        mock_get_file.return_value = {"id": 1, "user_id": self.user_id, "is_starred": False}
        mock_star.return_value = True

        response = self.fetch(
            "/api/star",
            method="POST",
            body=json.dumps({"file_id": 1}),
            headers={
                "Cookie": f"tma_session={self.session_token}; tma_csrf={self.csrf_token}",
                "X-CSRF-Token": self.csrf_token,
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])

    @patch("database.toggle_star_file")
    @patch("database.get_file")
    def test_mini_app_bearer_request_exempt_from_csrf(self, mock_get_file, mock_star):
        """51. Mini App requests with Bearer Authorization header do not require CSRF token."""
        mock_get_file.return_value = {"id": 1, "user_id": self.user_id, "is_starred": False}
        mock_star.return_value = True

        response = self.fetch(
            "/api/star",
            method="POST",
            body=json.dumps({"file_id": 1}),
            headers={
                "Authorization": f"Bearer {self.session_token}",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 200)

    @patch("database.get_file")
    def test_mismatched_csrf_token_rejected(self, mock_get_file):
        """52. Mismatched X-CSRF-Token header versus tma_csrf cookie returns 403."""
        mock_get_file.return_value = {"id": 1, "user_id": self.user_id}
        response = self.fetch(
            "/api/star",
            method="POST",
            body=json.dumps({"file_id": 1}),
            headers={
                "Cookie": f"tma_session={self.session_token}; tma_csrf=token_a",
                "X-CSRF-Token": "token_b",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.code, 403)


# ── 9. AUTH ME ENDPOINT TESTS (Tests 53-55) ───────────────────────

class TestApiAuthMeEndpoint(TestBrowserAuthBase):
    """Test /api/auth/me behavior for authenticated and unauthenticated clients."""

    def test_auth_me_unauthenticated_returns_false(self):
        """53. GET /api/auth/me without session returns authenticated=False with 200 status."""
        response = self.fetch("/api/auth/me")
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertFalse(data["authenticated"])
        self.assertIsNone(data["user"])

    @patch("database.get_user")
    def test_auth_me_authenticated_returns_user_info(self, mock_get_user):
        """54. GET /api/auth/me with session cookie returns authenticated=True and user data."""
        mock_get_user.return_value = {"id": 9001, "username": "test_alex", "full_name": "Alex T"}
        token = auth.create_session_token(9001)

        response = self.fetch(
            "/api/auth/me",
            headers={"Cookie": f"tma_session={token}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["id"], 9001)
        self.assertEqual(data["user"]["username"], "test_alex")

    @patch("database.get_user")
    def test_auth_me_authenticated_with_bearer_token(self, mock_get_user):
        """55. GET /api/auth/me with Bearer token header works identically to cookie."""
        mock_get_user.return_value = {"id": 9002, "username": "tg_mobile", "full_name": "Mobile User"}
        token = auth.create_session_token(9002)

        response = self.fetch(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.code, 200)
        data = json.loads(response.body.decode("utf-8"))
        self.assertTrue(data["authenticated"])
        self.assertEqual(data["user"]["id"], 9002)


# ── 10. ACCOUNT CONSISTENCY & SECURITY (Tests 56-66) ──────────────

class TestAccountConsistencyAndSecurity(TestBrowserAuthBase):
    """Verify that browser OIDC and Telegram Mini App map to identical accounts."""

    @patch("database.get_user")
    def test_same_user_id_from_cookie_and_bearer(self, mock_get_user):
        """56. A user accessing via cookie or Bearer token resolves to identical user_id."""
        user_id = 9001
        mock_get_user.return_value = {"id": user_id, "username": "shared_user"}
        token = auth.create_session_token(user_id)

        # 1. Cookie access (Browser OIDC flow)
        res_cookie = self.fetch("/api/auth/me", headers={"Cookie": f"tma_session={token}"})
        data_cookie = json.loads(res_cookie.body.decode("utf-8"))

        # 2. Bearer header access (Mini App flow)
        res_bearer = self.fetch("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        data_bearer = json.loads(res_bearer.body.decode("utf-8"))

        self.assertEqual(data_cookie["user"]["id"], user_id)
        self.assertEqual(data_bearer["user"]["id"], user_id)
        self.assertEqual(data_cookie["user"]["id"], data_bearer["user"]["id"])

    def test_login_start_rate_limiting(self):
        """57. Repeated rapid calls to /auth/telegram/start are rate-limited with HTTP 429."""
        # Execute 25 requests in quick succession from same IP
        responses = [self.fetch("/auth/telegram/start", follow_redirects=False) for _ in range(25)]
        statuses = [r.code for r in responses]
        self.assertIn(429, statuses)

    @patch("database.get_user")
    def test_client_cannot_forge_user_id(self, mock_get_user):
        """58. URL param user_id or body user_id cannot override authenticated principal."""
        token = auth.create_session_token(9001)
        mock_get_user.return_value = {"id": 9001, "username": "legit_user"}

        # Attempt to impersonate user 9999 via query param
        response = self.fetch("/api/auth/me?user_id=9999", headers={"Cookie": f"tma_session={token}"})
        data = json.loads(response.body.decode("utf-8"))
        self.assertEqual(data["user"]["id"], 9001)

    def test_unauthenticated_api_request_rejected(self):
        """59. Accessing private endpoints without credentials returns 401."""
        response = self.fetch("/api/drive")
        self.assertEqual(response.code, 401)

    @patch("database.get_file")
    def test_cross_user_file_access_blocked(self, mock_get_file):
        """60. User A cannot access File owned by User B."""
        # Authenticated as 9001
        token = auth.create_session_token(9001)
        # Mock get_file returns None when file is not owned by user_id
        mock_get_file.side_effect = lambda fid, user_id=None: {"id": 100, "user_id": 9002, "file_name": "secret.pdf"} if user_id == 9002 else None

        response = self.fetch("/api/download?file_id=100", headers={"Cookie": f"tma_session={token}"})
        self.assertEqual(response.code, 404)

    def test_landing_page_renders_browser_login_button(self):
        """61. Visiting / in browser unauthenticated renders the Telegram login card."""
        response = self.fetch("/")
        self.assertEqual(response.code, 200)
        html = response.body.decode("utf-8")
        self.assertIn("id=\"browserNoticeCard\"", html)
        self.assertIn("/auth/telegram/start", html)
        self.assertIn("Continue with Telegram", html)

    def test_landing_page_displays_auth_error_alert(self):
        """62. Visiting /?auth_error=cancelled renders the error alert."""
        response = self.fetch("/?auth_error=cancelled")
        self.assertEqual(response.code, 200)
        html = response.body.decode("utf-8")
        self.assertIn("id=\"authErrorAlert\"", html)

    def test_cors_not_wildcard_when_origin_specified(self):
        """63. Private APIs do not return wildcard CORS header with credentials."""
        response = self.fetch("/api/auth/me", headers={"Origin": "https://example.com"})
        self.assertNotEqual(response.headers.get("Access-Control-Allow-Origin"), "*")

    def test_jwks_caching_and_ttl(self):
        """64. JWKS cache avoids repeated outbound HTTP calls within TTL."""
        oidc._JWKS_CACHE.clear()
        mock_key = MagicMock()
        mock_key.key = self.pub_key
        fake_keys = {"test-kid": mock_key}
        oidc._JWKS_CACHE["keys"] = fake_keys
        oidc._JWKS_CACHE["fetched_at"] = time.time()

        with patch("httpx.Client") as mock_http:
            res = oidc.get_jwks()
            self.assertEqual(res, fake_keys)
            mock_http.assert_not_called()

    def test_client_secret_never_in_authorization_url(self):
        """65. Authorization URL does not contain the client secret."""
        url = oidc.build_authorization_url(
            state="state123",
            code_challenge="chall123",
            client_id="cid123",
            redirect_uri="https://ex.com/cb",
        )
        self.assertNotIn("secret", url.lower())
        self.assertNotIn(config.TELEGRAM_OIDC_CLIENT_SECRET, url)

    def test_session_token_expiry_rejection(self):
        """66. Expired session token is rejected by auth.get_authenticated_user."""
        expired_token = auth.create_session_token(user_id=1234, duration_seconds=-10)
        req_handler = MagicMock()
        del req_handler._authenticated_user
        req_handler.get_cookie.return_value = expired_token
        req_handler.request.headers = {}
        result = auth.get_authenticated_user(req_handler)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
