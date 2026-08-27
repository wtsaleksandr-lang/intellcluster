from __future__ import annotations

import os
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from intelligence.database import connect
from intelligence.enrichment.importyeti import ImportYetiClient, cache_is_fresh, compact_profile
from intelligence.repository import get_entity_by_slug, search_entities, set_entity_enrichment

router = APIRouter(tags=["intelligence-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

DEMO_COMPANIES = [{"slug":"maple-auto-supply-inc","name":"Maple Auto Supply Inc.","kind":"Importer","city":"Mississauga","province":"ON","country":"CA","status":"Active","incorporated":"2011","hs_codes":["870892","851220"],"products":["Motor vehicle exhaust parts","Automotive lighting equipment"],"origins":["China","Taiwan"],"source_count":2,"buyer_score":94,"is_importer":True}]


def _demo_search(q: str | None = None) -> list[dict]:
    if not q:
        return DEMO_COMPANIES
    needle = q.casefold()
    return [row for row in DEMO_COMPANIES if needle in (row["name"] + " " + " ".join(row["products"])).casefold()]


def _name_key(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"\b(incorporated|inc|corporation|corp|limited|ltd|llc|company|co|canada|usa)\b", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _confident_importyeti_match(company_name: str, match_title: str) -> bool:
    left, right = _name_key(company_name), _name_key(match_title)
    if not left or not right:
        return False
    if left == right:
        return True
    left_tokens, right_tokens = set(left.split()), set(right.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return overlap >= 0.72 or (len(left) >= 5 and (left in right or right in left))


async def _maybe_enrich_importyeti(company: dict) -> dict:
    if not os.getenv("IMPORTYETI_API_KEY") or not company.get("id"):
        return company
    cached = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if cache_is_fresh(cached):
        return company
    try:
        client = ImportYetiClient()
        matches = await client.search_company(company["name"], page_size=5)
        chosen = next((m for m in matches if _confident_importyeti_match(company["name"], m.title)), None)
        if not chosen:
            return company
        profile = compact_profile(await client.company_profile(chosen.slug))
        profile["_slug"] = chosen.slug
        profile["_matchedTitle"] = chosen.title
        profile["_matchAddress"] = chosen.address
        with connect() as conn:
            set_entity_enrichment(conn, int(company["id"]), "importyeti", profile)
            refreshed = get_entity_by_slug(conn, company["slug"])
        return refreshed or company
    except (httpx.HTTPError, RuntimeError, ValueError):
        return company


@router.get("/data", response_class=HTMLResponse)
async def intelligence_home(request: Request):
    return templates.TemplateResponse(request=request, name="home.html", context={"active": "home"})


@router.get("/data/suggest", response_class=JSONResponse)
async def intelligence_suggest(q: str = Query(default="", min_length=0, max_length=120)):
    term = q.strip()
    if len(term) < 2:
        return JSONResponse({"items": []})
    with connect() as conn:
        rows = search_entities(conn, q=term, limit=8)
    items = [{"name":row["name"],"slug":row["slug"],"kind":row.get("kind","Company"),"location":", ".join(x for x in [row.get("city"),row.get("province")] if x),"hs_codes":row.get("hs_codes",[])[:3]} for row in rows]
    return JSONResponse({"items": items})


@router.get("/data/search", response_class=HTMLResponse)
async def intelligence_search(request: Request,q: str | None=Query(default=None),type: str | None=Query(default=None),province: str | None=Query(default=None),origin: str | None=Query(default=None),hs: str | None=Query(default=None),status: str | None=Query(default=None),sort: str=Query(default="relevance")):
    with connect() as conn:
        rows=search_entities(conn,q=q,company_type=type,province=province,origin=origin,hs=hs,status=status,sort=sort,limit=50)
    demo_mode=not rows
    if demo_mode: rows=_demo_search(q)
    return templates.TemplateResponse(request=request,name="search.html",context={"active":"search","companies":rows,"q":q or "","filters":{"type":type or "","province":province or "","origin":origin or "","hs":hs or "","status":status or "","sort":sort},"demo_mode":demo_mode})


@router.get("/data/company/{slug}", response_class=HTMLResponse)
async def intelligence_company(request: Request, slug: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    demo_mode = company is None
    if company is None:
        company = next((row for row in DEMO_COMPANIES if row["slug"] == slug), DEMO_COMPANIES[0])
    elif not demo_mode:
        company = await _maybe_enrich_importyeti(company)
    return templates.TemplateResponse(request=request,name="company.html",context={"active":"company","company":company,"demo_mode":demo_mode})
