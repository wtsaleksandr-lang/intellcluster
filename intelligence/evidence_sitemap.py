from __future__ import annotations

import math
import os
import re
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import and_, exists, func, or_, select

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    source_records,
    supplier_relationships,
)


SITEMAP_PAGE_SIZE = 20_000
_STRONG_ENTITY_SOURCES = (
    "canadian_importers",
    "fmcsa_company_census",
)


def _base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://intellcluster.com").strip().rstrip("/")


def _iso_date(value: object) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match else ""


def _indexable_company_condition():
    strong_source = exists(
        select(source_records.c.id).where(
            and_(
                source_records.c.entity_id == entities.c.id,
                source_records.c.source.in_(_STRONG_ENTITY_SOURCES),
            )
        )
    )
    importer_evidence = exists(
        select(importer_relationships.c.id).where(
            importer_relationships.c.entity_id == entities.c.id
        )
    )
    supplier_evidence = exists(
        select(supplier_relationships.c.id).where(
            supplier_relationships.c.importer_entity_id == entities.c.id
        )
    )
    return and_(
        entities.c.slug.is_not(None),
        or_(
            entities.c.is_importer.is_(True),
            entities.c.website.is_not(None),
            strong_source,
            importer_evidence,
            supplier_evidence,
        ),
    )


def _sitemap_index() -> Response:
    with connect() as conn:
        total = int(
            conn.execute(
                select(func.count()).select_from(entities).where(_indexable_company_condition())
            ).scalar_one()
            or 0
        )
    pages = max(1, math.ceil(total / SITEMAP_PAGE_SIZE))
    paths = [
        "/sitemaps/static.xml",
        "/sitemaps/intelligence.xml",
        "/sitemaps/suppliers.xml",
    ]
    paths.extend(f"/sitemaps/companies-{page}.xml" for page in range(1, pages + 1))
    entries = "".join(
        f"<sitemap><loc>{xml_escape(_base_url() + path)}</loc></sitemap>"
        for path in paths
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + entries
        + "</sitemapindex>"
    )
    return Response(body, media_type="application/xml; charset=utf-8")


def _company_sitemap(page: int) -> Response:
    page = max(1, page)
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    with connect() as conn:
        rows = conn.execute(
            select(entities.c.slug, entities.c.updated_at)
            .where(_indexable_company_condition())
            .order_by(entities.c.id.asc())
            .limit(SITEMAP_PAGE_SIZE)
            .offset(offset)
        ).mappings().all()

    urls = []
    for row in rows:
        slug = quote(str(row["slug"]), safe="-")
        loc = xml_escape(f"{_base_url()}/data/company/{slug}")
        lastmod = _iso_date(row.get("updated_at"))
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(
            f"<url><loc>{loc}</loc>{mod}<changefreq>weekly</changefreq></url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(body, media_type="application/xml; charset=utf-8")


def install_evidence_sitemaps(app) -> None:
    """Prefer evidence-backed company URLs over registry-only sitemap flooding."""
    if getattr(app.state, "intellcluster_evidence_sitemaps_installed", False):
        return
    app.state.intellcluster_evidence_sitemaps_installed = True

    @app.middleware("http")
    async def evidence_sitemaps(request: Request, call_next):
        if request.method != "GET" or request.query_params:
            return await call_next(request)
        path = request.url.path
        if path == "/sitemap.xml":
            return _sitemap_index()
        match = re.fullmatch(r"/sitemaps/companies-(\d+)\.xml", path)
        if match:
            return _company_sitemap(int(match.group(1)))
        return await call_next(request)
