from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, func, or_, select

from intelligence.database import connect, entities, importer_relationships
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
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.buyer_score,
            )
            .order_by(func.count(importer_relationships.c.id).desc(), entities.c.canonical_name)
            .limit(60)
        ).mappings().all()

        origin_rows = conn.execute(
            select(
                importer_relationships.c.origin_country.label("label"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .where(and_(condition, importer_relationships.c.origin_country.is_not(None)))
            .group_by(importer_relationships.c.origin_country)
            .order_by(func.count(importer_relationships.c.id).desc())
            .limit(15)
        ).mappings().all()

        description_rows = conn.execute(
            select(
                importer_relationships.c.product_description.label("label"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .where(and_(condition, importer_relationships.c.product_description.is_not(None)))
            .group_by(importer_relationships.c.product_description)
            .order_by(func.count(importer_relationships.c.id).desc())
            .limit(20)
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

    companies = []
    for row in company_rows:
        relationships = int(row["relationships"] or 0)
        companies.append(
            {
                "slug": row["slug"],
                "name": row["canonical_name"],
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

    hierarchy = []
    for size, label in ((2, "Chapter"), (4, "Heading"), (6, "HS6"), (10, "HS10")):
        if len(code) >= size:
            hierarchy.append({"code": code[:size], "label": label})

    return {
        "code": code,
        "hierarchy": hierarchy,
        "total_relationships": total_relationships,
        "company_count": company_count,
        "origin_count": origin_count,
        "companies": companies,
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
