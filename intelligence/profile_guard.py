from __future__ import annotations

import re
from html import escape
from urllib.parse import unquote

from fastapi import Request
from fastapi.responses import HTMLResponse

from intelligence.database import connect
from intelligence.repository import get_entity_by_slug

DEMO_PROFILE_SLUGS = {"maple-auto-supply-inc"}
_PROFILE_PATH = re.compile(r"^/data/company/([^/]+)$")


def _not_found_page(slug: str) -> str:
    query = unquote(slug).replace("-", " ").strip()
    safe_query = escape(query or "company")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Company profile not found | IntellCluster</title>
  <meta name="description" content="The requested IntellCluster company profile could not be found.">
  <style>
    body{{margin:0;font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f7f9fa;color:#18242b}}
    .nf{{max-width:720px;margin:12vh auto;padding:0 22px}}
    .nf-card{{background:#fff;border:1px solid #dce3e7;border-radius:10px;padding:34px;box-shadow:0 10px 30px rgba(15,35,45,.05)}}
    .nf-kicker{{font-size:11px;font-weight:750;letter-spacing:.08em;text-transform:uppercase;color:#64808d}}
    h1{{margin:10px 0 8px;font-size:28px;letter-spacing:-.035em}}
    p{{color:#667780;line-height:1.55}}
    .nf-actions{{display:flex;gap:9px;flex-wrap:wrap;margin-top:22px}}
    a{{display:inline-flex;text-decoration:none;border:1px solid #cbd7dd;border-radius:6px;padding:9px 12px;color:#174b60;font-size:13px;font-weight:700;background:#fff}}
    a.primary{{background:#075a70;border-color:#075a70;color:#fff}}
  </style>
</head>
<body>
  <main class="nf">
    <section class="nf-card">
      <div class="nf-kicker">404 · Company profile unavailable</div>
      <h1>No indexed profile for “{safe_query}”</h1>
      <p>The profile may not be in the current public-data index yet, or the link may be outdated. Search the directory for the company name or browse the company index.</p>
      <div class="nf-actions">
        <a class="primary" href="/data/search?q={escape(query)}">Search companies</a>
        <a href="/data/companies">Browse company directory</a>
      </div>
    </section>
  </main>
</body>
</html>"""


def install_profile_guard(app) -> None:
    if getattr(app.state, "intellcluster_profile_guard_installed", False):
        return
    app.state.intellcluster_profile_guard_installed = True

    @app.middleware("http")
    async def strict_company_profile_guard(request: Request, call_next):
        match = _PROFILE_PATH.fullmatch(request.url.path)
        if not match:
            return await call_next(request)

        slug = unquote(match.group(1))
        if slug in DEMO_PROFILE_SLUGS:
            return await call_next(request)

        with connect() as conn:
            company = get_entity_by_slug(conn, slug)
        if company is None:
            return HTMLResponse(_not_found_page(slug), status_code=404)
        return await call_next(request)
