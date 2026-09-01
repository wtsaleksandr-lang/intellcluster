from __future__ import annotations

import os
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select

from intelligence.database import connect, entities, importer_relationships, source_records

router = APIRouter(tags=["intelligence-market-landings"])
templates = Jinja2Templates(directory="intelligence/templates")

_MARKETS = {
    "canada": {
        "code": "CA",
        "flag": "🇨🇦",
        "name": "Canada",
        "title": "Canada Company & Importer Intelligence",
        "description": (
            "Search Canadian companies and importers with corporation records, HS codes, "
            "product categories, sourcing countries and public trade-market evidence."
        ),
        "directory_label": "Browse Canadian companies",
        "primary_source": "Corporations Canada + Canadian Importers Database",
        "topics": [
            ("Canadian corporations", "Federal corporate identity, status, location and incorporation evidence."),
            ("Canadian importers", "Importer evidence connected to products, HS classifications and origin countries."),
            ("HS code intelligence", "Explore product classifications and the Canadian companies associated with them."),
            ("Sourcing geography", "Trace public importer relationships to origin countries and regional markets."),
        ],
    },
    "usa": {
        "code": "US",
        "flag": "🇺🇸",
        "name": "United States",
        "title": "U.S. Company, Carrier & Public Intelligence",
        "description": (
            "Research U.S. companies using FMCSA carrier records, federal awards, SEC filings, "
            "EPA and OSHA evidence, plus cached supplier and shipment intelligence when available."
        ),
        "directory_label": "Browse U.S. companies",
        "primary_source": "FMCSA + USAspending + SEC + EPA/OSHA",
        "topics": [
            ("U.S. carriers and fleets", "FMCSA identity, operating status, power units and driver evidence."),
            ("Federal contracts", "Cached USAspending recipient and award intelligence for government business signals."),
            ("SEC financial evidence", "Public-company filing history and standardized XBRL financial facts when matched."),
            ("Facilities & compliance", "Free EPA ECHO and OSHA inspection evidence added conservatively when matched."),
        ],
    },
}


def _base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://intellcluster.com").strip().rstrip("/")


def _market_stats(code: str) -> dict:
    country = func.upper(func.coalesce(entities.c.country, ""))
    with connect() as conn:
        company_count = int(
            conn.execute(
                select(func.count(entities.c.id)).where(country == code)
            ).scalar_one()
            or 0
        )
        importer_count = int(
            conn.execute(
                select(func.count(entities.c.id)).where(
                    country == code,
                    entities.c.is_importer.is_(True),
                )
            ).scalar_one()
            or 0
        )
        strong_records = int(
            conn.execute(
                select(func.count(source_records.c.id))
                .select_from(source_records.join(entities, source_records.c.entity_id == entities.c.id))
                .where(
                    country == code,
                    source_records.c.source.in_(("canadian_importers", "fmcsa_company_census")),
                )
            ).scalar_one()
            or 0
        )
        relationship_count = int(
            conn.execute(
                select(func.count(importer_relationships.c.id))
                .select_from(importer_relationships.join(entities, importer_relationships.c.entity_id == entities.c.id))
                .where(country == code)
            ).scalar_one()
            or 0
        )
        regions = conn.execute(
            select(
                entities.c.region.label("region"),
                func.count(entities.c.id).label("count"),
            )
            .where(country == code, entities.c.region.is_not(None), entities.c.region != "")
            .group_by(entities.c.region)
            .order_by(func.count(entities.c.id).desc())
            .limit(12)
        ).mappings().all()
        cities = conn.execute(
            select(
                entities.c.region.label("region"),
                entities.c.city.label("city"),
                func.count(entities.c.id).label("count"),
            )
            .where(
                country == code,
                entities.c.region.is_not(None),
                entities.c.city.is_not(None),
                entities.c.city != "",
            )
            .group_by(entities.c.region, entities.c.city)
            .order_by(func.count(entities.c.id).desc())
            .limit(12)
        ).mappings().all()

    return {
        "company_count": company_count,
        "importer_count": importer_count,
        "strong_records": strong_records,
        "relationship_count": relationship_count,
        "regions": [dict(row) for row in regions],
        "cities": [dict(row) for row in cities],
    }


async def _market_page(request: Request, slug: str) -> HTMLResponse:
    market = dict(_MARKETS[slug])
    stats = _market_stats(str(market["code"]))
    canonical = f"{_base_url()}/data/{slug}"
    collection_schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": market["title"],
        "description": market["description"],
        "url": canonical,
        "isPartOf": {
            "@type": "WebSite",
            "name": "IntellCluster",
            "url": _base_url(),
        },
        "about": {
            "@type": "Country",
            "name": market["name"],
        },
    }
    return templates.TemplateResponse(
        request=request,
        name="market_landing.html",
        context={
            "active": "search",
            "market": market,
            "market_slug": slug,
            "stats": stats,
            "collection_schema": collection_schema,
        },
    )


@router.get("/data/canada", response_class=HTMLResponse)
async def canada_market(request: Request) -> HTMLResponse:
    return await _market_page(request, "canada")


@router.get("/data/usa", response_class=HTMLResponse)
async def usa_market(request: Request) -> HTMLResponse:
    return await _market_page(request, "usa")


@router.get("/sitemaps/markets.xml")
async def markets_sitemap() -> Response:
    base = _base_url()
    urls = "".join(
        f"<url><loc>{xml_escape(base + '/data/' + slug)}</loc><changefreq>weekly</changefreq></url>"
        for slug in _MARKETS
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + urls
        + "</urlset>"
    )
    return Response(body, media_type="application/xml; charset=utf-8")
