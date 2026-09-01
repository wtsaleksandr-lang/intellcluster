from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import Response

from intelligence.database import connect
from intelligence.evidence_sitemap import company_is_indexable

_COMPANY_PATH = re.compile(r"^/data/company/([^/]+)/?$")
_ROBOTS_META = re.compile(
    r'<meta\s+name=["\']robots["\']\s+content=["\'][^"\']*["\']\s*/?>',
    flags=re.IGNORECASE,
)


def install_thin_profile_seo(app) -> None:
    """Keep thin registry profiles accessible without asking Google to index them.

    Company sitemaps already use an evidence threshold. Applying the same rule to
    the page itself prevents registry-only profiles reached through internal links
    from creating a large low-value index footprint.
    """
    if getattr(app.state, "intellcluster_thin_profile_seo_installed", False):
        return
    app.state.intellcluster_thin_profile_seo_installed = True

    @app.middleware("http")
    async def thin_profile_robots(request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or response.status_code != 200:
            return response

        match = _COMPANY_PATH.fullmatch(request.url.path)
        if not match:
            return response
        if "text/html" not in response.headers.get("content-type", ""):
            return response

        slug = match.group(1)
        try:
            with connect() as conn:
                indexable = company_is_indexable(conn, slug)
        except Exception:
            # Do not accidentally de-index good pages because an auxiliary SEO
            # query failed. The base SEO middleware remains the fallback.
            return response
        if indexable:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        replacement = '<meta name="robots" content="noindex,follow">'
        if _ROBOTS_META.search(text):
            text = _ROBOTS_META.sub(replacement, text, count=1)
        elif "</head>" in text:
            text = text.replace("</head>", replacement + "\n</head>", 1)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers["X-Robots-Tag"] = "noindex, follow"
        return Response(
            text,
            status_code=response.status_code,
            headers=headers,
            media_type="text/html",
        )
