from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, desc, func, select

from intelligence.database import connect, entities, importer_relationships

router = APIRouter(tags=["intelligence-location"])
templates = Jinja2Templates(directory="intelligence/templates")


def _clean(value: str, max_len: int) -> str:
    return unquote(value).strip()[:max_len]


def location_intelligence(province: str, city: str | None = None) -> dict:
    province_name = _clean(province, 100).upper()
    city_name = _clean(city, 180) if city else ""
    if not province_name:
        return {"error": "Invalid location."}

    conditions = [func.upper(func.coalesce(entities.c.region, "")) == province_name]
    if city_name:
        conditions.append(func.lower(func.coalesce(entities.c.city, "")) == city_name.casefold())
    entity_condition = and_(*conditions)

    with connect() as conn:
        totals = conn.execute(
            select(
                func.count(entities.c.id).label("companies"),
                func.sum(func.cast(entities.c.is_importer, type_=entities.c.id.type)).label("importers"),
                func.sum(
                    func.cast(func.lower(func.coalesce(entities.c.corporate_status, "")) == "active", type_=entities.c.id.type)
                ).label("active"),
            ).where(entity_condition)
        ).mappings().one()
        company_count = int(totals["companies"] or 0)
        if not company_count:
            label = f"{city_name}, {province_name}" if city_name else province_name
            return {"error": f"No companies found for {label}."}

        top_companies = conn.execute(
            select(
                entities.c.id,
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.is_importer,
                entities.c.buyer_score,
                func.count(importer_relationships.c.id).label("relationships"),
            )
            .select_from(entities.outerjoin(importer_relationships, importer_relationships.c.entity_id == entities.c.id))
            .where(entity_condition)
            .group_by(
                entities.c.id,
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.is_importer,
                entities.c.buyer_score,
            )
            .order_by(desc("relationships"), entities.c.buyer_score.desc().nullslast(), entities.c.canonical_name)
            .limit(60)
        ).mappings().all()

        rel_base = importer_relationships.join(entities, importer_relationships.c.entity_id == entities.c.id)
        relationship_count = int(
            conn.execute(
                select(func.count(importer_relationships.c.id)).select_from(rel_base).where(entity_condition)
            ).scalar_one()
            or 0
        )

        hs_rows = conn.execute(
            select(
                func.coalesce(importer_relationships.c.hs10, importer_relationships.c.hs6).label("code"),
                func.count(importer_relationships.c.id).label("count"),
                func.min(importer_relationships.c.product_description).label("description"),
            )
            .select_from(rel_base)
            .where(and_(entity_condition, func.coalesce(importer_relationships.c.hs10, importer_relationships.c.hs6).is_not(None)))
            .group_by("code")
            .order_by(desc("count"))
            .limit(20)
        ).mappings().all()

        origin_rows = conn.execute(
            select(
                importer_relationships.c.origin_country.label("country"),
                func.count(importer_relationships.c.id).label("count"),
            )
            .select_from(rel_base)
            .where(and_(entity_condition, importer_relationships.c.origin_country.is_not(None)))
            .group_by(importer_relationships.c.origin_country)
            .order_by(desc("count"))
            .limit(15)
        ).mappings().all()

        cities = []
        if not city_name:
            city_rows = conn.execute(
                select(
                    entities.c.city.label("city"),
                    func.count(entities.c.id).label("count"),
                    func.sum(func.cast(entities.c.is_importer, type_=entities.c.id.type)).label("importers"),
                )
                .where(and_(entity_condition, entities.c.city.is_not(None)))
                .group_by(entities.c.city)
                .order_by(desc("count"))
                .limit(25)
            ).mappings().all()
            cities = [
                {"city": row["city"], "count": int(row["count"] or 0), "importers": int(row["importers"] or 0)}
                for row in city_rows
                if row["city"]
            ]

        years = conn.execute(
            select(entities.c.incorporated_year.label("year"), func.count(entities.c.id).label("count"))
            .where(and_(entity_condition, entities.c.incorporated_year.is_not(None)))
            .group_by(entities.c.incorporated_year)
            .order_by(entities.c.incorporated_year)
        ).mappings().all()

    importers = int(totals["importers"] or 0)
    active = int(totals["active"] or 0)
    denom = relationship_count or 1
    companies = [
        {
            "slug": row["slug"],
            "name": row["canonical_name"],
            "city": row["city"] or "",
            "province": row["region"] or "",
            "status": (row["corporate_status"] or "Unknown").title(),
            "kind": "Importer" if row["is_importer"] else "Company",
            "buyer_score": int(row["buyer_score"] or 0),
            "relationships": int(row["relationships"] or 0),
        }
        for row in top_companies
    ]
    hs_codes = [
        {
            "code": str(row["code"] or ""),
            "count": int(row["count"] or 0),
            "share": round(int(row["count"] or 0) * 100 / denom, 1),
            "description": row["description"] or "",
        }
        for row in hs_rows
    ]
    origins = [
        {
            "country": row["country"],
            "count": int(row["count"] or 0),
            "share": round(int(row["count"] or 0) * 100 / denom, 1),
        }
        for row in origin_rows
        if row["country"]
    ]
    return {
        "province": province_name,
        "city": city_name,
        "label": f"{city_name}, {province_name}" if city_name else province_name,
        "company_count": company_count,
        "importer_count": importers,
        "importer_share": round(importers * 100 / company_count, 1),
        "active_count": active,
        "active_share": round(active * 100 / company_count, 1),
        "relationship_count": relationship_count,
        "companies": companies,
        "cities": cities,
        "hs_codes": hs_codes,
        "origins": origins,
        "years": [{"year": int(row["year"]), "count": int(row["count"] or 0)} for row in years],
    }


@router.get("/data/location/{province}", response_class=HTMLResponse)
async def province_page(request: Request, province: str):
    data = location_intelligence(province)
    return templates.TemplateResponse(
        request=request,
        name="location.html",
        context={"active": "search", "location": None if data.get("error") else data, "error": data.get("error")},
        status_code=404 if data.get("error") else 200,
    )


@router.get("/data/location/{province}/{city:path}", response_class=HTMLResponse)
async def city_page(request: Request, province: str, city: str):
    data = location_intelligence(province, city)
    return templates.TemplateResponse(
        request=request,
        name="location.html",
        context={"active": "search", "location": None if data.get("error") else data, "error": data.get("error")},
        status_code=404 if data.get("error") else 200,
    )
