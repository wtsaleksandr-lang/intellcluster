from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["intelligence-ui"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


DEMO_COMPANIES = [
    {
        "slug": "maple-auto-supply-inc",
        "name": "Maple Auto Supply Inc.",
        "kind": "Importer",
        "city": "Mississauga",
        "province": "ON",
        "country": "Canada",
        "status": "Active",
        "incorporated": "2011",
        "hs_codes": ["8708.92", "8512.20"],
        "products": ["Motor vehicle exhaust parts", "Automotive lighting equipment"],
        "origins": ["China", "Taiwan"],
        "source_count": 2,
        "buyer_score": 94,
    },
    {
        "slug": "northern-industrial-components-ltd",
        "name": "Northern Industrial Components Ltd.",
        "kind": "Importer",
        "city": "Vaughan",
        "province": "ON",
        "country": "Canada",
        "status": "Active",
        "incorporated": "2004",
        "hs_codes": ["8483.40", "7318.15"],
        "products": ["Industrial gearing", "Steel fasteners"],
        "origins": ["Germany", "China", "United States"],
        "source_count": 2,
        "buyer_score": 89,
    },
    {
        "slug": "pacific-food-equipment-corp",
        "name": "Pacific Food Equipment Corp.",
        "kind": "Company",
        "city": "Burnaby",
        "province": "BC",
        "country": "Canada",
        "status": "Active",
        "incorporated": "2017",
        "hs_codes": ["8419.81"],
        "products": ["Commercial food preparation equipment"],
        "origins": ["Italy", "China"],
        "source_count": 2,
        "buyer_score": 85,
    },
]


def _filter_demo(q: str | None, province: str | None, company_type: str | None, origin: str | None, hs: str | None):
    rows = DEMO_COMPANIES
    if q:
        needle = q.casefold()
        rows = [r for r in rows if needle in (r["name"] + " " + " ".join(r["products"])).casefold()]
    if province:
        rows = [r for r in rows if r["province"].casefold() == province.casefold()]
    if company_type:
        rows = [r for r in rows if r["kind"].casefold() == company_type.casefold()]
    if origin:
        rows = [r for r in rows if any(origin.casefold() in x.casefold() for x in r["origins"])]
    if hs:
        rows = [r for r in rows if any(code.replace(".", "").startswith(hs.replace(".", "")) for code in r["hs_codes"])]
    return rows


@router.get("/data", response_class=HTMLResponse)
async def intelligence_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"active": "home"},
    )


@router.get("/data/search", response_class=HTMLResponse)
async def intelligence_search(
    request: Request,
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
    province: str | None = Query(default=None),
    origin: str | None = Query(default=None),
    hs: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="relevance"),
):
    rows = _filter_demo(q, province, type, origin, hs)
    if status:
        rows = [r for r in rows if r["status"].casefold() == status.casefold()]
    if sort == "buyer_score":
        rows = sorted(rows, key=lambda x: x["buyer_score"], reverse=True)
    elif sort == "name":
        rows = sorted(rows, key=lambda x: x["name"])
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "active": "search",
            "companies": rows,
            "q": q or "",
            "filters": {"type": type or "", "province": province or "", "origin": origin or "", "hs": hs or "", "status": status or "", "sort": sort},
            "demo_mode": True,
        },
    )


@router.get("/data/company/{slug}", response_class=HTMLResponse)
async def intelligence_company(request: Request, slug: str):
    company = next((r for r in DEMO_COMPANIES if r["slug"] == slug), DEMO_COMPANIES[0])
    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={"active": "company", "company": company, "demo_mode": True},
    )
