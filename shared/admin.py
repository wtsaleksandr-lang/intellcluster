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


_INSECURE_SECRET_MARKERS = ("change-me", "change-this", "default", "secret-key", "admin123")


def _is_insecure_secret(value: str) -> bool:
    if not value:
        return True
    if len(value) < 24:
        return True
    lo = value.lower()
    return any(m in lo for m in _INSECURE_SECRET_MARKERS)


def _get_admin_creds() -> tuple[str, str, str]:
    """Load admin credentials from env. Returns (username, password, secret_key).

    Refuses to boot if ADMIN_SECRET_KEY is missing or contains a default
    placeholder, since the HMAC token is the only thing standing between
    a request and admin access. The previous fallback ("change-me-in-production")
    let anyone forge an admin cookie on a misconfigured deploy.
    """
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "")
    secret = os.environ.get("ADMIN_SECRET_KEY", "")
    if _is_insecure_secret(secret):
        raise RuntimeError(
            "ADMIN_SECRET_KEY is missing or insecure. Set a strong value (>=24 chars, no 'change-me' placeholder) in your .env."
        )
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


WAITLIST_HTML = """{% extends "base.html" %}
{% block title %}Admin — Waitlist{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:880px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Waitlist</h1>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
      <a href="/admin/waitlist.csv" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--accent-dim);border:1px solid var(--accent-border);color:var(--accent);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">EXPORT CSV</a>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:28px;">
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">TOTAL</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.total }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">LAST 24H</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.last_24h }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">UNIQUE</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.unique }}</div></div>
  </div>

  <div class="fig-label">FIG <span>1</span> — SIGNUPS BY PLAN</div>
  <div class="panel" style="padding:14px 18px;margin-bottom:24px;">
    {% if stats.by_plan %}
      {% for plan, count in stats.by_plan.items() %}
      <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;">
        <span style="color:var(--text);">{{ plan }}</span>
        <span class="t-mono" style="color:var(--text-muted);">{{ count }}</span>
      </div>
      {% endfor %}
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No signups yet.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>2</span> — RECENT SIGNUPS</div>
  {% if rows %}
    <div class="panel" style="padding:0;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="background:var(--surface2);">
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">TIMESTAMP</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">PLAN</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">EMAIL</th>
          </tr>
        </thead>
        <tbody>
          {% for r in rows %}
          <tr style="border-top:1px solid var(--border-subtle);">
            <td class="t-mono" style="padding:10px 14px;color:var(--text-dim);font-size:11px;white-space:nowrap;">{{ r.timestamp[:19] }}</td>
            <td style="padding:10px 14px;"><span class="bdg bdg-accent">{{ r.plan }}</span></td>
            <td style="padding:10px 14px;color:var(--text);">{{ r.email }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% else %}
    <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No signups yet.</div>
  {% endif %}
</div>
{% endblock %}"""


ANALYTICS_HTML = """{% extends "base.html" %}
{% block title %}Admin — Analytics{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:880px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Analytics</h1>
    </div>
    <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
  </div>

  <div class="fig-label">FIG <span>1</span> — LAST 24 HOURS</div>
  <div class="panel" style="padding:16px 20px;margin-bottom:24px;">
    {% if counts_24h %}
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;">
        {% for event, count in counts_24h.items() %}
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;">
          <span class="t-mono" style="font-size:11px;color:var(--text-muted);">{{ event }}</span>
          <span class="t-display" style="font-size:18px;font-weight:600;color:var(--text);">{{ count }}</span>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No events logged in the last 24 hours.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>2</span> — ALL-TIME TOTALS</div>
  <div class="panel" style="padding:16px 20px;margin-bottom:24px;">
    {% if counts_all %}
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;">
        {% for event, count in counts_all.items() %}
        <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;">
          <span class="t-mono" style="font-size:11px;color:var(--text-muted);">{{ event }}</span>
          <span class="t-display" style="font-size:18px;font-weight:600;color:var(--text);">{{ count }}</span>
        </div>
        {% endfor %}
      </div>
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No events logged.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>3</span> — RECENT EVENTS</div>
  <div class="panel" style="padding:0;overflow:hidden;">
    {% if recent %}
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="background:var(--surface2);">
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">WHEN</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">EVENT</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">PROPS</th>
          </tr>
        </thead>
        <tbody>
          {% for e in recent %}
          <tr style="border-top:1px solid var(--border-subtle);">
            <td class="t-mono" style="padding:8px 14px;color:var(--text-dim);font-size:10px;white-space:nowrap;">{{ e.timestamp[:19] }}</td>
            <td style="padding:8px 14px;"><span class="t-mono" style="color:var(--accent);font-size:11px;">{{ e.event }}</span></td>
            <td style="padding:8px 14px;color:var(--text-muted);font-size:11px;">{{ e.props_str }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <div style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No events yet.</div>
    {% endif %}
  </div>
</div>
{% endblock %}"""


USERS_HTML = """{% extends "base.html" %}
{% block title %}Admin — Users{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:960px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Users</h1>
    </div>
    <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:24px;">
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">TOTAL</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.total }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">NEW &lt;7D</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.last_7d }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">PAID</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.paid }}</div></div>
  </div>

  <div class="fig-label">FIG <span>1</span> — BY PLAN</div>
  <div class="panel" style="padding:14px 18px;margin-bottom:24px;">
    {% if stats.by_plan %}
      {% for plan, count in stats.by_plan.items() %}
      <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;">
        <span style="color:var(--text);text-transform:capitalize;">{{ plan }}</span>
        <span class="t-mono" style="color:var(--text-muted);">{{ count }}</span>
      </div>
      {% endfor %}
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No users yet.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>2</span> — RECENT USERS</div>
  {% if rows %}
    <div class="panel" style="padding:0;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="background:var(--surface2);">
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">EMAIL</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">PLAN</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">SIGNED UP</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">LAST LOGIN</th>
          </tr>
        </thead>
        <tbody>
          {% for u in rows %}
          <tr style="border-top:1px solid var(--border-subtle);">
            <td style="padding:10px 14px;color:var(--text);">{{ u.email }}</td>
            <td style="padding:10px 14px;"><span class="bdg bdg-accent" style="text-transform:capitalize;">{{ u.plan or 'free' }}</span></td>
            <td class="t-mono" style="padding:10px 14px;color:var(--text-dim);font-size:11px;white-space:nowrap;">{{ (u.created_at or '')[:10] }}</td>
            <td class="t-mono" style="padding:10px 14px;color:var(--text-dim);font-size:11px;white-space:nowrap;">{{ (u.last_login or '')[:16] }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% else %}
    <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No users yet.</div>
  {% endif %}
</div>
{% endblock %}"""


CONTACT_HTML = """{% extends "base.html" %}
{% block title %}Admin — Contact{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:960px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Contact submissions</h1>
    </div>
    <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:24px;">
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">TOTAL</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.total }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">LAST 7D</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.last_7d }}</div></div>
  </div>

  <div class="fig-label">FIG <span>1</span> — BY REASON</div>
  <div class="panel" style="padding:14px 18px;margin-bottom:24px;">
    {% if stats.by_reason %}
      {% for reason, count in stats.by_reason.items() %}
      <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;">
        <span style="color:var(--text);text-transform:capitalize;">{{ reason }}</span>
        <span class="t-mono" style="color:var(--text-muted);">{{ count }}</span>
      </div>
      {% endfor %}
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No submissions yet.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>2</span> — RECENT SUBMISSIONS</div>
  {% if rows %}
    <div style="display:flex;flex-direction:column;gap:10px;">
      {% for r in rows %}
      <div class="panel" style="padding:14px 18px;">
        <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
          <span class="bdg bdg-accent" style="text-transform:capitalize;">{{ r.reason }}</span>
          <span style="color:var(--text);font-weight:600;font-size:13px;">{{ r.name }}</span>
          <a href="mailto:{{ r.email }}" style="color:var(--accent);font-size:12px;text-decoration:none;">{{ r.email }}</a>
          <span class="t-mono" style="margin-left:auto;font-size:10px;color:var(--text-dim);">{{ r.timestamp[:19] }}</span>
        </div>
        <div style="color:var(--text-muted);font-size:13px;line-height:1.6;white-space:pre-wrap;">{{ r.message }}</div>
      </div>
      {% endfor %}
    </div>
  {% else %}
    <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No submissions yet.</div>
  {% endif %}
</div>
{% endblock %}"""


PURCHASES_HTML = """{% extends "base.html" %}
{% block title %}Admin — Purchases{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:960px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Purchases</h1>
    </div>
    <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:24px;">
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">TOTAL REVENUE</div><div class="t-display" style="font-size:26px;font-weight:600;">${{ '%.2f' | format(stats.revenue_usd) }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">PURCHASES</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.total }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">SUBS</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.subscriptions }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">PACKS</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.packs }}</div></div>
  </div>

  <div class="fig-label">FIG <span>1</span> — RECENT PURCHASES</div>
  {% if rows %}
    <div class="panel" style="padding:0;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="background:var(--surface2);">
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">WHEN</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">EMAIL</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">KIND</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">PLAN / PACK</th>
            <th style="text-align:right;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">AMOUNT</th>
          </tr>
        </thead>
        <tbody>
          {% for p in rows %}
          <tr style="border-top:1px solid var(--border-subtle);">
            <td class="t-mono" style="padding:10px 14px;color:var(--text-dim);font-size:11px;white-space:nowrap;">{{ (p.timestamp or '')[:19] }}</td>
            <td style="padding:10px 14px;color:var(--text);">{{ p.email or '—' }}</td>
            <td style="padding:10px 14px;"><span class="bdg {% if p.kind == 'subscription' %}bdg-accent{% else %}bdg-muted{% endif %}" style="text-transform:capitalize;">{{ p.kind }}</span></td>
            <td style="padding:10px 14px;color:var(--text);text-transform:capitalize;">{{ p.plan_id or p.pack_id or '—' }}{% if p.credits %} ({{ p.credits }} cr){% endif %}</td>
            <td class="t-mono" style="padding:10px 14px;text-align:right;color:var(--text);">${{ '%.2f' | format((p.amount or 0)/100) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% else %}
    <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No purchases yet.</div>
  {% endif %}
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

  <!-- Quick links -->
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px;">
    <a href="/admin/users" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">USERS →</a>
    <a href="/admin/advisory" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--accent-dim);border:1px solid var(--accent-border);color:var(--accent);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">ADVISORY →</a>
    <a href="/admin/contact" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">CONTACT →</a>
    <a href="/admin/purchases" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">PURCHASES →</a>
    <a href="/admin/waitlist" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">WAITLIST →</a>
    <a href="/admin/analytics" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">ANALYTICS →</a>
  </div>

  <!-- Stats overview -->
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:32px;">
    <div class="panel">
      <div class="fig-label" style="margin-bottom:4px;">USERS</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">{{ stats.user_count }}</div>
      <div style="font-size:11px;color:var(--text-muted);">signed in, all time</div>
    </div>
    <div class="panel">
      <div class="fig-label" style="margin-bottom:4px;">REVENUE</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">${{ '%.2f' | format(stats.revenue_usd) }}</div>
      <div style="font-size:11px;color:var(--text-muted);">{{ stats.purchase_count }} purchase{{ '' if stats.purchase_count == 1 else 's' }}</div>
    </div>
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
      <div class="fig-label" style="margin-bottom:4px;">CONTACT</div>
      <div class="t-display" style="font-size:28px;font-weight:600;">{{ stats.contact_count }}</div>
      <div style="font-size:11px;color:var(--text-muted);">submissions</div>
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
ADVISORY_HTML = """{% extends "base.html" %}
{% block title %}Admin — Advisory{% endblock %}
{% block robots %}noindex, nofollow{% endblock %}
{% block content %}
<div style="max-width:960px;margin:0 auto;padding:40px 20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;gap:12px;flex-wrap:wrap;">
    <div>
      <div class="fig-label" style="margin-bottom:4px;">INTELLCLUSTER <span>·</span> ADMIN</div>
      <h1 class="t-display" style="font-size:26px;font-weight:600;">Advisory sessions</h1>
    </div>
    <a href="/admin" class="t-mono" style="font-size:10px;padding:8px 14px;background:var(--surface);border:1px solid var(--border);color:var(--text-muted);border-radius:6px;text-decoration:none;letter-spacing:0.3px;">← DASHBOARD</a>
  </div>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:24px;">
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">TOTAL</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.total }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">COMPLETED</div><div class="t-display" style="font-size:26px;font-weight:600;">{{ stats.completed }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">ERRORED</div><div class="t-display" style="font-size:26px;font-weight:600;color:{% if stats.errored %}var(--red){% else %}var(--text-primary){% endif %};">{{ stats.errored }}</div></div>
    <div class="panel"><div class="fig-label" style="margin-bottom:4px;">COST</div><div class="t-display" style="font-size:26px;font-weight:600;">${{ '%.2f' | format(stats.total_cost_usd) }}</div></div>
  </div>

  <div class="fig-label">FIG <span>1</span> — BY CATEGORY</div>
  <div class="panel" style="padding:14px 18px;margin-bottom:24px;">
    {% if stats.by_category %}
      {% for cat, count in stats.by_category.items() %}
      <div style="display:flex;justify-content:space-between;padding:4px 0;font-size:13px;">
        <span style="color:var(--text);text-transform:capitalize;">{{ cat }}</span>
        <span class="t-mono" style="color:var(--text-muted);">{{ count }}</span>
      </div>
      {% endfor %}
    {% else %}
      <div style="color:var(--text-dim);font-size:13px;">No sessions yet.</div>
    {% endif %}
  </div>

  <div class="fig-label">FIG <span>2</span> — RECENT SESSIONS</div>
  {% if sessions %}
    <div class="panel" style="padding:0;overflow:hidden;">
      <table style="width:100%;border-collapse:collapse;font-size:12px;">
        <thead>
          <tr style="background:var(--surface2);">
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">CREATED</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">USER</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">CATEGORY</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">QUESTION</th>
            <th style="text-align:left;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">STAGE</th>
            <th style="text-align:right;padding:10px 14px;font-weight:500;color:var(--text-dim);font-size:10px;letter-spacing:1px;">COST</th>
          </tr>
        </thead>
        <tbody>
          {% for s in sessions %}
          <tr style="border-top:1px solid var(--border-subtle);">
            <td class="t-mono" style="padding:10px 14px;color:var(--text-dim);font-size:11px;white-space:nowrap;">{{ (s.created_at or '')[:19] }}</td>
            <td style="padding:10px 14px;color:var(--text);">{{ s.user_email or '—' }}</td>
            <td style="padding:10px 14px;"><span class="bdg bdg-accent" style="text-transform:capitalize;">{{ s.category or 'exploratory' }}</span></td>
            <td style="padding:10px 14px;color:var(--text);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
              {% if s.report %}
                <a href="/advisory/result/{{ s.run_id }}" style="color:var(--accent);text-decoration:none;">{{ (s.intake.advisory_question if s.intake else s.raw_input)[:60] }}</a>
              {% else %}
                {{ (s.intake.advisory_question if s.intake else s.raw_input)[:60] }}
              {% endif %}
            </td>
            <td style="padding:10px 14px;">
              <span class="bdg {% if s.stage == 'done' %}bdg-green{% elif s.stage == 'error' %}bdg-red{% else %}bdg-muted{% endif %}">{{ s.stage }}</span>
            </td>
            <td class="t-mono" style="padding:10px 14px;text-align:right;color:var(--text-muted);">${{ '%.4f' | format(s.total_cost_usd or 0) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% else %}
    <div class="panel" style="padding:18px;color:var(--text-dim);font-size:13px;text-align:center;">No advisory sessions yet.</div>
  {% endif %}
</div>
{% endblock %}"""


_admin_templates.env.loader = ChoiceLoader([
    DictLoader({
        "_admin_login.html": LOGIN_HTML,
        "_admin_dashboard.html": DASHBOARD_HTML,
        "_admin_waitlist.html": WAITLIST_HTML,
        "_admin_analytics.html": ANALYTICS_HTML,
        "_admin_users.html": USERS_HTML,
        "_admin_contact.html": CONTACT_HTML,
        "_admin_purchases.html": PURCHASES_HTML,
        "_admin_advisory.html": ADVISORY_HTML,
    }),
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
    from shared.tracking.contact import list_recent as _list_contact
    from shared.tracking.purchases import list_recent as _list_purchases
    from shared.auth.users import list_users, user_count
    from config import settings as app_settings

    recent_phronesis = get_recent_decisions(limit=10)
    recent_synthesis = get_recent_synthesis_runs(limit=10)
    providers = app_settings.available_judges()

    purchases = _list_purchases(limit=500)
    revenue_cents = sum(int(p.get("amount") or 0) for p in purchases)

    stats = {
        "phronesis_count": len(get_recent_decisions(limit=2000)),
        "synthesis_count": len(get_recent_synthesis_runs(limit=2000)),
        "provider_count": len(providers),
        "providers": providers,
        "user_count": user_count(),
        "contact_count": len(_list_contact(limit=2000)),
        "purchase_count": len(purchases),
        "revenue_usd": revenue_cents / 100.0,
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
        # secure flag follows SECURE_COOKIES env (default True so admin sessions
        # never travel over HTTP — set explicitly to "false" only for local dev).
        secure_flag = os.environ.get("SECURE_COOKIES", "true").lower() != "false"
        resp.set_cookie(
            ADMIN_COOKIE, token,
            httponly=True, samesite="lax",
            max_age=TOKEN_TTL_SECONDS,
            secure=secure_flag,
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


# ─── Waitlist viewer ───

def _load_waitlist() -> list[dict]:
    import json
    from pathlib import Path as _Path
    path = _Path("history") / "waitlist.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


@admin_router.get("/admin/waitlist", response_class=HTMLResponse)
async def admin_waitlist(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    from datetime import datetime, timedelta, timezone

    rows = _load_waitlist()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    last_24h = 0
    by_plan: dict[str, int] = {}
    emails: set[str] = set()
    for r in rows:
        try:
            ts = datetime.fromisoformat(r.get("timestamp", ""))
            if ts >= cutoff:
                last_24h += 1
        except Exception:
            pass
        plan = r.get("plan") or "unknown"
        by_plan[plan] = by_plan.get(plan, 0) + 1
        em = (r.get("email") or "").strip().lower()
        if em:
            emails.add(em)

    stats = {
        "total": len(rows),
        "last_24h": last_24h,
        "unique": len(emails),
        "by_plan": dict(sorted(by_plan.items(), key=lambda x: -x[1])),
    }

    return _admin_templates.TemplateResponse(
        "_admin_waitlist.html",
        {"request": request, "rows": list(reversed(rows))[:200], "stats": stats},
    )


@admin_router.get("/admin/waitlist.csv")
async def admin_waitlist_csv(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    import csv
    import io
    from fastapi.responses import Response

    rows = _load_waitlist()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "plan", "email"])
    for r in reversed(rows):
        writer.writerow([r.get("timestamp", ""), r.get("plan", ""), r.get("email", "")])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="waitlist.csv"'},
    )


# ─── Analytics viewer ───

@admin_router.get("/admin/analytics", response_class=HTMLResponse)
async def admin_analytics(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    import json as _json
    from shared.analytics import recent_events, summary_last_24h

    all_events = recent_events(limit=5000)
    counts_all: dict[str, int] = {}
    for e in all_events:
        evt = e.get("event", "unknown")
        counts_all[evt] = counts_all.get(evt, 0) + 1

    # Sort by count desc
    counts_all_sorted = dict(sorted(counts_all.items(), key=lambda x: -x[1]))
    counts_24h = dict(sorted(summary_last_24h().items(), key=lambda x: -x[1]))

    # Build a clean display of recent events
    recent = []
    for e in all_events[:100]:
        props = {k: v for k, v in e.items() if k not in ("timestamp", "event")}
        try:
            props_str = _json.dumps(props)[:140]
        except Exception:
            props_str = str(props)[:140]
        recent.append({
            "timestamp": e.get("timestamp", ""),
            "event": e.get("event", ""),
            "props_str": props_str,
        })

    return _admin_templates.TemplateResponse(
        "_admin_analytics.html",
        {
            "request": request,
            "counts_24h": counts_24h,
            "counts_all": counts_all_sorted,
            "recent": recent,
        },
    )


# ─── Users, Contact, Purchases ───

def _days_ago(iso_ts: str, days: int) -> bool:
    """True if iso_ts is within the last `days` days."""
    from datetime import datetime as _dt, timezone as _tz
    if not iso_ts:
        return False
    try:
        dt = _dt.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return False
    age = (_dt.now(_tz.utc) - dt).total_seconds() / 86400.0
    return age <= days


@admin_router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    from shared.auth.users import list_users

    rows = list_users(limit=200)
    by_plan: dict[str, int] = {}
    last_7d = 0
    paid = 0
    for u in rows:
        plan = u.get("plan", "free")
        by_plan[plan] = by_plan.get(plan, 0) + 1
        if _days_ago(u.get("created_at", ""), 7):
            last_7d += 1
        if plan and plan != "free":
            paid += 1
    stats = {
        "total": len(rows),
        "by_plan": dict(sorted(by_plan.items(), key=lambda kv: -kv[1])),
        "last_7d": last_7d,
        "paid": paid,
    }
    return _admin_templates.TemplateResponse(
        "_admin_users.html",
        {"request": request, "rows": rows, "stats": stats},
    )


@admin_router.get("/admin/contact", response_class=HTMLResponse)
async def admin_contact(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    from shared.tracking.contact import list_recent
    rows = list_recent(limit=200)
    by_reason: dict[str, int] = {}
    last_7d = 0
    for r in rows:
        rs = r.get("reason", "other")
        by_reason[rs] = by_reason.get(rs, 0) + 1
        if _days_ago(r.get("timestamp", ""), 7):
            last_7d += 1
    stats = {
        "total": len(rows),
        "by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "last_7d": last_7d,
    }
    return _admin_templates.TemplateResponse(
        "_admin_contact.html",
        {"request": request, "rows": rows, "stats": stats},
    )


@admin_router.get("/admin/advisory", response_class=HTMLResponse)
async def admin_advisory(request: Request):
    """Recent Phronesis OS advisory sessions."""
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    from phronesis.advisory.session import list_recent
    sessions = list_recent(limit=100)
    completed = sum(1 for s in sessions if s.stage == "done")
    errored = sum(1 for s in sessions if s.stage == "error")
    total_cost = sum(s.total_cost_usd or 0 for s in sessions)
    by_cat: dict[str, int] = {}
    for s in sessions:
        c = s.category or "exploratory"
        by_cat[c] = by_cat.get(c, 0) + 1
    stats = {
        "total": len(sessions),
        "completed": completed,
        "errored": errored,
        "total_cost_usd": total_cost,
        "by_category": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
    }
    return _admin_templates.TemplateResponse(
        "_admin_advisory.html",
        {"request": request, "sessions": sessions, "stats": stats},
    )


@admin_router.get("/admin/purchases", response_class=HTMLResponse)
async def admin_purchases(request: Request):
    if not is_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    from shared.tracking.purchases import list_recent
    rows = list_recent(limit=200)
    subs = sum(1 for r in rows if r.get("kind") == "subscription")
    packs = sum(1 for r in rows if r.get("kind") == "credit_pack")
    revenue_cents = sum(int(r.get("amount") or 0) for r in rows)
    stats = {
        "total": len(rows),
        "subscriptions": subs,
        "packs": packs,
        "revenue_usd": revenue_cents / 100.0,
    }
    return _admin_templates.TemplateResponse(
        "_admin_purchases.html",
        {"request": request, "rows": rows, "stats": stats},
    )
