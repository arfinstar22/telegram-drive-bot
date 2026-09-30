"""Telegram OpenID Connect (OIDC) Standalone Browser Authentication Core.

Implements official Telegram OIDC Authorization Code Flow with PKCE (S256),
cryptographic state verification, JWKS key caching, and ID Token signature validation.
100% deterministic local auth, zero external identity providers.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from typing import Any, Optional

import httpx
import jwt
from jwt import PyJWK

import config
from auth import get_session_secret

log = logging.getLogger(__name__)

# In-memory JWKS cache: { "keys": { kid: public_key }, "raw_jwks": dict, "fetched_at": float }
_JWKS_CACHE: dict[str, Any] = {
    "keys": {},
    "raw_jwks": {},
    "fetched_at": 0.0,
}
_JWKS_CACHE_TTL_SECONDS = 3600.0


# ── PKCE Generation ──────────────────────────────────────────────

def generate_code_verifier(length: int = 64) -> str:
    """Generate cryptographically secure random PKCE code verifier."""
    return secrets.token_urlsafe(length)


def generate_code_challenge(verifier: str) -> str:
    """Compute S256 code challenge from PKCE code verifier per RFC 7636."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ── State and Nonce Protection ───────────────────────────────────

def generate_state() -> str:
    """Generate cryptographically secure random OAuth state string."""
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """Generate cryptographically secure random OIDC nonce string."""
    return secrets.token_urlsafe(32)


def create_state_cookie_value(
    state: str,
    verifier: str,
    nonce: str,
    next_path: str = "/",
    max_age: int = 600,
) -> str:
    """Create signed, tamper-proof state cookie value binding state, verifier, and nonce."""
    exp = int(time.time()) + max_age
    clean_next = sanitize_redirect_path(next_path)
    # Payload format: state:nonce:verifier:next_path:exp
    payload = f"{state}:{nonce}:{verifier}:{clean_next}:{exp}"
    sig = hmac.new(
        get_session_secret(),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{sig}"


def verify_state_cookie_value(
    cookie_value: str | None,
    expected_state: str,
) -> dict[str, str] | None:
    """Verify signed state cookie value. Returns dict of parameters or None if invalid/expired."""
    if not cookie_value or not isinstance(cookie_value, str):
        return None

    parts = cookie_value.split(":")
    if len(parts) != 6:
        return None

    state, nonce, verifier, next_path, exp_str, received_sig = parts
    if not exp_str.isdigit():
        return None

    payload = f"{state}:{nonce}:{verifier}:{next_path}:{exp_str}"
    expected_sig = hmac.new(
        get_session_secret(),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig.lower(), received_sig.lower()):
        log.warning("OIDC state cookie HMAC signature mismatch")
        return None

    if int(exp_str) <= int(time.time()):
        log.warning("OIDC state cookie expired")
        return None

    if not hmac.compare_digest(state, expected_state):
        log.warning("OIDC state mismatch between query param and cookie")
        return None

    return {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "next_path": sanitize_redirect_path(next_path),
    }


def sanitize_redirect_path(path: str | None, default: str = "/") -> str:
    """Ensure redirect target is a safe internal relative path, blocking open redirects."""
    if not path or not isinstance(path, str):
        return default
    clean = path.strip()
    # Reject protocol-relative URLs (//), full URLs, and backslashes
    if not clean.startswith("/") or clean.startswith("//") or "\\" in clean:
        return default
    # Reject scheme prefixes in the path
    segment = clean.split("/")[1] if len(clean.split("/")) > 1 else ""
    if ":" in segment:
        return default
    return clean


# ── Authorization URL Builder ────────────────────────────────────

def build_authorization_url(
    state: str,
    code_challenge: str,
    nonce: str | None = None,
    redirect_uri: str | None = None,
    client_id: str | None = None,
    auth_url: str | None = None,
    scopes: str | None = None,
) -> str:
    """Construct Telegram OIDC authorization URL with PKCE parameters."""
    cid = client_id or config.TELEGRAM_OIDC_CLIENT_ID
    ruri = redirect_uri or config.TELEGRAM_OIDC_REDIRECT_URI
    aurl = auth_url or config.TELEGRAM_OIDC_AUTH_URL
    sc = scopes or config.TELEGRAM_OIDC_SCOPES

    if not cid:
        raise ValueError("TELEGRAM_OIDC_CLIENT_ID is not configured.")
    if not ruri:
        raise ValueError("TELEGRAM_OIDC_REDIRECT_URI is not configured.")

    params = {
        "client_id": cid,
        "redirect_uri": ruri,
        "response_type": "code",
        "scope": sc,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if nonce:
        params["nonce"] = nonce

    query_string = urllib.parse.urlencode(params)
    sep = "&" if "?" in aurl else "?"
    return f"{aurl}{sep}{query_string}"


# ── JWKS Retrieval & In-Memory Caching ───────────────────────────

def get_jwks(
    jwks_url: str | None = None,
    force_refresh: bool = False,
    http_client: httpx.Client | None = None,
) -> dict[str, PyJWK]:
    """Fetch and cache Telegram OIDC JWKS public keys.

    Handles gzip decompression and caches parsed PyJWK objects for fast lookup.
    """
    global _JWKS_CACHE
    now = time.time()
    url = jwks_url or config.TELEGRAM_OIDC_JWKS_URL

    if not force_refresh and _JWKS_CACHE.get("keys") and (now - _JWKS_CACHE.get("fetched_at", 0.0) < _JWKS_CACHE_TTL_SECONDS):
        return _JWKS_CACHE["keys"]

    client = http_client or httpx.Client(timeout=10.0)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content

        # Decompress gzip if raw content is gzipped
        if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
            content = gzip.decompress(content)

        data = json.loads(content.decode("utf-8"))
        keys_map: dict[str, PyJWK] = {}
        for k in data.get("keys", []):
            try:
                jwk_obj = PyJWK(k)
                if jwk_obj.key_id:
                    keys_map[jwk_obj.key_id] = jwk_obj
            except Exception as e:
                log.debug("Skipping unparseable JWK key: %s", e)

        _JWKS_CACHE = {
            "keys": keys_map,
            "raw_jwks": data,
            "fetched_at": now,
        }
        return keys_map
    except Exception as e:
        log.error("Failed to fetch Telegram JWKS from %s: %s", url, e)
        # If cache exists from earlier, return stale cache as fallback
        if _JWKS_CACHE.get("keys"):
            log.warning("Serving stale JWKS cache following fetch error")
            return _JWKS_CACHE["keys"]
        raise


def clear_jwks_cache() -> None:
    """Clear in-memory JWKS cache (useful for testing and key rotation)."""
    global _JWKS_CACHE
    _JWKS_CACHE = {
        "keys": {},
        "raw_jwks": {},
        "fetched_at": 0.0,
    }


# ── Token Exchange ───────────────────────────────────────────────

def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    redirect_uri: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    token_url: str | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Exchange authorization code and PKCE code_verifier for tokens at Telegram token endpoint."""
    cid = client_id or config.TELEGRAM_OIDC_CLIENT_ID
    csec = client_secret or config.TELEGRAM_OIDC_CLIENT_SECRET
    ruri = redirect_uri or config.TELEGRAM_OIDC_REDIRECT_URI
    turl = token_url or config.TELEGRAM_OIDC_TOKEN_URL

    if not cid:
        raise ValueError("TELEGRAM_OIDC_CLIENT_ID is not configured.")
    if not csec:
        raise ValueError("TELEGRAM_OIDC_CLIENT_SECRET is not configured.")
    if not ruri:
        raise ValueError("TELEGRAM_OIDC_REDIRECT_URI is not configured.")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": ruri,
        "client_id": cid,
        "client_secret": csec,
        "code_verifier": code_verifier,
    }

    client = http_client or httpx.Client(timeout=15.0)
    # Authenticate with Basic Auth and include client_id/client_secret in payload
    resp = client.post(
        turl,
        data=data,
        auth=(cid, csec),
        headers={"Accept": "application/json"},
    )
    if resp.status_code != 200:
        log.error("Telegram OIDC token exchange failed (HTTP %s): %s", resp.status_code, resp.text)
        raise RuntimeError(f"Token exchange failed with HTTP {resp.status_code}")

    tokens = resp.json()
    if not isinstance(tokens, dict) or "id_token" not in tokens:
        raise RuntimeError("Token exchange response did not contain an id_token")

    return tokens


# ── ID Token Validation ──────────────────────────────────────────

def validate_id_token(
    id_token: str,
    expected_nonce: str | None = None,
    client_id: str | None = None,
    issuer: str | None = None,
    jwks_keys: dict[str, PyJWK] | None = None,
) -> dict[str, Any]:
    """Cryptographically validate Telegram OIDC ID token.

    Verifies:
    1. Signature using Telegram JWKS public key matching kid
    2. Issuer matches TELEGRAM_OIDC_ISSUER (default https://oauth.telegram.org)
    3. Audience matches TELEGRAM_OIDC_CLIENT_ID
    4. Expiration date (exp)
    5. Nonce matches expected nonce (if nonce provided)
    6. Valid subject claim (sub or id)
    """
    cid = client_id or config.TELEGRAM_OIDC_CLIENT_ID
    iss = issuer or config.TELEGRAM_OIDC_ISSUER

    if not id_token or not isinstance(id_token, str):
        raise ValueError("Missing or invalid id_token string")

    # Read unverified header to extract kid
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as e:
        raise ValueError(f"Malformed ID token header: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise ValueError("ID token header missing 'kid' claim")

    # Obtain public key for kid
    keys = jwks_keys if jwks_keys is not None else get_jwks()
    if kid not in keys:
        # Try refreshing JWKS in case of recent key rotation
        if jwks_keys is None:
            keys = get_jwks(force_refresh=True)
        if kid not in keys:
            raise ValueError(f"Unknown key ID '{kid}' in ID token")

    pyjwk = keys[kid]
    public_key = pyjwk.key

    # Decode and verify signature, audience, issuer, expiration
    try:
        claims = jwt.decode(
            id_token,
            key=public_key,
            algorithms=["RS256", "ES256", "EdDSA", "ES256K"],
            audience=cid,
            issuer=iss,
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
            },
        )
    except jwt.ExpiredSignatureError as e:
        raise ValueError("ID token has expired") from e
    except jwt.InvalidAudienceError as e:
        raise ValueError("ID token audience mismatch") from e
    except jwt.InvalidIssuerError as e:
        raise ValueError("ID token issuer mismatch") from e
    except Exception as e:
        raise ValueError(f"ID token signature validation failed: {e}") from e

    # Validate nonce if expected
    if expected_nonce is not None:
        token_nonce = claims.get("nonce")
        if not token_nonce or not hmac.compare_digest(str(token_nonce), expected_nonce):
            raise ValueError("ID token nonce mismatch")

    # Ensure subject claim is present
    sub = claims.get("sub") or claims.get("id")
    if not sub:
        raise ValueError("ID token missing subject (sub or id) claim")

    return claims


def resolve_telegram_user_id(claims: dict[str, Any]) -> int:
    """Extract and validate numeric Telegram user ID from verified OIDC claims."""
    raw_id = claims.get("id") or claims.get("sub")
    if raw_id is None:
        raise ValueError("Claims do not contain a user identifier")

    try:
        uid = int(raw_id)
        if uid <= 0:
            raise ValueError("Telegram user ID must be positive")
        return uid
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid non-numeric Telegram user ID '{raw_id}'") from e
