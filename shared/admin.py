"""
Admin authentication — HMAC-signed cookie tokens, 24h expiry.
Single-admin model: one username/password from env vars.

Usage:
    from shared.admin import require_admin, admin_router
    app.include_router(admin_router)

    @app.get("/admin/something")
    async def protected(admin: bool = Depends(require_admin)):
        ...
"""

import hashlib
import hmac
import os
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request, APIRouter, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates


ADMIN_COOKIE = "intellcluster_admin"
TOKEN_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _get_admin_creds() -> tuple[str, str, str]:
    """Load admin credentials from env. Returns (username, password, secret_key)."""
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    secret = os.environ.get("ADMIN_SECRET_KEY", "change-me-in-production")
    return username, password, secret


def _sign_token(payload: str, secret: str) -> str:
    """Create HMAC-signed token: base = payload, signature = HMAC-SHA256(payload, secret)."""
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_token(token: str, secret: str) -> bool:
    """Verify HMAC signature on token. Returns True if valid and not expired."""
    if not token or "." not in token:
        return False
    try:
        payload, sig = token.rsplit(".", 1)
        expected_sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return False
        # Payload format: "username|timestamp"
        parts = payload.split("|")
        if len(parts) != 2:
            return False
        ts = int(parts[1])
        if time.time() - ts > TOKEN_TTL_SECONDS:
            return False
        return True
    except (ValueError, TypeError):
        return False


def create_admin_token(username: str) -> str:
    """Create a fresh signed admin token."""
    _, _, secret = _get_admin_creds()
    payload = f"{username}|{int(time.time())}"
    return _sign_token(payload, secret)


def is_admin(request: Request) -> bool:
    """Check if the request has a valid admin cookie. Non-raising."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        return False
    _, _, secret = _get_admin_creds()
    return _verify_token(token, secret)


def require_admin(request: Request):
    """FastAPI dependency that raises 401 if not admin."""
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin access required")
    return True


def admin_configured() -> bool:
    """Check if admin credentials are actually set (not empty password)."""
    _, password, _ = _get_admin_creds()
    return bool(password and len(password) >= 4)


# ─── Router with login/logout ───

admin_router = APIRouter()


LOGIN_HTML = """{% extends "base.html" %}
{% block title %}Admin Login{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:400px;margin:80px auto;padding:0 20px;">
  <div class="fig-label" style="text-align:center;">INTELLCLUSTER <span>·</span> ADMIN</div>
  <h1 class="t-display" style="font-size:26px;font-weight:600;text-align:center;margin-bottom:32px;">Admin Access</h1>

  {% if error %}
  <div style="padding:12px;background:rgba(248,81,73,0.08);border:1px solid rgba(248,81,73,0.15);border-radius:8px;color:var(--red);font-size:13px;margin-bottom:16px;">
    {{ error }}
  </div>
  {% endif %}

  <form method="post" action="/admin/login" class="panel" style="padding:24px;">
    <div style="margin-bottom:14px;">
      <label class="fig-label" style="margin-bottom:6px;">USERNAME</label>
      <input type="text" name="username" required autocomplete="username"
             style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px;font-family:inherit;">
    </div>
    <div style="margin-bottom:18px;">
      <label class="fig-label" style="margin-bottom:6px;">PASSWORD</label>
      <input type="password" name="password" required autocomplete="current-password"
             style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px;font-family:inherit;">
    </div>
    <button type="submit" style="width:100%;padding:10px;background:var(--accent);color:#fff;font-weight:600;border:none;border-radius:8px;font-size:13px;cursor:pointer;">Sign in</button>
  </form>
</div>
{% endblock %}"""


DASHBOARD_HTML = """{% extends "base.html" %}
{% block title %}Admin Dashboard{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:880px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:32px;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:28px;font-weight:600;">Dashboard</h1>
    </div>
    <form method="post" action="/admin/logout">
      <button type="submit" class="t-mono" style="font-size:10px;padding:8px 16px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;cursor:pointer;letter-spacing:0.3px;">SIGN OUT</button>
    </form>
  </div>

  <!-- Stats overview -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:32px;">
    <div class="panel">
      <div class="fig-label" style="margin-bottom:4px;">PHRONESIS</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">{{ stats.phronesis_count }}</div>
      <div style="font-size:11px;color:var(--text-muted);">decisions completed</div>
    </div>
    <div class="panel">
      <div class="fig-label" style="margin-bottom:4px;">SYNTHESIS</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">{{ stats.synthesis_count }}</div>
      <div style="font-size:11px;color:var(--text-muted);">research runs</div>
    </div>
    <div class="panel">
      <div class="fig-label" style="margin-bottom:4px;">PROVIDERS</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">{{ stats.provider_count }}</div>
      <div style="font-size:11px;color:var(--text-muted);">LLMs configured</div>
    </div>
  </div>

  <!-- Recent Phronesis -->
  <div style="margin-bottom:32px;">
    <div class="fig-label">FIG <span>1</span> — RECENT PHRONESIS DECISIONS</div>
    {% if recent_phronesis %}
      {% for d in recent_phronesis[:10] %}
      <a href="/phronesis/result/{{ d.run_id }}" style="display:block;text-decoration:none;color:inherit;">
        <div class="panel" style="padding:12px 16px;margin-bottom:4px;transition:border-color 0.15s;" onmouseover="this.style.borderColor='var(--accent-border)'" onmouseout="this.style.borderColor='var(--border)'">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
            <div style="min-width:0;flex:1;">
              <div style="font-size:13px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ d.question }}</div>
              <div class="t-mono" style="font-size:10px;color:var(--text-dim);margin-top:2px;">{{ d.run_id }} &middot; {{ d.winner }}</div>
            </div>
            <span class="t-mono" style="font-size:10px;color:var(--text-dim);flex-shrink:0;">{{ d.confidence or 'N/A' }}</span>
          </div>
        </div>
      </a>
      {% endfor %}
    {% else %}
      <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No decisions yet.</div>
    {% endif %}
  </div>

  <!-- Recent Synthesis -->
  <div style="margin-bottom:32px;">
    <div class="fig-label">FIG <span>2</span> — RECENT SYNTHESIS RUNS</div>
    {% if recent_synthesis %}
      {% for r in recent_synthesis[:10] %}
      <a href="/synthesis/result/{{ r.run_id }}" style="display:block;text-decoration:none;color:inherit;">
        <div class="panel" style="padding:12px 16px;margin-bottom:4px;transition:border-color 0.15s;" onmouseover="this.style.borderColor='var(--accent-border)'" onmouseout="this.style.borderColor='var(--border)'">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
            <div style="min-width:0;flex:1;">
              <div style="font-size:13px;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ r.prompt[:120] }}</div>
              <div class="t-mono" style="font-size:10px;color:var(--text-dim);margin-top:2px;">{{ r.run_id }} &middot; {{ r.mode }}</div>
            </div>
          </div>
        </div>
      </a>
      {% endfor %}
    {% else %}
      <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No research runs yet.</div>
    {% endif %}
  </div>

  <!-- Health -->
  <div>
    <div class="fig-label">FIG <span>3</span> — HEALTH</div>
    <div class="panel" style="padding:18px;">
      <div style="display:flex;flex-wrap:wrap;gap:14px;font-size:12px;">
        {% for provider in stats.providers %}
        <span class="bdg bdg-accent">{{ provider }}</span>
        {% endfor %}
      </div>
    </div>
  </div>
</div>
{% endblock %}"""


# Dynamic template registration (so shared/templates/base.html works)
from fastapi.templating import Jinja2Templates as _JT
_admin_templates = _JT(directory=["shared/templates"])
# Register inline templates
from jinja2 import DictLoader, ChoiceLoader, FileSystemLoader
_admin_templates.env.loader = ChoiceLoader([
    DictLoader({"_admin_login.html": LOGIN_HTML, "_admin_dashboard.html": DASHBOARD_HTML}),
    FileSystemLoader("shared/templates"),
])


@admin_router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request):
    """Admin dashboard (if logged in) or redirect to login."""
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    # Gather stats
    from shared.tracking.history import get_recent_decisions
    from shared.tracking.synthesis_history import get_recent_synthesis_runs
    from config import settings as app_settings

    recent_phronesis = get_recent_decisions(limit=10)
    recent_synthesis = get_recent_synthesis_runs(limit=10)
    providers = app_settings.available_judges()

    stats = {
        "phronesis_count": len(recent_phronesis),  # approximate; better to count all
        "synthesis_count": len(recent_synthesis),
        "provider_count": len(providers),
        "providers": providers,
    }

    return _admin_templates.TemplateResponse(
        "_admin_dashboard.html",
        {"request": request, "stats": stats, "recent_phronesis": recent_phronesis, "recent_synthesis": recent_synthesis},
    )


@admin_router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request, error: str | None = None):
    if is_admin(request):
        return RedirectResponse(url="/admin", status_code=302)
    return _admin_templates.TemplateResponse("_admin_login.html", {"request": request, "error": error})


@admin_router.post("/admin/login")
async def admin_login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    expected_user, expected_pass, _ = _get_admin_creds()

    if not expected_pass:
        return _admin_templates.TemplateResponse(
            "_admin_login.html",
            {"request": request, "error": "Admin not configured. Set ADMIN_PASSWORD in environment."},
            status_code=503,
        )

    if username == expected_user and hmac.compare_digest(password, expected_pass):
        token = create_admin_token(username)
        resp = RedirectResponse(url="/admin", status_code=302)
        resp.set_cookie(
            ADMIN_COOKIE, token,
            httponly=True, samesite="lax",
            max_age=TOKEN_TTL_SECONDS,
            secure=False,  # set True in production with HTTPS
        )
        return resp

    return _admin_templates.TemplateResponse(
        "_admin_login.html",
        {"request": request, "error": "Invalid credentials."},
        status_code=401,
    )


@admin_router.post("/admin/logout")
async def admin_logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie(ADMIN_COOKIE)
    return resp
