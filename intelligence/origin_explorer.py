from __future__ import annotations

from collections import Counter
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select

from intelligence.database import connect, entities, importer_relationships

router = APIRouter(tags=["intelligence-origin"])
templates = Jinja2Templates(directory="intelligence/templates")


def _pct_rows(counter: Counter[str], limit: int = 15) -> list[dict]:
    total = sum(counter.values()) or 1
    return [
        {"label": label, "count": count, "percent": round(count * 100 / total, 1)}
        for label, count in counter.most_common(limit)
    ]


def origin_intelligence(country: str) -> dict:
    name = unquote(country).strip()
    if not name or len(name) > 180:
        return {"error": "Invalid origin country."}

    with connect() as conn:
        condition = func.lower(func.coalesce(importer_relationships.c.origin_country, "")) == name.casefold()
        rows = conn.execute(
            select(
                importer_relationships.c.entity_id,
                importer_relationships.c.activity_year,
                importer_relationships.c.hs6,
                importer_relationships.c.hs10,
                importer_relationships.c.product_description,
                entities.c.slug,
                entities.c.canonical_name,
                entities.c.city,
                entities.c.region,
                entities.c.corporate_status,
                entities.c.buyer_score,
            )
            .select_from(importer_relationships.join(entities, importer_relationships.c.entity_id == entities.c.id))
            .where(condition)
        ).mappings().all()

    if not rows:
        return {"error": f"No importer relationships found for {name}."}

    company_counter: Counter[int] = Counter()
    hs_counter: Counter[str] = Counter()
    desc_counter: Counter[str] = Counter()
    year_counter: Counter[str] = Counter()
    company_info: dict[int, dict] = {}
    hs_desc: dict[str, str] = {}

    for row in rows:
        entity_id = int(row["entity_id"])
        company_counter[entity_id] += 1
        company_info.setdefault(
            entity_id,
            {
                "slug": row["slug"],
                "name": row["canonical_name"],
                "city": row["city"] or "",
                "province": row["region"] or "",
                "status": (row["corporate_status"] or "Unknown").title(),
                "buyer_score": int(row["buyer_score"] or 0),
            },
        )
        code = str(row["hs10"] or row["hs6"] or "").strip()
        if code:
            hs_counter[code] += 1
            if row["product_description"]:
                hs_desc.setdefault(code, str(row["product_description"]))
        if row["product_description"]:
            desc_counter[str(row["product_description"])] += 1
        if row["activity_year"]:
            year_counter[str(row["activity_year"])] += 1

    total = len(rows)
    companies = []
    for entity_id, count in company_counter.most_common(50):
        item = dict(company_info[entity_id])
        item.update(relationships=count, share=round(count * 100 / total, 1))
        companies.append(item)

    hs_rows = []
    for item in _pct_rows(hs_counter, 20):
        item["description"] = hs_desc.get(item["label"], "")
        hs_rows.append(item)

    years = [
        {"year": year, "count": count}
        for year, count in sorted(year_counter.items(), key=lambda x: x[0])
    ]

    return {
        "country": name,
        "total_relationships": total,
        "company_count": len(company_counter),
        "hs_count": len(hs_counter),
        "companies": companies,
        "hs_codes": hs_rows,
        "descriptions": _pct_rows(desc_counter, 15),
        "years": years,
    }


@router.get("/data/origin/{country:path}", response_class=HTMLResponse)
async def origin_page(request: Request, country: str):
    data = origin_intelligence(country)
    return templates.TemplateResponse(
        request=request,
        name="origin.html",
        context={"active": "search", "origin": None if data.get("error") else data, "error": data.get("error")},
        status_code=404 if data.get("error") else 200,
    )
