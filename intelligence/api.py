from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from intelligence.country_intelligence import COUNTRY_MARKETS, profile_capabilities
from intelligence.database import connect, entities
from intelligence.enrichment.epa_echo import EPAEchoClient, compact_echo_profile
from intelligence.enrichment.fmcsa import FMCSAClient
from intelligence.enrichment.osha import OSHAClient, compact_osha_profile
from intelligence.enrichment.usaspending import USAspendingClient
from intelligence.entity_resolution import normalize_company_name
from intelligence.freshness import directory_freshness
from intelligence.registry import list_sources
from intelligence.repository import get_entity_by_slug, search_entities, set_entity_enrichment

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


def _similar_name(left: str, right: str) -> bool:
    a = normalize_company_name(left); b = normalize_company_name(right)
    if not a or not b: return False
    if a == b: return True
    a_tokens, b_tokens = set(a.split()), set(b.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    return overlap >= 0.72 or (len(a) >= 5 and (a in b or b in a))


def _same_place(expected_state: str, expected_city: str, state: str | None, city: str | None) -> bool:
    if expected_state and state and state.strip().upper() != expected_state: return False
    if expected_city and city and city.strip().casefold() != expected_city.casefold(): return False
    return True


def _fmcsa_profile(company) -> dict[str, object]:
    return {"dot_number": company.dot_number, "status_code": company.status_code, "legal_name": company.legal_name,
            "dba_name": company.dba_name, "phone": company.phone, "cell_phone": company.cell_phone,
            "power_units": company.power_units, "total_drivers": company.total_drivers, "mcs150_date": company.mcs150_date,
            "add_date": company.add_date, "carrier_operation": company.carrier_operation, "city": company.city,
            "state": company.state, "postal_code": company.postal_code, "source": "FMCSA Company Census"}


@router.get("/health")
async def intelligence_health() -> dict[str, object]:
    with connect() as conn: entity_count = conn.execute(select(func.count()).select_from(entities)).scalar_one()
    return {"status": "ok", "registered_sources": len(list_sources()), "entities": int(entity_count or 0)}

@router.get("/freshness")
async def intelligence_freshness() -> dict[str, object]: return directory_freshness()
@router.get("/markets")
async def intelligence_markets() -> dict[str, object]: return {"markets": list(COUNTRY_MARKETS.values())}
@router.get("/markets/{country}/capabilities")
async def intelligence_market_capabilities(country: str) -> dict[str, object]: return profile_capabilities(country=country)
@router.get("/sources")
async def intelligence_sources() -> dict[str, object]: return {"sources": list_sources()}

@router.get("/search")
async def intelligence_search_api(q: str | None=Query(default=None), country: str | None=Query(default=None), type: str | None=Query(default=None), province: str | None=Query(default=None), origin: str | None=Query(default=None), hs: str | None=Query(default=None), status: str | None=Query(default=None), sort: str=Query(default="relevance"), limit: int=Query(default=25,ge=1,le=100), offset: int=Query(default=0,ge=0)) -> dict[str, object]:
    with connect() as conn: rows=search_entities(conn,q=q,country=country,company_type=type,province=province,origin=origin,hs=hs,status=status,sort=sort,limit=limit,offset=offset)
    return {"results":rows,"count":len(rows),"offset":offset,"limit":limit,"country":country or "all"}

@router.get("/company/{slug}")
async def intelligence_company_api(slug: str) -> dict[str, object]:
    with connect() as conn: row=get_entity_by_slug(conn,slug)
    if row is None: raise HTTPException(status_code=404,detail="Company not found")
    return {"company":row,"capabilities":profile_capabilities(row)}


async def _compliance(row: dict, enrichment: dict, lookup: dict[str,str]) -> None:
    entity_id=int(row["id"]); name=str(row.get("name") or ""); state=str(row.get("province") or "").strip().upper(); city=str(row.get("city") or "").strip()
    if isinstance(enrichment.get("epa_echo"),dict): lookup["epa_echo"]="cached"
    else:
        try:
            facilities=await EPAEchoClient(timeout=12).search_facilities(name,state=state or None,city=city or None,limit=25)
            facilities=[f for f in facilities if _similar_name(name,f.name) and _same_place(state,city,f.state,f.city)][:25]
            if facilities:
                with connect() as conn: set_entity_enrichment(conn,entity_id,"epa_echo",compact_echo_profile(facilities))
                lookup["epa_echo"]="matched"
            else: lookup["epa_echo"]="no_confident_match"
        except (httpx.HTTPError,RuntimeError,ValueError): lookup["epa_echo"]="unavailable"
    if isinstance(enrichment.get("osha"),dict): lookup["osha"]="cached"
    else:
        try:
            inspections=await OSHAClient(timeout=12).search(name,state=state or None,limit=60)
            inspections=[i for i in inspections if _similar_name(name,i.establishment_name) and (not state or not i.state or i.state.upper()==state)][:60]
            if inspections:
                with connect() as conn: set_entity_enrichment(conn,entity_id,"osha",compact_osha_profile(inspections))
                lookup["osha"]="matched"
            else: lookup["osha"]="no_confident_match"
        except (httpx.HTTPError,RuntimeError,ValueError): lookup["osha"]="unavailable"


@router.post("/company/{slug}/enrich/us-public")
async def intelligence_company_us_public_enrichment(slug: str) -> dict[str, object]:
    """One-click free-only U.S. enrichment. Never calls ImportYeti or another paid source."""
    with connect() as conn: row=get_entity_by_slug(conn,slug)
    if row is None: raise HTTPException(status_code=404,detail="Company not found")
    if str(row.get("country") or "").upper()!="US": raise HTTPException(status_code=400,detail="U.S. public enrichment applies to U.S. companies")
    enrichment=row.get("enrichment") if isinstance(row.get("enrichment"),dict) else {}; lookup:dict[str,str]={}; entity_id=int(row["id"]); name=str(row.get("name") or ""); state=str(row.get("province") or "").strip().upper(); city=str(row.get("city") or "").strip()
    if isinstance(enrichment.get("fmcsa"),dict): lookup["fmcsa"]="cached"
    else:
        try:
            matches=await FMCSAClient(timeout=12).search(name,limit=10)
            matches=[m for m in matches if _similar_name(name,m.display_name) and _same_place(state,city,m.state,m.city)]
            if len(matches)==1:
                with connect() as conn: set_entity_enrichment(conn,entity_id,"fmcsa",_fmcsa_profile(matches[0]))
                lookup["fmcsa"]="matched"
            else: lookup["fmcsa"]="ambiguous" if matches else "no_confident_match"
        except (httpx.HTTPError,RuntimeError,ValueError): lookup["fmcsa"]="unavailable"
    if isinstance(enrichment.get("usaspending"),dict): lookup["usaspending"]="cached"
    else:
        try:
            profile=await USAspendingClient(timeout=15).company_profile(name,award_limit=25)
            profile_name=str(profile.get("name") or "") if isinstance(profile,dict) else ""
            locations=profile.get("locations") or [] if isinstance(profile,dict) else []
            place_ok=not locations or any(_same_place(state,city,str(x.get("state") or ""),str(x.get("city") or "")) for x in locations if isinstance(x,dict))
            if profile and _similar_name(name,profile_name) and place_ok:
                with connect() as conn: set_entity_enrichment(conn,entity_id,"usaspending",profile)
                lookup["usaspending"]="matched"
            else: lookup["usaspending"]="no_confident_match"
        except (httpx.HTTPError,RuntimeError,ValueError): lookup["usaspending"]="unavailable"
    await _compliance(row,enrichment,lookup)
    with connect() as conn: refreshed=get_entity_by_slug(conn,slug)
    assert refreshed is not None
    return {"company":refreshed,"capabilities":profile_capabilities(refreshed),"lookup":lookup,"paid_sources_called":False}


@router.post("/company/{slug}/enrich/compliance")
async def intelligence_company_compliance_enrichment(slug: str) -> dict[str, object]:
    with connect() as conn: row=get_entity_by_slug(conn,slug)
    if row is None: raise HTTPException(status_code=404,detail="Company not found")
    if str(row.get("country") or "").upper()!="US": raise HTTPException(status_code=400,detail="Compliance enrichment currently applies to U.S. companies")
    enrichment=row.get("enrichment") if isinstance(row.get("enrichment"),dict) else {}; lookup:dict[str,str]={}
    await _compliance(row,enrichment,lookup)
    with connect() as conn: refreshed=get_entity_by_slug(conn,slug)
    assert refreshed is not None
    return {"company":refreshed,"capabilities":profile_capabilities(refreshed),"lookup":lookup,"paid_sources_called":False}
