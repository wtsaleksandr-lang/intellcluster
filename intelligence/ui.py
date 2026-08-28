from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from intelligence.country_intelligence import profile_capabilities
from intelligence.database import connect
from intelligence.enrichment.importyeti import (
    ImportYetiClient,
    compact_profile,
    live_importyeti_enabled,
    load_importyeti_fixture,
)
from intelligence.repository import (
    get_entity_by_slug,
    get_entity_enrichment,
    search_entities,
    set_entity_enrichment,
)

router = APIRouter(tags=["intelligence-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

DEMO_COMPANIES = [{"slug":"maple-auto-supply-inc","name":"Maple Auto Supply Inc.","kind":"Importer","city":"Mississauga","province":"ON","country":"CA","status":"Active","incorporated":"2011","hs_codes":["870892","851220"],"products":["Motor vehicle exhaust parts","Automotive lighting equipment"],"origins":["China","Taiwan"],"source_count":2,"source_records_count":2,"buyer_score":94,"is_importer":True}]


def _demo_search(q: str | None = None, country: str | None = None) -> list[dict]:
    rows = DEMO_COMPANIES
    if country:
        rows = [row for row in rows if row.get("country") == country]
    if not q:
        return rows
    needle = q.casefold()
    return [row for row in rows if needle in (row["name"] + " " + " ".join(row["products"])).casefold()]


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


def _looks_like_bol(value: str | None) -> bool:
    text = (value or "").strip()
    return (
        9 <= len(text) <= 28
        and " " not in text
        and sum(ch.isalpha() for ch in text) >= 2
        and sum(ch.isdigit() for ch in text) >= 4
        and all(ch.isalnum() or ch in {"-", "_"} for ch in text)
    )


def _referer_company_slug(request: Request) -> str | None:
    ref = request.headers.get("referer", "")
    match = re.search(r"/data/company/([^/?#]+)", ref)
    return match.group(1) if match else None


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    return str(value)


async def _maybe_enrich_importyeti(company: dict) -> dict:
    """Attach shipment intelligence without spending credits during normal browsing."""
    if not company.get("id"):
        return company
    cached = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if cached:
        return company
    fixture = load_importyeti_fixture()
    if fixture is not None:
        profile = compact_profile(fixture)
        profile.setdefault("_slug", str(fixture.get("_slug") or "cached-test-company"))
        profile.setdefault("_matchedTitle", str(fixture.get("title") or company["name"]))
        profile["_fixture"] = True
        with connect() as conn:
            set_entity_enrichment(conn, int(company["id"]), "importyeti", profile)
            refreshed = get_entity_by_slug(conn, company["slug"])
        return refreshed or company
    if not live_importyeti_enabled() or not os.getenv("IMPORTYETI_API_KEY"):
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
async def intelligence_search(
    request: Request,
    q: str | None = Query(default=None),
    country: str | None = Query(default=None),
    type: str | None = Query(default=None),
    province: str | None = Query(default=None),
    city: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    hs: str | None = Query(default=None),
    status: str | None = Query(default=None),
    incorporated_from: int | None = Query(default=None, ge=1800, le=2100),
    incorporated_to: int | None = Query(default=None, ge=1800, le=2100),
    website: str | None = Query(default=None),
    sort: str = Query(default="relevance"),
    page: int = Query(default=1, ge=1),
):
    company_slug = _referer_company_slug(request)
    if company_slug and _looks_like_bol(q):
        return RedirectResponse(url=f"/data/company/{company_slug}/bol/{q}", status_code=302)
    normalized_country = (country or "").strip().upper()
    if normalized_country not in {"CA", "US"}:
        normalized_country = ""
    has_website = True if website == "yes" else False if website == "no" else None
    page_size = 50
    with connect() as conn:
        rows = search_entities(
            conn, q=q, country=normalized_country or None, company_type=type, province=province,
            city=city, origin=origin, hs=hs, status=status, incorporated_from=incorporated_from,
            incorporated_to=incorporated_to, has_website=has_website, sort=sort,
            limit=page_size + 1, offset=(page - 1) * page_size,
        )
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    demo_mode = not rows and page == 1
    if demo_mode:
        rows = _demo_search(q, normalized_country or None)
    filters = {
        "country": normalized_country,
        "type": type or "", "province": province or "", "city": city or "", "origin": origin or "",
        "hs": hs or "", "status": status or "", "incorporated_from": incorporated_from or "",
        "incorporated_to": incorporated_to or "", "website": website or "", "sort": sort,
    }
    return templates.TemplateResponse(
        request=request, name="search.html",
        context={"active":"search","companies":rows,"q":q or "","filters":filters,"demo_mode":demo_mode,"page":page,"has_next":has_next},
    )


@router.get("/data/company/{slug}", response_class=HTMLResponse)
async def intelligence_company(request: Request, slug: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    demo_mode = company is None
    if company is None:
        company = next((row for row in DEMO_COMPANIES if row["slug"] == slug), DEMO_COMPANIES[0])
    elif not demo_mode:
        company = await _maybe_enrich_importyeti(company)
    capabilities = profile_capabilities(company)
    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={"active":"company","company":company,"capabilities":capabilities,"demo_mode":demo_mode},
    )


@router.get("/data/company/{slug}/export.csv")
async def intelligence_company_export(slug: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return Response("Company not found", status_code=404, media_type="text/plain")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "field", "value", "detail"])
    core_rows = [
        ("company", "name", company.get("name"), ""), ("company", "type", company.get("kind"), ""),
        ("company", "status", company.get("status"), ""), ("company", "corporation_number", company.get("corporation_number"), ""),
        ("company", "incorporated_year", company.get("incorporated"), ""), ("company", "city", company.get("city"), ""),
        ("company", "province", company.get("province"), ""), ("company", "country", company.get("country"), ""),
        ("company", "address", company.get("address"), ""), ("company", "website", company.get("website"), ""),
        ("evidence", "source_records", company.get("source_records_count"), ""), ("evidence", "matched_sources", company.get("source_count"), ""),
        ("evidence", "importer_relationships", company.get("relationship_count"), ""), ("ai", "buyer_score", company.get("buyer_score"), ""),
    ]
    for row in core_rows:
        writer.writerow([_csv_cell(cell) for cell in row])
    for item in company.get("hs_breakdown") or []:
        writer.writerow(["hs", item.get("label", ""), item.get("count", ""), item.get("description", "")])
    for item in company.get("origin_breakdown") or []:
        writer.writerow(["origin", item.get("label", ""), item.get("count", ""), f"{item.get('percent', '')}%"])
    for item in company.get("dataset_breakdown") or []:
        writer.writerow(["dataset", item.get("label", ""), item.get("count", ""), f"{item.get('percent', '')}%"])
    iy = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if iy:
        writer.writerow(["shipment", "importyeti_match", iy.get("_matchedTitle") or iy.get("title") or "", ""])
        writer.writerow(["shipment", "total_shipments", iy.get("total_shipments", ""), ""])
        writer.writerow(["shipment", "estimated_shipping_spend", iy.get("total_shipping_cost", ""), ""])
        writer.writerow(["shipment", "cached_at", iy.get("_cachedAt", ""), ""])
        for supplier in (iy.get("suppliers_table") or [])[:60]:
            writer.writerow(["supplier", supplier.get("supplier_name", ""), supplier.get("total_shipments_company", ""), supplier.get("country") or supplier.get("supplier_address_country") or ""])
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", company.get("name") or slug).strip("-")[:100] or "company"
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}-intelligence.csv"'}
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/data/company/{slug}/bol/{bol_number}", response_class=HTMLResponse)
async def intelligence_bol(request: Request, slug: str, bol_number: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
        enrichment = get_entity_enrichment(conn, int(company["id"])) if company else {}
    if company is None:
        return templates.TemplateResponse(request=request,name="bol.html",context={"active":"company","company":None,"bol":None,"error":"Company not found."},status_code=404)
    key = f"importyeti_bol:{bol_number}"
    bol = enrichment.get(key) if isinstance(enrichment, dict) else None
    if bol is None and live_importyeti_enabled() and os.getenv("IMPORTYETI_API_KEY"):
        try:
            bol = await ImportYetiClient().bill_of_lading(bol_number)
            with connect() as conn:
                set_entity_enrichment(conn, int(company["id"]), key, bol)
        except (httpx.HTTPError, RuntimeError, ValueError):
            bol = None
    return templates.TemplateResponse(request=request,name="bol.html",context={"active":"company","company":company,"bol":bol,"error":None if bol else "This bill of lading is not cached."})
