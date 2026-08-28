from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from intelligence.country_intelligence import COUNTRY_MARKETS, profile_capabilities
from intelligence.database import connect, entities
from intelligence.enrichment.epa_echo import EPAEchoClient, compact_echo_profile
from intelligence.enrichment.osha import OSHAClient, compact_osha_profile
from intelligence.entity_resolution import normalize_company_name
from intelligence.freshness import directory_freshness
from intelligence.registry import list_sources
from intelligence.repository import get_entity_by_slug, search_entities, set_entity_enrichment

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


def _similar_name(left: str, right: str) -> bool:
    a = normalize_company_name(left)
    b = normalize_company_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    return overlap >= 0.72 or (len(a) >= 5 and (a in b or b in a))


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


@router.post("/company/{slug}/enrich/compliance")
async def intelligence_company_compliance_enrichment(slug: str) -> dict[str, object]:
    """Cache free EPA ECHO and OSHA evidence for one U.S. company profile."""
    with connect() as conn:
        row = get_entity_by_slug(conn, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if str(row.get("country") or "").upper() != "US":
        raise HTTPException(status_code=400, detail="Compliance enrichment currently applies to U.S. companies")

    enrichment = row.get("enrichment") if isinstance(row.get("enrichment"), dict) else {}
    entity_id = int(row["id"])
    name = str(row.get("name") or "")
    state = str(row.get("province") or "").strip().upper()
    city = str(row.get("city") or "").strip()
    lookup: dict[str, str] = {}

    if isinstance(enrichment.get("epa_echo"), dict):
        lookup["epa_echo"] = "cached"
    else:
        try:
            facilities = await EPAEchoClient(timeout=12).search_facilities(
                name,
                state=state or None,
                city=city or None,
                limit=25,
            )
            facilities = [
                facility
                for facility in facilities
                if _similar_name(name, facility.name)
                and (not state or not facility.state or facility.state.upper() == state)
            ][:25]
            if facilities:
                with connect() as conn:
                    set_entity_enrichment(conn, entity_id, "epa_echo", compact_echo_profile(facilities))
                lookup["epa_echo"] = "matched"
            else:
                lookup["epa_echo"] = "no_confident_match"
        except (httpx.HTTPError, RuntimeError, ValueError):
            lookup["epa_echo"] = "unavailable"

    if isinstance(enrichment.get("osha"), dict):
        lookup["osha"] = "cached"
    else:
        try:
            inspections = await OSHAClient(timeout=12).search(name, state=state or None, limit=60)
            inspections = [
                inspection
                for inspection in inspections
                if _similar_name(name, inspection.establishment_name)
                and (not state or not inspection.state or inspection.state.upper() == state)
            ][:60]
            if inspections:
                with connect() as conn:
                    set_entity_enrichment(conn, entity_id, "osha", compact_osha_profile(inspections))
                lookup["osha"] = "matched"
            else:
                lookup["osha"] = "no_confident_match"
        except (httpx.HTTPError, RuntimeError, ValueError):
            lookup["osha"] = "unavailable"

    with connect() as conn:
        refreshed = get_entity_by_slug(conn, slug)
    assert refreshed is not None
    return {"company": refreshed, "capabilities": profile_capabilities(refreshed), "lookup": lookup}
