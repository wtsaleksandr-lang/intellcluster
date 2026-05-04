"""
Magic-link token + session cookie primitives.

Two token types:

  * **Magic token** — short-lived (15 min), embedded in the login email
    URL. Carries an email + expiry + HMAC signature. Verifying it creates
    a session cookie. One-time-use: the signature is recorded in a small
    ledger after `verify_magic_token` returns successfully, so reusing a
    leaked link (browser history, mail forwarding) gets rejected.
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
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

from .users import get_user, upsert_user, is_valid_email


SESSION_COOKIE = "intellcluster_user"
MAGIC_TOKEN_TTL = 15 * 60          # 15 minutes
SESSION_TTL = 30 * 24 * 60 * 60    # 30 days

_USED_TOKENS_FILE = Path("history/auth_used_tokens.jsonl")
_used_tokens_lock = threading.RLock()
_used_tokens_cache: set[str] | None = None  # in-memory mirror of the ledger
_USED_TOKENS_GC_AGE = MAGIC_TOKEN_TTL + 60  # entries past expiry can be forgotten


def _warm_used_tokens() -> set[str]:
    seen: set[str] = set()
    if not _USED_TOKENS_FILE.exists():
        return seen
    cutoff = time.time() - _USED_TOKENS_GC_AGE
    with open(_USED_TOKENS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sig, _, ts = line.partition("|")
            try:
                if float(ts) >= cutoff:
                    seen.add(sig)
            except ValueError:
                continue
    return seen


def _record_used_token(sig: str) -> None:
    global _used_tokens_cache
    with _used_tokens_lock:
        if _used_tokens_cache is None:
            _used_tokens_cache = _warm_used_tokens()
        if sig in _used_tokens_cache:
            return
        _USED_TOKENS_FILE.parent.mkdir(exist_ok=True)
        with open(_USED_TOKENS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{sig}|{int(time.time())}\n")
        _used_tokens_cache.add(sig)


def _is_token_used(sig: str) -> bool:
    global _used_tokens_cache
    with _used_tokens_lock:
        if _used_tokens_cache is None:
            _used_tokens_cache = _warm_used_tokens()
        return sig in _used_tokens_cache


_INSECURE_SECRET_MARKERS = ("change-me", "change-this", "default", "secret-key")


def _secret() -> str:
    """User-session HMAC secret. Refuses to operate on default placeholders so
    nobody can forge a session cookie on a misconfigured deploy."""
    s = os.environ.get("AUTH_SECRET_KEY") or os.environ.get("ADMIN_SECRET_KEY") or ""
    if not s or len(s) < 24 or any(m in s.lower() for m in _INSECURE_SECRET_MARKERS):
        raise RuntimeError(
            "AUTH_SECRET_KEY (or ADMIN_SECRET_KEY) is missing or insecure. "
            "Set a strong value (>=24 chars, no placeholder) in your .env."
        )
    return s


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


def verify_magic_token(token: str, *, consume: bool = True) -> str | None:
    """Return the email if the token is valid, unexpired, and unused.

    With consume=True (default) the signature is recorded in the used-tokens
    ledger BEFORE returning the email — so a second call with the same token
    yields None. Pass consume=False from non-binding paths (e.g. previews).
    """
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
        # One-time-use enforcement
        if _is_token_used(sig):
            return None
        if consume:
            _record_used_token(sig)
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
