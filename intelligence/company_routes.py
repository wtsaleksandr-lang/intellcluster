from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from intelligence.country_intelligence import profile_capabilities
from intelligence.database import connect
from intelligence.profile_guard import _not_found_page
from intelligence.repository import get_entity_by_slug, get_entity_enrichment

router = APIRouter(tags=["intelligence-company-pages"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_cached_bol(row: dict[str, Any], *, company: dict[str, Any]) -> dict[str, Any]:
    """Normalize a compact cached BOL row for the shipment-detail template.

    ImportYeti's compact company cache uses historical field names that differ
    from the richer BOL-detail endpoint. Normalizing them lets the detail page use
    evidence already stored on the company profile instead of making a paid call.
    """
    bol = dict(row)
    aliases = {
        "bol_number": ("bol_number", "Bill_of_Lading", "bill_of_lading", "bol"),
        "arrival_date": ("arrival_date", "date_formatted", "Arrival_Date", "date"),
        "weight": ("weight", "Weight_in_KG", "weight_kg"),
        "quantity": ("quantity", "Quantity"),
        "quantity_unit": ("quantity_unit", "Quantity_Unit"),
        "supplier_name": ("supplier_name", "Shipper_Name", "shipper_name", "supplier"),
        "supplier_address": ("supplier_address", "Shipper_Address", "shipper_address"),
        "supplier_country": (
            "supplier_country",
            "supplier_address_country",
            "Shipper_Country",
        ),
        "product_description": (
            "product_description",
            "Product_Description",
            "product_description_raw",
            "description",
        ),
        "hs_code": ("hs_code", "HS_Code", "hts_code"),
        "entry_port": ("entry_port", "Port_of_Entry", "Entry_Port", "destination_port"),
        "exit_port": ("exit_port", "Port_of_Exit", "Exit_Port", "origin_port"),
        "carrier_scac_code": ("carrier_scac_code", "SCAC", "Carrier_SCAC"),
        "vessel_name": ("vessel_name", "Vessel_Name", "vessel"),
        "voyage": ("voyage", "Voyage"),
        "shipping_cost": ("shipping_cost", "freight_cost", "Freight_Cost"),
        "teu": ("teu", "TEU"),
        "company_name": ("company_name", "Consignee_Name", "consignee_name"),
        "company_address": ("company_address", "Consignee_Address", "consignee_address"),
        "company_country": ("company_country", "Consignee_Country", "consignee_country"),
    }
    for target, keys in aliases.items():
        if bol.get(target) in (None, ""):
            value = _first(row, *keys)
            if value not in (None, ""):
                bol[target] = value
    bol.setdefault("company_name", company.get("name"))
    bol.setdefault("company_country", company.get("country"))
    bol["_cache_source"] = "company_recent_bols"
    return bol


def _cached_bol(company: dict[str, Any], enrichment: dict[str, Any], bol_number: str) -> dict[str, Any] | None:
    key = f"importyeti_bol:{bol_number}"
    direct = enrichment.get(key) if isinstance(enrichment, dict) else None
    if isinstance(direct, dict):
        return dict(direct)

    iy = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if not iy and isinstance(enrichment, dict) and isinstance(enrichment.get("importyeti"), dict):
        iy = enrichment.get("importyeti")
    if not isinstance(iy, dict):
        return None

    wanted = str(bol_number or "").strip().casefold()
    for row in iy.get("recent_bols") or []:
        if not isinstance(row, dict):
            continue
        candidate = _first(row, "bol_number", "Bill_of_Lading", "bill_of_lading", "bol")
        if str(candidate or "").strip().casefold() == wanted:
            normalized = _normalize_cached_bol(row, company=company)
            normalized.setdefault("_cachedAt", iy.get("_cachedAt"))
            return normalized
    return None


@router.get("/data/company/{slug}", response_class=HTMLResponse)
async def intelligence_company_page(request: Request, slug: str):
    """Render a canonical company profile from persisted data only."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return HTMLResponse(_not_found_page(slug), status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={
            "active": "company",
            "company": company,
            "capabilities": profile_capabilities(company),
            "demo_mode": False,
        },
    )


@router.get("/data/company/{slug}/bol/{bol_number}", response_class=HTMLResponse)
async def intelligence_cached_bol_page(request: Request, slug: str, bol_number: str):
    """Render BOL evidence from cache only; page views never purchase data."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
        enrichment = get_entity_enrichment(conn, int(company["id"])) if company else {}
    if company is None:
        return templates.TemplateResponse(
            request=request,
            name="bol.html",
            context={
                "active": "company",
                "company": None,
                "bol": None,
                "error": "Company not found.",
            },
            status_code=404,
        )

    bol = _cached_bol(company, enrichment, bol_number)
    return templates.TemplateResponse(
        request=request,
        name="bol.html",
        context={
            "active": "company",
            "company": company,
            "bol": bol,
            "error": (
                None
                if bol
                else "This bill of lading is not cached. Viewing this page never triggers a paid data request."
            ),
        },
        status_code=200,
    )
