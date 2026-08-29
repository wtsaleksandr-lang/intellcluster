from __future__ import annotations

import csv
import io
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from intelligence.country_intelligence import profile_capabilities
from intelligence.database import connect
from intelligence.enrichment.epa_echo import EPAEchoClient, EchoFacility, compact_echo_profile
from intelligence.enrichment.fmcsa import FMCSAClient, FMCSACompany
from intelligence.enrichment.importyeti import (
    ImportYetiClient,
    compact_profile,
    live_importyeti_enabled,
    load_importyeti_fixture,
)
from intelligence.enrichment.usaspending import (
    USARecipientMatch,
    USAspendingClient,
    compact_usaspending_profile,
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


def _marker_is_recent(marker: object, max_age_days: int = 7) -> bool:
    if not isinstance(marker, dict) or not marker.get("checked_at"):
        return False
    try:
        checked = datetime.fromisoformat(str(marker["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return datetime.now(UTC) - checked <= timedelta(days=max_age_days)


def _fmcsa_profile(match: FMCSACompany) -> dict:
    status = {"A": "Active", "P": "Pending", "I": "Inactive"}.get(match.status_code or "", match.status_code or "Unknown")
    return {
        "usdot_number": match.dot_number,
        "legal_name": match.legal_name,
        "dba_name": match.dba_name,
        "status_code": match.status_code,
        "status": status,
        "street": match.street,
        "city": match.city,
        "state": match.state,
        "postal_code": match.postal_code,
        "country": match.country,
        "phone": match.phone,
        "cell_phone": match.cell_phone,
        "power_units": match.power_units,
        "total_drivers": match.total_drivers,
        "mcs150_date": match.mcs150_date,
        "add_date": match.add_date,
        "carrier_operation": match.carrier_operation,
        "source": "FMCSA Company Census File",
        "source_url": f"https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string={match.dot_number}",
    }


def _choose_fmcsa(company: dict, matches: list[FMCSACompany]) -> FMCSACompany | None:
    wanted = _name_key(str(company.get("name") or ""))
    if not wanted:
        return None
    for match in matches:
        if wanted in {_name_key(match.legal_name), _name_key(match.dba_name or "")}:
            return match
    state = str(company.get("province") or "").strip().upper()
    city = str(company.get("city") or "").strip().casefold()
    for match in matches:
        if not _confident_importyeti_match(str(company.get("name") or ""), match.display_name):
            continue
        state_ok = not state or state == str(match.state or "").upper()
        city_ok = not city or city == str(match.city or "").casefold()
        if state_ok and city_ok:
            return match
    return None


def _choose_usaspending(company: dict, matches: list[USARecipientMatch]) -> USARecipientMatch | None:
    wanted = _name_key(str(company.get("name") or ""))
    if not wanted:
        return None
    for match in matches:
        if wanted == _name_key(match.name):
            return match
    for match in matches:
        if _confident_importyeti_match(str(company.get("name") or ""), match.name):
            return match
    return None


def _choose_echo_facilities(company: dict, matches: list[EchoFacility]) -> list[EchoFacility]:
    company_name = str(company.get("name") or "")
    state = str(company.get("province") or "").strip().upper()
    city = str(company.get("city") or "").strip().casefold()
    chosen: list[EchoFacility] = []
    for match in matches:
        if not _confident_importyeti_match(company_name, match.name):
            continue
        if state and match.state and state != match.state.upper():
            continue
        if city and match.city and city == match.city.casefold():
            chosen.insert(0, match)
        else:
            chosen.append(match)
    return chosen[:25]


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


async def _enrich_us_public(company: dict) -> tuple[dict, dict]:
    """Fetch free U.S. public intelligence once, cache it, and never call paid trade APIs."""
    if str(company.get("country") or "").upper() != "US" or not company.get("id"):
        return company, {"status": "not_us"}

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    marker = enrichment.get("us_public_lookup") if isinstance(enrichment, dict) else None
    need_fmcsa = not isinstance(enrichment.get("fmcsa"), dict)
    need_spending = not isinstance(enrichment.get("usaspending"), dict)
    need_echo = not isinstance(enrichment.get("epa_echo"), dict)
    if not need_fmcsa and not need_spending and not need_echo:
        return company, {"status": "cached", "fmcsa": "cached", "usaspending": "cached", "epa_echo": "cached"}
    marker_has_echo = isinstance(marker, dict) and "epa_echo" in marker
    if _marker_is_recent(marker) and (marker_has_echo or not need_echo):
        return company, {"status": "recently_checked", **marker}

    result: dict[str, str] = {"status": "checked"}
    fmcsa_profile: dict | None = None
    spending_profile: dict | None = None
    echo_profile: dict | None = None

    if need_fmcsa:
        try:
            matches = await FMCSAClient(timeout=12).search(str(company.get("name") or ""), limit=8)
            chosen = _choose_fmcsa(company, matches)
            if chosen:
                fmcsa_profile = _fmcsa_profile(chosen)
                result["fmcsa"] = "matched"
            else:
                result["fmcsa"] = "no_confident_match"
        except (httpx.HTTPError, RuntimeError, ValueError):
            result["fmcsa"] = "unavailable"
    else:
        result["fmcsa"] = "cached"

    if need_spending:
        try:
            client = USAspendingClient(timeout=12)
            matches = await client.search_recipients(str(company.get("name") or ""), limit=8)
            chosen = _choose_usaspending(company, matches)
            if chosen:
                awards = await client.contract_awards(chosen.recipient_id, limit=25)
                spending_profile = compact_usaspending_profile(chosen, awards)
                result["usaspending"] = "matched"
            else:
                result["usaspending"] = "no_confident_match"
        except (httpx.HTTPError, RuntimeError, ValueError):
            result["usaspending"] = "unavailable"
    else:
        result["usaspending"] = "cached"

    if need_echo:
        try:
            client = EPAEchoClient(timeout=12)
            matches = await client.search_facilities(
                str(company.get("name") or ""),
                state=str(company.get("province") or "") or None,
                city=str(company.get("city") or "") or None,
                limit=25,
            )
            chosen = _choose_echo_facilities(company, matches)
            if chosen:
                echo_profile = compact_echo_profile(chosen)
                result["epa_echo"] = "matched"
            else:
                result["epa_echo"] = "no_confident_match"
        except (httpx.HTTPError, RuntimeError, ValueError):
            result["epa_echo"] = "unavailable"
    else:
        result["epa_echo"] = "cached"

    marker_payload = {
        "checked_at": datetime.now(UTC).isoformat(),
        "fmcsa": result.get("fmcsa", "unknown"),
        "usaspending": result.get("usaspending", "unknown"),
        "epa_echo": result.get("epa_echo", "unknown"),
        "source": "free_public_us_enrichment",
    }
    with connect() as conn:
        entity_id = int(company["id"])
        if fmcsa_profile:
            set_entity_enrichment(conn, entity_id, "fmcsa", fmcsa_profile)
        if spending_profile:
            set_entity_enrichment(conn, entity_id, "usaspending", spending_profile)
        if echo_profile:
            set_entity_enrichment(conn, entity_id, "epa_echo", echo_profile)
        set_entity_enrichment(conn, entity_id, "us_public_lookup", marker_payload)
        refreshed = get_entity_by_slug(conn, company["slug"])
    return refreshed or company, {**result, **marker_payload}


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


@router.post("/api/intelligence/company/{slug}/enrich/us-public", response_class=JSONResponse)
async def intelligence_company_us_public_enrichment(slug: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return JSONResponse({"error": "Company not found."}, status_code=404)
    if str(company.get("country") or "").upper() != "US":
        return JSONResponse({"error": "Free U.S. public enrichment applies only to U.S. company profiles."}, status_code=400)
    refreshed, lookup = await _enrich_us_public(company)
    return JSONResponse({"company": refreshed, "capabilities": profile_capabilities(refreshed), "lookup": lookup})


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
    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    fmcsa = enrichment.get("fmcsa") if isinstance(enrichment.get("fmcsa"), dict) else None
    if fmcsa:
        for field in ("usdot_number", "status", "power_units", "total_drivers", "carrier_operation", "phone", "mcs150_date"):
            writer.writerow(["fleet", field, fmcsa.get(field, ""), "FMCSA Company Census File"])
    spending = enrichment.get("usaspending") if isinstance(enrichment.get("usaspending"), dict) else None
    if spending:
        writer.writerow(["contracts", "uei", spending.get("uei", ""), "USAspending.gov"])
        writer.writerow(["contracts", "awards_shown", spending.get("contract_awards_shown", ""), "USAspending.gov"])
        writer.writerow(["contracts", "award_value_shown", spending.get("contract_award_value_shown", ""), "USAspending.gov"])
        writer.writerow(["contracts", "awarding_agencies", _csv_cell(spending.get("awarding_agencies") or []), "USAspending.gov"])
        for award in (spending.get("awards") or [])[:25]:
            writer.writerow(["contract_award", award.get("award_id", ""), award.get("amount", ""), award.get("awarding_agency", "")])
    echo = enrichment.get("epa_echo") if isinstance(enrichment.get("epa_echo"), dict) else None
    if echo:
        for field in ("facility_count", "major_facility_count", "active_facility_count", "inspections_5y", "formal_actions_5y", "informal_actions_5y", "penalty_events_5y", "total_penalties"):
            writer.writerow(["environmental_compliance", field, echo.get(field, ""), "EPA ECHO"])
        for facility in (echo.get("facilities") or [])[:25]:
            writer.writerow(["epa_facility", facility.get("registry_id", ""), facility.get("name", ""), facility.get("address", "")])
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
