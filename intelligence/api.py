from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from intelligence.country_intelligence import COUNTRY_MARKETS, profile_capabilities
from intelligence.database import connect, entities
from intelligence.freshness import directory_freshness
from intelligence.registry import list_sources
from intelligence.repository import get_entity_by_slug, search_entities

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/health")
async def intelligence_health() -> dict[str, object]:
    with connect() as conn:
        entity_count = conn.execute(select(func.count()).select_from(entities)).scalar_one()
    return {
        "status": "ok",
        "registered_sources": len(list_sources()),
        "entities": int(entity_count or 0),
    }


@router.get("/freshness")
async def intelligence_freshness() -> dict[str, object]:
    return directory_freshness()


@router.get("/markets")
async def intelligence_markets() -> dict[str, object]:
    return {"markets": list(COUNTRY_MARKETS.values())}


@router.get("/markets/{country}/capabilities")
async def intelligence_market_capabilities(country: str) -> dict[str, object]:
    return profile_capabilities(country=country)


@router.get("/sources")
async def intelligence_sources() -> dict[str, object]:
    return {"sources": list_sources()}


@router.get("/search")
async def intelligence_search_api(
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    type: str | None = Query(default=None),
    province: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    hs: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="relevance"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    with connect() as conn:
        rows = search_entities(
            conn,
            q=q,
            country=country,
            company_type=type,
            province=province,
            origin=origin,
            hs=hs,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    return {
        "results": rows,
        "count": len(rows),
        "offset": offset,
        "limit": limit,
        "country": country or "all",
    }


@router.get("/company/{slug}")
async def intelligence_company_api(slug: str) -> dict[str, object]:
    with connect() as conn:
        row = get_entity_by_slug(conn, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"company": row, "capabilities": profile_capabilities(row)}
