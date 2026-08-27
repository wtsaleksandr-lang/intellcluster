from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from intelligence.database import connect, entities
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


@router.get("/sources")
async def intelligence_sources() -> dict[str, object]:
    return {"sources": list_sources()}


@router.get("/search")
async def intelligence_search_api(
    q: str | None = Query(default=None),
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
            company_type=type,
            province=province,
            origin=origin,
            hs=hs,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    return {"results": rows, "count": len(rows), "offset": offset, "limit": limit}


@router.get("/company/{slug}")
async def intelligence_company_api(slug: str) -> dict[str, object]:
    with connect() as conn:
        row = get_entity_by_slug(conn, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return {"company": row}
