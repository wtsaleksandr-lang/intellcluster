from __future__ import annotations

from collections import Counter
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.engine import Connection

from intelligence.database import connect, entities, normalize_name, supplier_relationships

router = APIRouter(tags=["intelligence-supplier"])
templates = Jinja2Templates(directory="intelligence/templates")


def _supplier_name(item: dict) -> str:
    return str(item.get("supplier_name") or item.get("name") or item.get("Shipper_Name") or "").strip()


def _supplier_country(item: dict) -> str:
    return str(
        item.get("country")
        or item.get("supplier_address_country")
        or item.get("supplier_country")
        or ""
    ).strip()


def _supplier_address(item: dict) -> str:
    return str(item.get("supplier_address") or item.get("address") or "").strip()


def _shipments(item: dict) -> int:
    raw = item.get("total_shipments_company") or item.get("total_shipments") or item.get("shipments") or 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _matching_bols(profile: dict, supplier_normalized: str) -> list[dict]:
    matches = []
    for bol in profile.get("recent_bols") or []:
        if not isinstance(bol, dict):
            continue
        shipper = str(bol.get("Shipper_Name") or bol.get("shipper_name") or "").strip()
        if shipper and normalize_name(shipper) == supplier_normalized:
            matches.append(bol)
    return matches[:40]


def sync_supplier_relationships(conn: Connection, importer_entity_id: int, profile: dict) -> int:
    """Index supplier rows from one cached ImportYeti company profile.

    This function performs database-only work. It never calls ImportYeti or any
    other external service and is safe to run whenever a cached company is viewed.
    """
    suppliers = profile.get("suppliers_table") if isinstance(profile, dict) else None
    if not isinstance(suppliers, list):
        return 0

    seen: set[str] = set()
    written = 0
    cached_at = str(profile.get("_cachedAt") or "")[:80]
    for item in suppliers[:60]:
        if not isinstance(item, dict):
            continue
        name = _supplier_name(item)
        normalized = normalize_name(name)
        if not name or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        products = item.get("product_descriptions") or item.get("products") or []
        if isinstance(products, str):
            products = [products]
        products = [str(value).strip() for value in products if str(value).strip()][:40]
        values = {
            "importer_entity_id": importer_entity_id,
            "supplier_name": name[:500],
            "supplier_normalized": normalized[:500],
            "supplier_country": _supplier_country(item)[:180] or None,
            "supplier_address": _supplier_address(item) or None,
            "total_shipments": _shipments(item),
            "product_descriptions": products,
            "recent_bols": _matching_bols(profile, normalized),
            "source": "importyeti",
            "source_cached_at": cached_at or None,
        }
        existing = conn.execute(
            select(supplier_relationships.c.id).where(
                supplier_relationships.c.importer_entity_id == importer_entity_id,
                supplier_relationships.c.supplier_normalized == normalized,
                supplier_relationships.c.source == "importyeti",
            )
        ).scalar_one_or_none()
        if existing is None:
            conn.execute(supplier_relationships.insert().values(**values))
        else:
            conn.execute(supplier_relationships.update().where(supplier_relationships.c.id == existing).values(**values))
        written += 1

    if seen:
        conn.execute(
            supplier_relationships.delete().where(
                supplier_relationships.c.importer_entity_id == importer_entity_id,
                supplier_relationships.c.source == "importyeti",
                supplier_relationships.c.supplier_normalized.not_in(seen),
            )
        )
    return written


def supplier_intelligence(name: str) -> dict:
    decoded = unquote(name).strip()
    normalized = normalize_name(decoded)
    if not normalized or len(decoded) > 500:
        return {"error": "Invalid supplier name."}

    with connect() as conn:
        rows = conn.execute(
            select(
                supplier_relationships.c.supplier_name,
                supplier_relationships.c.supplier_country,
                supplier_relationships.c.supplier_address,
                supplier_relationships.c.total_shipments,
                supplier_relationships.c.product_descriptions,
                supplier_relationships.c.recent_bols,
                supplier_relationships.c.source_cached_at,
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.city,
                entities.c.region,
                entities.c.country,
                entities.c.buyer_score,
            )
            .select_from(
                supplier_relationships.join(
                    entities,
                    supplier_relationships.c.importer_entity_id == entities.c.id,
                )
            )
            .where(supplier_relationships.c.supplier_normalized == normalized)
            .order_by(supplier_relationships.c.total_shipments.desc())
        ).mappings().all()

    if not rows:
        return {"error": f"No cached supplier relationships found for {decoded}."}

    name_counter: Counter[str] = Counter()
    country_counter: Counter[str] = Counter()
    product_counter: Counter[str] = Counter()
    hs_counter: Counter[str] = Counter()
    bol_seen: set[str] = set()
    recent_bols: list[dict] = []
    importers = []
    cached_dates = []
    total_shipments = 0

    for row in rows:
        supplier_name = str(row["supplier_name"] or decoded)
        name_counter[supplier_name] += 1
        country = str(row["supplier_country"] or "").strip()
        if country:
            country_counter[country] += max(1, int(row["total_shipments"] or 0))
        shipments = int(row["total_shipments"] or 0)
        total_shipments += shipments
        products = row["product_descriptions"] if isinstance(row["product_descriptions"], list) else []
        for product in products:
            if str(product).strip():
                product_counter[str(product).strip()] += max(1, shipments)
        for bol in row["recent_bols"] if isinstance(row["recent_bols"], list) else []:
            if not isinstance(bol, dict):
                continue
            number = str(bol.get("Bill_of_Lading") or bol.get("bill_of_lading") or "").strip()
            dedupe = number or repr(sorted(bol.items()))
            if dedupe in bol_seen:
                continue
            bol_seen.add(dedupe)
            hs = str(bol.get("HS_Code") or bol.get("hs_code") or "").strip()
            if hs:
                hs_counter[hs] += 1
            recent_bols.append(bol)
        if row["source_cached_at"]:
            cached_dates.append(str(row["source_cached_at"]))
        importers.append(
            {
                "slug": row["slug"],
                "name": row["canonical_name"],
                "city": row["city"] or "",
                "province": row["region"] or "",
                "country": row["country"] or "",
                "buyer_score": int(row["buyer_score"] or 0),
                "shipments": shipments,
                "products": products[:5],
            }
        )

    recent_bols.sort(key=lambda item: str(item.get("date_formatted") or item.get("Arrival_Date") or ""), reverse=True)
    display_name = name_counter.most_common(1)[0][0]
    primary_country = country_counter.most_common(1)[0][0] if country_counter else ""
    return {
        "name": display_name,
        "country": primary_country,
        "importer_count": len(importers),
        "total_shipments": total_shipments,
        "importers": importers[:100],
        "countries": [
            {"label": label, "count": count}
            for label, count in country_counter.most_common(10)
        ],
        "products": [
            {"label": label, "count": count}
            for label, count in product_counter.most_common(20)
        ],
        "hs_codes": [
            {"label": label, "count": count}
            for label, count in hs_counter.most_common(20)
        ],
        "recent_bols": recent_bols[:60],
        "cached_at": max(cached_dates) if cached_dates else "",
    }


@router.get("/data/supplier/{supplier:path}", response_class=HTMLResponse)
async def supplier_page(request: Request, supplier: str):
    data = supplier_intelligence(supplier)
    return templates.TemplateResponse(
        request=request,
        name="supplier.html",
        context={
            "active": "search",
            "supplier": None if data.get("error") else data,
            "error": data.get("error"),
        },
        status_code=404 if data.get("error") else 200,
    )
