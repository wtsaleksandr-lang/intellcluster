from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from fastapi import Request

from intelligence.database import connect
from intelligence.repository import (
    get_entity_by_slug,
    get_entity_enrichment,
    set_entity_enrichment,
)

_BOL_PATH = re.compile(r"^/data/company/([^/]+)/bol/([^/]+)$")


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_cached_bol(row: dict[str, Any], company: dict[str, Any]) -> dict[str, Any]:
    """Map compact ImportYeti cache fields to the BOL-detail template contract."""
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
    bol["_cache_source"] = "stored_importyeti_evidence"
    return bol


def cached_bol_evidence(
    company: dict[str, Any],
    enrichment: dict[str, Any],
    bol_number: str,
) -> dict[str, Any] | None:
    """Find BOL evidence in direct cache or a cached company recent-BOL list."""
    key = f"importyeti_bol:{bol_number}"
    direct = enrichment.get(key) if isinstance(enrichment, dict) else None
    if isinstance(direct, dict):
        return normalize_cached_bol(direct, company)

    iy = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if not iy and isinstance(enrichment, dict) and isinstance(enrichment.get("importyeti"), dict):
        iy = enrichment["importyeti"]
    if not isinstance(iy, dict):
        return None

    wanted = str(bol_number or "").strip().casefold()
    for row in iy.get("recent_bols") or []:
        if not isinstance(row, dict):
            continue
        candidate = _first(row, "bol_number", "Bill_of_Lading", "bill_of_lading", "bol")
        if str(candidate or "").strip().casefold() != wanted:
            continue
        bol = normalize_cached_bol(row, company)
        bol.setdefault("_cachedAt", iy.get("_cachedAt"))
        return bol
    return None


def install_cached_bol_compat(app) -> None:
    """Make nested cached BOL evidence visible to the existing detail route.

    The historical BOL handler looks for ``importyeti_bol:<number>``. Earlier
    company-profile caches often stored the same evidence only inside
    ``importyeti.recent_bols``. On a matching BOL view, this middleware promotes
    that already-purchased row into the direct cache before routing continues.

    This performs database reads and, at most, one local cache write. It never
    instantiates an enrichment client and cannot make an ImportYeti network call.
    """
    if getattr(app.state, "intellcluster_cached_bol_compat_installed", False):
        return
    app.state.intellcluster_cached_bol_compat_installed = True

    @app.middleware("http")
    async def cached_bol_compat(request: Request, call_next):
        if request.method == "GET":
            match = _BOL_PATH.fullmatch(request.url.path)
            if match:
                slug = unquote(match.group(1))
                bol_number = unquote(match.group(2))
                try:
                    with connect() as conn:
                        company = get_entity_by_slug(conn, slug)
                        if company:
                            entity_id = int(company["id"])
                            enrichment = get_entity_enrichment(conn, entity_id)
                            evidence = cached_bol_evidence(company, enrichment, bol_number)
                            if evidence:
                                key = f"importyeti_bol:{bol_number}"
                                current = enrichment.get(key)
                                if not isinstance(current, dict) or current != evidence:
                                    set_entity_enrichment(conn, entity_id, key, evidence)
                except Exception:
                    # Compatibility hydration must never make the page unavailable.
                    pass
        return await call_next(request)
