"""
Magic-link token + session cookie primitives.

Two token types:

  * **Magic token** — short-lived (15 min), embedded in the login email
    URL. Carries an email + expiry + HMAC signature. Verifying it creates
    a session cookie. Stateless — no DB lookup required.
  * **Session cookie** — 30-day, HMAC-signed, sets the authenticated
    identity. Read on every request via `current_user()`.

Both tokens use the shared AUTH_SECRET_KEY (falls back to ADMIN_SECRET_KEY
so a single secret works for small deployments).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Any

from fastapi import HTTPException, Request

from .users import get_user, upsert_user, is_valid_email


SESSION_COOKIE = "intellcluster_user"
MAGIC_TOKEN_TTL = 15 * 60          # 15 minutes
SESSION_TTL = 30 * 24 * 60 * 60    # 30 days


def _secret() -> str:
    return (
        os.environ.get("AUTH_SECRET_KEY")
        or os.environ.get("ADMIN_SECRET_KEY")
        or "change-me-in-production"
    )


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode())


def _sign(payload: str) -> str:
    sig = hmac.new(_secret().encode(), payload.encode(), hashlib.sha256).digest()
    return _b64e(sig)


def _verify_sig(payload: str, sig: str) -> bool:
    expected = _sign(payload)
    return hmac.compare_digest(sig, expected)


# ═══════════════════════════════════════════════════════════════════════
# Magic tokens — embedded in the email link
# ═══════════════════════════════════════════════════════════════════════


def create_magic_token(email: str) -> str:
    """Return a URL-safe token encoding (email, expiry). Valid for MAGIC_TOKEN_TTL."""
    if not is_valid_email(email):
        raise ValueError("invalid email")
    exp = int(time.time()) + MAGIC_TOKEN_TTL
    payload = f"{email.strip().lower()}|{exp}"
    sig = _sign(payload)
    return f"{_b64e(payload.encode())}.{sig}"


def verify_magic_token(token: str) -> str | None:
    """Return the email if the token is valid and unexpired, else None."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.rsplit(".", 1)
        payload = _b64d(payload_b64).decode()
        if not _verify_sig(payload, sig):
            return None
        email, exp_str = payload.split("|", 1)
        exp = int(exp_str)
        if time.time() > exp:
            return None
        if not is_valid_email(email):
            return None
        return email
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Session cookies — 30-day auth for the browser
# ═══════════════════════════════════════════════════════════════════════


def create_session_cookie(email: str) -> str:
    email = email.strip().lower()
    exp = int(time.time()) + SESSION_TTL
    payload = f"{email}|{exp}"
    sig = _sign(payload)
    return f"{_b64e(payload.encode())}.{sig}"


def verify_session_cookie(cookie_value: str | None) -> str | None:
    if not cookie_value or "." not in cookie_value:
        return None
    try:
        payload_b64, sig = cookie_value.rsplit(".", 1)
        payload = _b64d(payload_b64).decode()
        if not _verify_sig(payload, sig):
            return None
        email, exp_str = payload.split("|", 1)
        if time.time() > int(exp_str):
            return None
        if not is_valid_email(email):
            return None
        return email
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Request helpers — drop into any FastAPI handler
# ═══════════════════════════════════════════════════════════════════════


def current_user(request: Request) -> dict[str, Any] | None:
    """Return the signed-in user row (or None). Non-raising."""
    token = request.cookies.get(SESSION_COOKIE)
    email = verify_session_cookie(token)
    if not email:
        return None
    return get_user(email)


def require_user(request: Request) -> dict[str, Any]:
    """Return the signed-in user row or raise 401. Use as a FastAPI dependency."""
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def bind_login(email: str) -> dict[str, Any]:
    """Record a successful login, creating the user on first visit."""
    return upsert_user(email)
