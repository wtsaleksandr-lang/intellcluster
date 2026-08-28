from __future__ import annotations

import json
import math
import os
import re
from html import escape as html_escape
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import func, select

from intelligence.database import connect, entities
from intelligence.repository import get_entity_by_slug

router = APIRouter(tags=["seo"])
SITEMAP_PAGE_SIZE = 20_000


def _base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://intellcluster.com").strip().rstrip("/")


def _xml_response(body: str) -> Response:
    return Response(body, media_type="application/xml; charset=utf-8")


def _iso_date(value: object) -> str:
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""


@router.get("/robots.txt")
async def robots_txt() -> Response:
    base = _base_url()
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /data/",
            "Disallow: /api/",
            "Disallow: /admin/",
            "Disallow: /data/suggest",
            "Disallow: /data/search?",
            f"Sitemap: {base}/sitemap.xml",
            "",
        ]
    )
    return Response(body, media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml")
async def sitemap_index() -> Response:
    base = _base_url()
    with connect() as conn:
        total = int(conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0)
    pages = max(1, math.ceil(total / SITEMAP_PAGE_SIZE))
    entries = [f"<sitemap><loc>{xml_escape(base + '/sitemaps/static.xml')}</loc></sitemap>"]
    entries.extend(
        f"<sitemap><loc>{xml_escape(base + f'/sitemaps/companies-{page}.xml')}</loc></sitemap>"
        for page in range(1, pages + 1)
    )
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(entries) + "</sitemapindex>"
    return _xml_response(body)


@router.get("/sitemaps/static.xml")
async def sitemap_static() -> Response:
    base = _base_url()
    paths = ["/data", "/data/suppliers"]
    urls = "".join(f"<url><loc>{xml_escape(base + path)}</loc></url>" for path in paths)
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    return _xml_response(body)


@router.get("/sitemaps/companies-{page}.xml")
async def sitemap_companies(page: int) -> Response:
    page = max(1, page)
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    base = _base_url()
    with connect() as conn:
        rows = conn.execute(
            select(entities.c.slug, entities.c.updated_at)
            .where(entities.c.slug.is_not(None))
            .order_by(entities.c.id.asc())
            .limit(SITEMAP_PAGE_SIZE)
            .offset(offset)
        ).mappings().all()
    urls = []
    for row in rows:
        loc = xml_escape(f"{base}/data/company/{quote(str(row['slug']), safe='-')}")
        lastmod = _iso_date(row.get("updated_at"))
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(f"<url><loc>{loc}</loc>{mod}<changefreq>weekly</changefreq></url>")
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    return _xml_response(body)


def _canonical_path(path: str) -> str:
    if path.endswith("/") and path != "/":
        path = path[:-1]
    return path


def _organization_schema(company: dict, canonical: str) -> dict[str, object]:
    schema: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": company.get("name") or company.get("canonical_name") or "Company",
        "url": canonical,
    }
    address_parts = {
        "streetAddress": company.get("address"),
        "addressLocality": company.get("city"),
        "addressRegion": company.get("province") or company.get("region"),
        "postalCode": company.get("postal_code"),
        "addressCountry": company.get("country"),
    }
    if any(address_parts.values()):
        schema["address"] = {"@type": "PostalAddress", **{k: v for k, v in address_parts.items() if v}}
    website = str(company.get("website") or "").strip()
    if website:
        if not website.startswith(("http://", "https://")):
            website = "https://" + website
        schema["sameAs"] = [website]
    if company.get("corporation_number"):
        schema["identifier"] = str(company["corporation_number"])
    return schema


def install_seo_middleware(app) -> None:
    if getattr(app.state, "intellcluster_seo_installed", False):
        return
    app.state.intellcluster_seo_installed = True

    @app.middleware("http")
    async def intellcluster_seo_metadata(request: Request, call_next):
        path = request.url.path
        # The underlying product already owns these root-level routes. Intercept
        # them here so the directory's discovery endpoints are authoritative.
        if path == "/robots.txt":
            return await robots_txt()
        if path == "/sitemap.xml":
            return await sitemap_index()

        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response
        if not path.startswith("/data"):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        text = body.decode("utf-8", errors="replace")
        base = _base_url()
        canonical = base + _canonical_path(path)
        noindex = path.startswith("/data/search") or path.startswith("/data/suggest")
        robots = "noindex,follow" if noindex else "index,follow,max-image-preview:large,max-snippet:-1"
        head_bits = [
            f'<link rel="canonical" href="{html_escape(canonical, quote=True)}">',
            f'<meta name="robots" content="{robots}">',
            f'<meta property="og:url" content="{html_escape(canonical, quote=True)}">',
            '<meta property="og:type" content="website">',
        ]

        company_match = re.fullmatch(r"/data/company/([^/]+)", _canonical_path(path))
        if company_match and response.status_code == 200:
            slug = company_match.group(1)
            try:
                with connect() as conn:
                    company = get_entity_by_slug(conn, slug)
                if company:
                    schema = json.dumps(
                        _organization_schema(company, canonical),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    safe_schema = schema.replace("</", "<\\/")
                    head_bits.append(f'<script type="application/ld+json">{safe_schema}</script>')
            except Exception:
                pass

        injection = "\n".join(head_bits)
        if "</head>" in text:
            text = text.replace("</head>", injection + "\n</head>", 1)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(text, status_code=response.status_code, headers=headers, media_type="text/html")
