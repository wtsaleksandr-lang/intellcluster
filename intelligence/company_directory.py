from __future__ import annotations

import math
import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select

from intelligence.database import connect, entities

router = APIRouter(tags=["intelligence-company-directory"])
templates = Jinja2Templates(directory="intelligence/templates")
PAGE_SIZE = 100


def _clean_country(value: str | None) -> str:
    code = (value or "").strip().upper()
    return code if code in {"CA", "US"} else ""


def _clean_letter(value: str | None) -> str:
    text = (value or "").strip().upper()
    return text if re.fullmatch(r"[A-Z0-9]", text) else ""


@router.get("/data/companies", response_class=HTMLResponse)
async def company_directory(
    request: Request,
    page: int = Query(default=1, ge=1),
    country: str | None = Query(default=None),
    starts_with: str | None = Query(default=None),
):
    country_code = _clean_country(country)
    letter = _clean_letter(starts_with)
    filters = []
    if country_code:
        filters.append(func.upper(func.coalesce(entities.c.country, "")) == country_code)
    if letter:
        filters.append(func.upper(entities.c.canonical_name).like(f"{letter}%"))
    condition = and_(*filters) if filters else None

    with connect() as conn:
        count_stmt = select(func.count(entities.c.id))
        if condition is not None:
            count_stmt = count_stmt.where(condition)
        total = int(conn.execute(count_stmt).scalar_one() or 0)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)

        stmt = select(
            entities.c.slug,
            entities.c.canonical_name,
            entities.c.country,
            entities.c.region,
            entities.c.city,
            entities.c.corporate_status,
            entities.c.is_importer,
            entities.c.buyer_score,
            entities.c.website,
            entities.c.incorporated_year,
        )
        if condition is not None:
            stmt = stmt.where(condition)
        rows = conn.execute(
            stmt.order_by(entities.c.canonical_name.asc(), entities.c.id.asc())
            .limit(PAGE_SIZE)
            .offset((page - 1) * PAGE_SIZE)
        ).mappings().all()

    companies = [
        {
            "slug": row["slug"],
            "name": row["canonical_name"],
            "country": row["country"] or "",
            "province": row["region"] or "",
            "city": row["city"] or "",
            "status": (row["corporate_status"] or "Unknown").title(),
            "kind": "Importer" if row["is_importer"] else "Company",
            "buyer_score": int(row["buyer_score"] or 0),
            "website": row["website"] or "",
            "incorporated": row["incorporated_year"],
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request=request,
        name="companies.html",
        context={
            "active": "search",
            "companies": companies,
            "page": page,
            "pages": pages,
            "total": total,
            "country": country_code,
            "starts_with": letter,
            "page_size": PAGE_SIZE,
        },
    )
