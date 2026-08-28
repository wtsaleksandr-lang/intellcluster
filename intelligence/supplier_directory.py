from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import distinct, func, select

from intelligence.database import connect, supplier_relationships

router = APIRouter(tags=["intelligence-supplier-directory"])
templates = Jinja2Templates(directory="intelligence/templates")


def search_suppliers(
    q: str | None = None,
    country: str | None = None,
    sort: str = "shipments",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    name_expr = func.min(supplier_relationships.c.supplier_name).label("name")
    country_expr = func.max(supplier_relationships.c.supplier_country).label("country")
    importer_count = func.count(distinct(supplier_relationships.c.importer_entity_id)).label("importer_count")
    shipments = func.coalesce(func.sum(supplier_relationships.c.total_shipments), 0).label("shipments")
    cached_at = func.max(supplier_relationships.c.source_cached_at).label("cached_at")
    stmt = select(
        supplier_relationships.c.supplier_normalized.label("normalized"),
        name_expr,
        country_expr,
        importer_count,
        shipments,
        cached_at,
    )
    term = (q or "").strip().casefold()
    if term:
        stmt = stmt.where(func.lower(supplier_relationships.c.supplier_name).like(f"%{term}%"))
    if country:
        stmt = stmt.where(func.lower(supplier_relationships.c.supplier_country) == country.strip().casefold())
    stmt = stmt.group_by(supplier_relationships.c.supplier_normalized)
    if sort == "importers":
        stmt = stmt.order_by(importer_count.desc(), shipments.desc(), name_expr.asc())
    elif sort == "name":
        stmt = stmt.order_by(name_expr.asc())
    else:
        stmt = stmt.order_by(shipments.desc(), importer_count.desc(), name_expr.asc())
    stmt = stmt.limit(max(1, min(limit, 101))).offset(max(0, offset))

    with connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [
        {
            "name": row["name"] or row["normalized"],
            "country": row["country"] or "",
            "importer_count": int(row["importer_count"] or 0),
            "shipments": int(row["shipments"] or 0),
            "cached_at": row["cached_at"] or "",
        }
        for row in rows
    ]


def supplier_countries(limit: int = 40) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            select(
                supplier_relationships.c.supplier_country.label("country"),
                func.count(distinct(supplier_relationships.c.supplier_normalized)).label("suppliers"),
            )
            .where(supplier_relationships.c.supplier_country.is_not(None))
            .group_by(supplier_relationships.c.supplier_country)
            .order_by(func.count(distinct(supplier_relationships.c.supplier_normalized)).desc())
            .limit(limit)
        ).mappings().all()
    return [
        {"country": row["country"], "suppliers": int(row["suppliers"] or 0)}
        for row in rows
        if row["country"]
    ]


@router.get("/data/suppliers", response_class=HTMLResponse)
async def supplier_directory_page(
    request: Request,
    q: str | None = Query(default=None, max_length=160),
    country: str | None = Query(default=None, max_length=180),
    sort: str = Query(default="shipments"),
    page: int = Query(default=1, ge=1),
):
    page_size = 50
    rows = search_suppliers(
        q=q,
        country=country,
        sort=sort,
        limit=page_size + 1,
        offset=(page - 1) * page_size,
    )
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    return templates.TemplateResponse(
        request=request,
        name="supplier_search.html",
        context={
            "active": "search",
            "suppliers": rows,
            "countries": supplier_countries(),
            "q": q or "",
            "country": country or "",
            "sort": sort,
            "page": page,
            "has_next": has_next,
        },
    )
