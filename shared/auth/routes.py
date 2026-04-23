"""
Magic-link auth routes.

  GET  /login             → sign-in form (also "check your email" state)
  POST /auth/request-link → accept email, send magic link
  GET  /auth/verify?token → verify, set session cookie, redirect to /account
  POST /auth/logout       → clear session cookie
  GET  /account           → signed-in-only dashboard

Rate limiting is intentionally strict on /auth/request-link: we depend on
the sliding-window middleware in shared/rate_limit.py for general protection
but also dedupe by email in-process so one user can't trigger more than a
link every 30 seconds (prevents mailbox floods if the submit button is
hammered).
"""

from __future__ import annotations

import os
import time
from urllib.parse import urljoin

from fastapi import APIRouter, Cookie, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .magic import (
    SESSION_COOKIE,
    SESSION_TTL,
    bind_login,
    create_magic_token,
    create_session_cookie,
    current_user,
    verify_magic_token,
)
from .users import is_valid_email


user_router = APIRouter()

# Shared template loader — matches the path order main.py uses.
_templates = Jinja2Templates(directory=[
    "shared/templates",
    "phronesis/templates",
    "synthesis/templates",
    "homepage",
])


# Per-email throttle: email → last send timestamp.
_LAST_SEND: dict[str, float] = {}
_MIN_INTERVAL = 30  # seconds between link requests for the same email


def _site_url(request: Request) -> str:
    return (os.environ.get("SITE_URL") or str(request.base_url)).rstrip("/")


@user_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # Already signed in? Go straight to /account.
    if current_user(request):
        return RedirectResponse(url="/account", status_code=302)
    return _templates.TemplateResponse(
        request, "auth/login.html", {"sent": False, "email": ""},
    )


@user_router.post("/auth/request-link", response_class=HTMLResponse)
async def request_link(request: Request, email: str = Form(...)):
    email = email.strip().lower()[:200]
    if not is_valid_email(email):
        return _templates.TemplateResponse(
            request, "auth/login.html",
            {"sent": False, "email": email, "error": "That doesn't look like a valid email."},
        )

    # Per-email throttle
    now = time.time()
    last = _LAST_SEND.get(email, 0)
    if now - last < _MIN_INTERVAL:
        wait = int(_MIN_INTERVAL - (now - last)) + 1
        return _templates.TemplateResponse(
            request, "auth/login.html",
            {"sent": False, "email": email,
             "error": f"A magic link was just sent. Try again in {wait} seconds."},
        )
    _LAST_SEND[email] = now

    # Send the magic link (or pretend-send in dev mode)
    from shared.email import magic_link as _send_magic

    token = create_magic_token(email)
    site = _site_url(request)
    link = f"{site}/auth/verify?token={token}"

    try:
        _send_magic(email, link)
    except Exception as e:
        print(f"[auth] magic-link send failed: {e}")

    from shared.analytics import log_event
    log_event("auth_link_requested", {"email_hash": hash(email) % (10**10)})

    return _templates.TemplateResponse(
        request, "auth/login.html",
        {"sent": True, "email": email},
    )


@user_router.get("/auth/verify", response_class=HTMLResponse)
async def verify(request: Request, token: str = ""):
    email = verify_magic_token(token)
    if not email:
        return _templates.TemplateResponse(
            request, "auth/login.html",
            {"sent": False, "email": "",
             "error": "That link is invalid or expired. Request a fresh one."},
            status_code=400,
        )

    # First-ever login sends the welcome email on top of the session set.
    from .users import get_user as _get
    was_new = _get(email) is None
    user = bind_login(email)

    if was_new:
        try:
            from shared.email import welcome as _welcome
            _welcome(email, plan=user.get("plan", "free"))
        except Exception as e:
            print(f"[auth] welcome email failed: {e}")

    from shared.analytics import log_event
    log_event("auth_verified", {"email_hash": hash(email) % (10**10), "new": was_new})

    resp = RedirectResponse(url="/account", status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        create_session_cookie(email),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("SECURE_COOKIES", "").lower() == "true",
        path="/",
    )
    return resp


@user_router.post("/auth/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@user_router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    # Load recent runs for this user (only runs attached to their email).
    email = user["email"]
    from shared.tracking.history import get_recent_decisions
    from shared.tracking.synthesis_history import get_recent_synthesis_runs

    phronesis_recent = [d for d in get_recent_decisions(200) if d.get("user_email") == email][:10]
    try:
        synthesis_recent = [r for r in get_recent_synthesis_runs(200) if r.get("user_email") == email][:10]
    except Exception:
        synthesis_recent = []

    from shared.tracking.purchases import credits_balance as _balance
    credits_purchased = _balance(email)

    return _templates.TemplateResponse(
        request, "auth/account.html",
        {
            "user": user,
            "phronesis_recent": phronesis_recent,
            "synthesis_recent": synthesis_recent,
            "credits_purchased": credits_purchased,
        },
    )
