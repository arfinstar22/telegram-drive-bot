"""Centralized Authentication Module for Telegram WebApp / Mini App.

Implements official Telegram WebApp HMAC-SHA256 signature verification,
signed session tokens for media streaming, and dev-mode isolation.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from typing import Optional

import tornado.web

import config
from config import (
    BOT_TOKEN,
    DEV_AUTH_ENABLED,
    DEV_USER_ID,
    INIT_DATA_MAX_AGE_SECONDS,
)

log = logging.getLogger(__name__)

def get_telegram_secret_key(bot_token: Optional[str] = None) -> bytes:
    token = bot_token or config.BOT_TOKEN
    return hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()


def get_session_secret(bot_token: Optional[str] = None) -> bytes:
    token = bot_token or config.BOT_TOKEN
    return hmac.new(token.encode("utf-8"), b"DarfinStorageSessionKey_v1", hashlib.sha256).digest()


def validate_telegram_init_data(
    init_data_raw: str, max_age_seconds: int = INIT_DATA_MAX_AGE_SECONDS
) -> Optional[dict]:
    """Validate raw Telegram WebApp initData string using official HMAC-SHA256.

    Returns dict with authenticated user info if valid, else None.
    """
    if config.DEV_AUTH_ENABLED and config.DEV_USER_ID:
        return {
            "id": config.DEV_USER_ID,
            "user_id": config.DEV_USER_ID,
            "username": "dev_user",
            "first_name": "Dev User",
            "auth_type": "dev",
        }

    if not init_data_raw or not isinstance(init_data_raw, str):
        return None

    try:
        parsed_items = urllib.parse.parse_qsl(init_data_raw, keep_blank_values=True)
        if not parsed_items:
            return None

        params = dict(parsed_items)
        received_hash = params.get("hash")
        if not received_hash:
            return None

        # Sort remaining key-value pairs alphabetically
        sorted_pairs = sorted(
            [(k, v) for k, v in parsed_items if k != "hash"], key=lambda item: item[0]
        )
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)

        # Calculate HMAC-SHA256 signature
        secret_key = get_telegram_secret_key()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison
        if not hmac.compare_digest(calculated_hash.lower(), received_hash.lower()):
            return None

        # Check auth_date
        auth_date_raw = params.get("auth_date")
        if not auth_date_raw or not auth_date_raw.isdigit():
            return None

        auth_date = int(auth_date_raw)
        now = int(time.time())

        # Disallow auth_date far in future (max 60s clock skew)
        if auth_date > now + 60:
            return None

        # Disallow expired/stale auth_date
        if max_age_seconds > 0 and (now - auth_date) > max_age_seconds:
            return None

        # Parse user field
        user_raw = params.get("user")
        if not user_raw:
            return None

        user_data = json.loads(user_raw)
        user_id = user_data.get("id")
        if not user_id or not isinstance(user_id, int):
            return None

        return {
            "id": user_id,
            "user_id": user_id,
            "username": user_data.get("username"),
            "first_name": user_data.get("first_name", ""),
            "last_name": user_data.get("last_name", ""),
            "auth_date": auth_date,
            "raw_user": user_data,
        }
    except Exception as exc:
        log.debug("initData validation error: %s", exc)
        return None


def create_session_token(
    user_id: int,
    user_info: Optional[dict] = None,
    duration_seconds: int = 86400,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Create a tamper-proof signed session token for media/download streams."""
    dur = ttl_seconds if ttl_seconds is not None else duration_seconds
    expires_at = int(time.time()) + dur
    nonce = secrets.token_hex(8)
    payload = f"{user_id}:{expires_at}:{nonce}"
    sig = hmac.new(
        get_session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_session_token(token: str) -> Optional[int]:
    """Verify signed session token. Returns user_id if valid and not expired, else None."""
    if not token or not isinstance(token, str):
        return None

    parts = token.split(":")
    if len(parts) != 4:
        return None

    user_id_str, exp_str, nonce, received_sig = parts
    if not user_id_str.isdigit() or not exp_str.isdigit():
        return None

    payload = f"{user_id_str}:{exp_str}:{nonce}"
    expected_sig = hmac.new(
        get_session_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_sig.lower(), received_sig.lower()):
        return None

    if int(exp_str) <= int(time.time()):
        return None

    return int(user_id_str)


def get_user_from_session_token(token: str) -> Optional[dict]:
    """Retrieve user dict if session token is valid and not expired."""
    uid = verify_session_token(token)
    if uid:
        return {"id": uid, "user_id": uid}
    return None


def authenticate_request(handler: tornado.web.RequestHandler) -> Optional[dict]:
    """Extract and authenticate user identity from the incoming request.

    Priority:
    1. Explicit local DEV auth (if DEV_AUTH_ENABLED is True and DEV_USER_ID set)
    2. Header: X-Telegram-Init-Data
    3. Header: Authorization (tma <initData> or Bearer <session_token>)
    4. Cookie: tma_session (<session_token>)
    5. Query param: auth (<session_token>, useful for media tags)
    """
    # 1. Dev Auth (Safe: requires explicit config, never enabled by default in prod)
    if DEV_AUTH_ENABLED and DEV_USER_ID:
        return {
            "user_id": DEV_USER_ID,
            "username": "dev_user",
            "first_name": "Dev User",
            "auth_type": "dev",
        }

    # 2. X-Telegram-Init-Data header
    init_data_hdr = handler.request.headers.get("X-Telegram-Init-Data")
    if init_data_hdr:
        res = validate_telegram_init_data(init_data_hdr)
        if res:
            res["auth_type"] = "init_data_header"
            return res

    # 3. Authorization header
    auth_hdr = handler.request.headers.get("Authorization", "").strip()
    if auth_hdr:
        if auth_hdr.lower().startswith("tma "):
            token_val = auth_hdr[4:].strip()
            res = validate_telegram_init_data(token_val)
            if res:
                res["auth_type"] = "tma_header"
                return res
        elif auth_hdr.lower().startswith("bearer "):
            token_val = auth_hdr[7:].strip()
            uid = verify_session_token(token_val)
            if uid:
                return {"user_id": uid, "auth_type": "bearer_session"}
            # Fallback: check if bearer contained raw initData
            res = validate_telegram_init_data(token_val)
            if res:
                res["auth_type"] = "bearer_init_data"
                return res

    # 4. Cookie: tma_session
    cookie_val = handler.get_cookie("tma_session")
    if cookie_val:
        uid = verify_session_token(cookie_val)
        if uid:
            return {"user_id": uid, "auth_type": "cookie"}

    # 5. Query param: auth (for <img>, <video>, <audio> and direct downloads)
    auth_param = handler.get_argument("auth", None)
    if auth_param:
        uid = verify_session_token(auth_param)
        if uid:
            return {"user_id": uid, "auth_type": "query_session"}
        res = validate_telegram_init_data(auth_param)
        if res:
            res["auth_type"] = "query_init_data"
            return res

    return None


def get_authenticated_user(handler: tornado.web.RequestHandler) -> Optional[dict]:
    """Get authenticated user dict if already resolved or resolve it now."""
    if hasattr(handler, "_authenticated_user") and handler._authenticated_user:
        return handler._authenticated_user
    user = authenticate_request(handler)
    handler._authenticated_user = user
    return user


def require_authenticated_user(handler: tornado.web.RequestHandler) -> Optional[int]:
    """Enforce authentication on private endpoints.

    If authenticated, returns integer user_id.
    If unauthenticated, sends 401 Unauthorized JSON error and finishes request.
    """
    user = get_authenticated_user(handler)
    if not user or not user.get("user_id"):
        handler.set_status(401)
        handler.set_header("Content-Type", "application/json; charset=utf-8")
        handler.finish(
            json.dumps({
                "ok": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Autentikasi Telegram diperlukan. Buka WebApp melalui aplikasi Telegram.",
                },
            })
        )
        return None
    return user["user_id"]
