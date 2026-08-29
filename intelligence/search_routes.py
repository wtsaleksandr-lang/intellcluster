from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from intelligence.database import connect
from intelligence.repository import search_entities

router = APIRouter(tags=["intelligence-search-pages"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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


@router.get("/data/search", response_class=HTMLResponse)
async def intelligence_search_page(
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
    """Render real directory results only; no demo company is injected on zero results."""
    company_slug = _referer_company_slug(request)
    if company_slug and _looks_like_bol(q):
        return RedirectResponse(
            url=f"/data/company/{company_slug}/bol/{q}",
            status_code=302,
        )

    normalized_country = (country or "").strip().upper()
    if normalized_country not in {"CA", "US"}:
        normalized_country = ""
    has_website = True if website == "yes" else False if website == "no" else None
    page_size = 50
    with connect() as conn:
        rows = search_entities(
            conn,
            q=q,
            country=normalized_country or None,
            company_type=type,
            province=province,
            city=city,
            origin=origin,
            hs=hs,
            status=status,
            incorporated_from=incorporated_from,
            incorporated_to=incorporated_to,
            has_website=has_website,
            sort=sort,
            limit=page_size + 1,
            offset=(page - 1) * page_size,
        )
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    filters = {
        "country": normalized_country,
        "type": type or "",
        "province": province or "",
        "city": city or "",
        "origin": origin or "",
        "hs": hs or "",
        "status": status or "",
        "incorporated_from": incorporated_from or "",
        "incorporated_to": incorporated_to or "",
        "website": website or "",
        "sort": sort,
    }
    response = templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "active": "search",
            "companies": rows,
            "q": q or "",
            "filters": filters,
            "demo_mode": False,
            "page": page,
            "has_next": has_next,
        },
    )
    if page == 1 and not rows:
        response.headers["X-IntellCluster-Empty-Search"] = "1"
    return response
