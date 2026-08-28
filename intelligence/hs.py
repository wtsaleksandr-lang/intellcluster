from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, or_, select

from intelligence.database import connect, entities, importer_relationships, supplier_relationships
from intelligence.ui import templates

router = APIRouter(tags=["intelligence-hs"])


def _clean_hs(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())[:10]


def _hs_condition(code: str):
    return or_(
        importer_relationships.c.hs6.like(f"{code}%"),
        importer_relationships.c.hs10.like(f"{code}%"),
    )


def _pct(count: int, total: int) -> float:
    return round((count * 100 / total), 1) if total else 0.0


def _child_size(code: str) -> int | None:
    length = len(code)
    if length < 2:
        return 2
    if length < 4:
        return 4
    if length < 6:
        return 6
    if length < 10:
        return 10
    return None


def _prefix_level(length: int) -> str:
    return {2: "Chapter", 4: "Heading", 6: "HS6", 10: "HS10"}.get(length, "HS")


def _bol_hs_matches(bol: dict[str, Any], code: str) -> bool:
    raw = str(bol.get("HS_Code") or bol.get("hs_code") or bol.get("HTS_Code") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return bool(digits and digits.startswith(code))


def _cached_suppliers_for_hs(rows: list[dict[str, Any]], code: str) -> list[dict[str, Any]]:
    ranked: dict[str, dict[str, Any]] = {}
    for row in rows:
        bols = row.get("recent_bols") if isinstance(row.get("recent_bols"), list) else []
        matching_bols = [bol for bol in bols if isinstance(bol, dict) and _bol_hs_matches(bol, code)]
        if not matching_bols:
            continue
        key = str(row.get("supplier_normalized") or row.get("supplier_name") or "").strip()
        if not key:
            continue
        item = ranked.setdefault(
            key,
            {
                "name": str(row.get("supplier_name") or "Unknown supplier"),
                "country": str(row.get("supplier_country") or ""),
                "shipments": 0,
                "matched_bols": 0,
                "importers": {},
                "products": Counter(),
            },
        )
        item["shipments"] += int(row.get("total_shipments") or 0)
        item["matched_bols"] += len(matching_bols)
        importer_name = str(row.get("importer_name") or "")
        importer_slug = str(row.get("importer_slug") or "")
        if importer_name and importer_slug:
            item["importers"][importer_slug] = importer_name
        for bol in matching_bols:
            description = str(bol.get("Product_Description") or bol.get("product_description") or "").strip()
            if description:
                item["products"][description] += 1

    results = []
    for item in ranked.values():
        products: Counter[str] = item.pop("products")
        importers: dict[str, str] = item.pop("importers")
        item["products"] = [label for label, _ in products.most_common(3)]
        item["importers"] = [{"slug": slug, "name": name} for slug, name in list(importers.items())[:5]]
        results.append(item)
    return sorted(results, key=lambda row: (row["matched_bols"], row["shipments"]), reverse=True)[:40]


def get_hs_intelligence(code: str) -> dict[str, Any]:
    with connect() as conn:
        condition = _hs_condition(code)
        total_relationships = int(
            conn.execute(select(func.count(importer_relationships.c.id)).where(condition)).scalar_one() or 0
        )
        company_count = int(
            conn.execute(
                select(func.count(func.distinct(importer_relationships.c.entity_id))).where(condition)
            ).scalar_one()
            or 0
        )
        origin_count = int(
            conn.execute(
                select(func.count(func.distinct(importer_relationships.c.origin_country))).where(
                    and_(condition, importer_relationships.c.origin_country.is_not(None))
                )
            ).scalar_one()
            or 0
        )

        company_rows = conn.execute(
            select(
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.country,
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.buyer_score,
                func.count(importer_relationships.c.id).label("relationships"),
                func.count(func.distinct(importer_relationships.c.origin_country)).label("origins"),
            )
            .select_from(importer_relationships.join(entities, entities.c.id == importer_relationships.c.entity_id))
            .where(condition)
            .group_by(
                entities.c.id,
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.country,
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.buyer_score,
            )
            .order_by(func.count(importer_relationships.c.id).desc(), entities.c.canonical_name)
            .limit(80)
        ).mappings().all()

        origin_rows = conn.execute(
            select(
                importer_relationships.c.origin_country.label("label"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .where(and_(condition, importer_relationships.c.origin_country.is_not(None)))
            .group_by(importer_relationships.c.origin_country)
            .order_by(func.count(importer_relationships.c.id).desc())
            .limit(20)
        ).mappings().all()

        description_rows = conn.execute(
            select(
                importer_relationships.c.product_description.label("label"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .where(and_(condition, importer_relationships.c.product_description.is_not(None)))
            .group_by(importer_relationships.c.product_description)
            .order_by(func.count(importer_relationships.c.id).desc())
            .limit(24)
        ).mappings().all()

        year_rows = conn.execute(
            select(
                importer_relationships.c.activity_year.label("year"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .where(and_(condition, importer_relationships.c.activity_year.is_not(None)))
            .group_by(importer_relationships.c.activity_year)
            .order_by(importer_relationships.c.activity_year)
        ).mappings().all()

        child_len = _child_size(code)
        child_rows = []
        if child_len is not None:
            code_expr = func.coalesce(importer_relationships.c.hs10, importer_relationships.c.hs6)
            prefix_expr = func.substr(code_expr, 1, child_len)
            child_rows = conn.execute(
                select(prefix_expr.label("code"), func.count(importer_relationships.c.id).label("count"))
                .where(and_(condition, func.length(code_expr) >= child_len))
                .group_by(prefix_expr)
                .order_by(func.count(importer_relationships.c.id).desc())
                .limit(36)
            ).mappings().all()

        all_hs_rows = conn.execute(
            select(
                importer_relationships.c.hs6,
                importer_relationships.c.hs10,
                importer_relationships.c.product_description,
            ).where(condition).limit(10000)
        ).mappings().all()

        cached_supplier_rows = conn.execute(
            select(
                supplier_relationships.c.supplier_name,
                supplier_relationships.c.supplier_normalized,
                supplier_relationships.c.supplier_country,
                supplier_relationships.c.total_shipments,
                supplier_relationships.c.recent_bols,
                entities.c.slug.label("importer_slug"),
                entities.c.canonical_name.label("importer_name"),
            )
            .select_from(
                supplier_relationships.join(
                    entities,
                    supplier_relationships.c.importer_entity_id == entities.c.id,
                )
            )
            .where(supplier_relationships.c.source == "importyeti")
            .order_by(supplier_relationships.c.total_shipments.desc())
            .limit(5000)
        ).mappings().all()

    companies = []
    for row in company_rows:
        relationships = int(row["relationships"] or 0)
        companies.append(
            {
                "slug": row["slug"],
                "name": row["canonical_name"],
                "country": row["country"] or "",
                "city": row["city"] or "",
                "province": row["region"] or "",
                "status": (row["corporate_status"] or "Unknown").title(),
                "buyer_score": int(row["buyer_score"] or 0),
                "relationships": relationships,
                "origins": int(row["origins"] or 0),
                "share": _pct(relationships, total_relationships),
            }
        )

    origins = [
        {"label": row["label"], "count": int(row["count"] or 0), "percent": _pct(int(row["count"] or 0), total_relationships)}
        for row in origin_rows
    ]
    descriptions = [
        {"label": row["label"], "count": int(row["count"] or 0), "percent": _pct(int(row["count"] or 0), total_relationships)}
        for row in description_rows
    ]
    years = [{"year": int(row["year"]), "count": int(row["count"] or 0)} for row in year_rows]

    description_by_prefix: dict[str, Counter[str]] = {}
    for row in all_hs_rows:
        full_code = str(row["hs10"] or row["hs6"] or "")
        description = str(row["product_description"] or "").strip()
        if not full_code or not description:
            continue
        for size in (2, 4, 6, 10):
            if len(full_code) >= size:
                description_by_prefix.setdefault(full_code[:size], Counter())[description] += 1

    hierarchy = []
    for size, label in ((2, "Chapter"), (4, "Heading"), (6, "HS6"), (10, "HS10")):
        if len(code) >= size:
            prefix = code[:size]
            top_desc = description_by_prefix.get(prefix, Counter()).most_common(1)
            hierarchy.append({"code": prefix, "label": label, "description": top_desc[0][0] if top_desc else ""})

    children = []
    for row in child_rows:
        child_code = str(row["code"] or "").strip()
        count = int(row["count"] or 0)
        if not child_code:
            continue
        top_desc = description_by_prefix.get(child_code, Counter()).most_common(1)
        children.append(
            {
                "code": child_code,
                "level": _prefix_level(len(child_code)),
                "count": count,
                "percent": _pct(count, total_relationships),
                "description": top_desc[0][0] if top_desc else "",
            }
        )

    suppliers = _cached_suppliers_for_hs([dict(row) for row in cached_supplier_rows], code)

    return {
        "code": code,
        "level": _prefix_level(len(code)),
        "hierarchy": hierarchy,
        "children": children,
        "total_relationships": total_relationships,
        "company_count": company_count,
        "origin_count": origin_count,
        "companies": companies,
        "suppliers": suppliers,
        "supplier_count": len(suppliers),
        "origins": origins,
        "descriptions": descriptions,
        "years": years,
    }


@router.get("/data/hs/{code}", response_class=HTMLResponse)
async def hs_explorer(request: Request, code: str):
    clean = _clean_hs(code)
    if len(clean) < 2:
        return templates.TemplateResponse(
            request=request,
            name="hs.html",
            context={"active": "search", "hs": None, "error": "Enter at least two HS digits."},
            status_code=400,
        )
    data = get_hs_intelligence(clean)
    return templates.TemplateResponse(
        request=request,
        name="hs.html",
        context={"active": "search", "hs": data, "error": None},
    )
