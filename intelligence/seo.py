from __future__ import annotations

import json
import math
import os
import re
from html import escape as html_escape
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import and_, func, select

from intelligence.database import connect, entities, importer_relationships, supplier_relationships
from intelligence.repository import get_entity_by_slug

router = APIRouter(tags=["seo"])
SITEMAP_PAGE_SIZE = 20_000
SUPPLIER_SITEMAP_LIMIT = 20_000


def _base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://intellcluster.com").strip().rstrip("/")


def _xml_response(body: str) -> Response:
    return Response(body, media_type="application/xml; charset=utf-8")


def _iso_date(value: object) -> str:
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""


def _url_entry(path: str, *, changefreq: str = "weekly", lastmod: str = "") -> str:
    loc = xml_escape(_base_url() + path)
    mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return f"<url><loc>{loc}</loc>{mod}<changefreq>{changefreq}</changefreq></url>"


@router.get("/robots.txt")
async def robots_txt() -> Response:
    base = _base_url()
    body = "\n".join([
        "User-agent: *", "Allow: /data/", "Disallow: /api/", "Disallow: /admin/",
        "Disallow: /data/suggest", "Disallow: /data/search?", f"Sitemap: {base}/sitemap.xml", "",
    ])
    return Response(body, media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml")
async def sitemap_index() -> Response:
    base = _base_url()
    with connect() as conn:
        total = int(conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0)
    pages = max(1, math.ceil(total / SITEMAP_PAGE_SIZE))
    paths = ["/sitemaps/static.xml", "/sitemaps/intelligence.xml", "/sitemaps/suppliers.xml"]
    paths.extend(f"/sitemaps/companies-{page}.xml" for page in range(1, pages + 1))
    entries = [f"<sitemap><loc>{xml_escape(base + path)}</loc></sitemap>" for path in paths]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(entries) + "</sitemapindex>"
    return _xml_response(body)


@router.get("/sitemaps/static.xml")
async def sitemap_static() -> Response:
    paths = ["/data", "/data/companies", "/data/suppliers"]
    urls = "".join(_url_entry(path) for path in paths)
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    return _xml_response(body)


@router.get("/sitemaps/suppliers.xml")
async def sitemap_suppliers() -> Response:
    """Index supplier intelligence pages that have cached relationship evidence."""
    with connect() as conn:
        rows = conn.execute(
            select(
                supplier_relationships.c.supplier_name,
                func.sum(supplier_relationships.c.total_shipments).label("shipments"),
                func.max(supplier_relationships.c.updated_at).label("updated_at"),
            )
            .where(supplier_relationships.c.supplier_name.is_not(None))
            .group_by(supplier_relationships.c.supplier_normalized, supplier_relationships.c.supplier_name)
            .order_by(func.sum(supplier_relationships.c.total_shipments).desc())
            .limit(SUPPLIER_SITEMAP_LIMIT)
        ).mappings().all()
    urls = []
    seen: set[str] = set()
    for row in rows:
        name = str(row.get("supplier_name") or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        urls.append(_url_entry(f"/data/supplier/{quote(name, safe='')}", lastmod=_iso_date(row.get("updated_at"))))
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    return _xml_response(body)


@router.get("/sitemaps/intelligence.xml")
async def sitemap_intelligence() -> Response:
    """Expose high-value analytical landing pages without indexing search-result permutations."""
    with connect() as conn:
        code_expr = func.coalesce(importer_relationships.c.hs10, importer_relationships.c.hs6)
        hs_rows = conn.execute(select(code_expr.label("code"), func.count(importer_relationships.c.id).label("count")).where(code_expr.is_not(None)).group_by(code_expr).order_by(func.count(importer_relationships.c.id).desc()).limit(20_000)).mappings().all()
        origin_rows = conn.execute(select(importer_relationships.c.origin_country.label("origin"), func.count(importer_relationships.c.id).label("count")).where(importer_relationships.c.origin_country.is_not(None)).group_by(importer_relationships.c.origin_country).order_by(func.count(importer_relationships.c.id).desc()).limit(1_000)).mappings().all()
        province_rows = conn.execute(select(entities.c.region.label("province"), func.count(entities.c.id).label("count")).where(entities.c.region.is_not(None)).group_by(entities.c.region).order_by(func.count(entities.c.id).desc()).limit(500)).mappings().all()
        city_rows = conn.execute(select(entities.c.region.label("province"), entities.c.city.label("city"), func.count(entities.c.id).label("count")).where(and_(entities.c.region.is_not(None), entities.c.city.is_not(None))).group_by(entities.c.region, entities.c.city).order_by(func.count(entities.c.id).desc()).limit(10_000)).mappings().all()
    urls: list[str] = []; seen_hs: set[str] = set()
    for row in hs_rows:
        raw = "".join(ch for ch in str(row.get("code") or "") if ch.isdigit())[:10]
        if len(raw) < 2: continue
        for size in (2, 4, 6, 10):
            if len(raw) < size: continue
            code = raw[:size]
            if code in seen_hs: continue
            seen_hs.add(code); urls.append(_url_entry(f"/data/hs/{code}"))
    for row in origin_rows:
        origin = str(row.get("origin") or "").strip()
        if origin: urls.append(_url_entry(f"/data/origin/{quote(origin, safe='')}"))
    for row in province_rows:
        province = str(row.get("province") or "").strip()
        if province: urls.append(_url_entry(f"/data/location/{quote(province, safe='')}"))
    for row in city_rows:
        province = str(row.get("province") or "").strip(); city = str(row.get("city") or "").strip()
        if province and city: urls.append(_url_entry(f"/data/location/{quote(province, safe='')}/{quote(city, safe='')}"))
    urls = urls[:45_000]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    return _xml_response(body)


@router.get("/sitemaps/companies-{page}.xml")
async def sitemap_companies(page: int) -> Response:
    page = max(1, page); offset = (page - 1) * SITEMAP_PAGE_SIZE
    with connect() as conn:
        rows = conn.execute(select(entities.c.slug, entities.c.updated_at).where(entities.c.slug.is_not(None)).order_by(entities.c.id.asc()).limit(SITEMAP_PAGE_SIZE).offset(offset)).mappings().all()
    urls = [_url_entry(f"/data/company/{quote(str(row['slug']), safe='-')}", lastmod=_iso_date(row.get("updated_at"))) for row in rows]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    return _xml_response(body)


def _canonical_path(path: str) -> str:
    return path[:-1] if path.endswith("/") and path != "/" else path


def _organization_schema(company: dict, canonical: str) -> dict[str, object]:
    schema: dict[str, object] = {"@context":"https://schema.org","@type":"Organization","name":company.get("name") or company.get("canonical_name") or "Company","url":canonical}
    address_parts = {"streetAddress":company.get("address"),"addressLocality":company.get("city"),"addressRegion":company.get("province") or company.get("region"),"postalCode":company.get("postal_code"),"addressCountry":company.get("country")}
    if any(address_parts.values()): schema["address"] = {"@type":"PostalAddress", **{k:v for k,v in address_parts.items() if v}}
    website = str(company.get("website") or "").strip()
    if website:
        if not website.startswith(("http://","https://")): website = "https://" + website
        schema["sameAs"] = [website]
    if company.get("corporation_number"): schema["identifier"] = str(company["corporation_number"])
    return schema


def _breadcrumb_schema(path: str, *, company_name: str | None = None) -> dict[str, object] | None:
    base = _base_url(); path = _canonical_path(path); crumbs: list[tuple[str,str]] = [("IntellCluster Data","/data")]
    if path == "/data/companies": crumbs.append(("Companies",path))
    elif path == "/data/suppliers": crumbs.append(("Suppliers",path))
    else:
        match = re.fullmatch(r"/data/company/([^/]+)",path)
        if match: crumbs.extend([("Companies","/data/companies"),(company_name or unquote(match.group(1)).replace("-"," ").title(),path)])
        else:
            match = re.fullmatch(r"/data/supplier/(.+)",path)
            if match: crumbs.extend([("Suppliers","/data/suppliers"),(unquote(match.group(1)),path)])
            else:
                match = re.fullmatch(r"/data/hs/(\d{2,10})",path)
                if match: crumbs.extend([("HS Code Intelligence","/data"),(f"HS {match.group(1)}",path)])
                else:
                    match = re.fullmatch(r"/data/origin/(.+)",path)
                    if match: crumbs.extend([("Origin Markets","/data"),(unquote(match.group(1)),path)])
                    else:
                        match = re.fullmatch(r"/data/location/([^/]+)(?:/(.+))?",path)
                        if not match: return None
                        province = unquote(match.group(1)); city = unquote(match.group(2)) if match.group(2) else ""
                        crumbs.extend([("Locations","/data"),(province,f"/data/location/{quote(province,safe='')}")])
                        if city: crumbs.append((city,path))
    return {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[{"@type":"ListItem","position":index,"name":name,"item":base+item_path} for index,(name,item_path) in enumerate(crumbs,start=1)]}


def _rendered_meta(text: str) -> tuple[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>",text,flags=re.IGNORECASE|re.DOTALL)
    desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',text,flags=re.IGNORECASE|re.DOTALL)
    title = re.sub(r"\s+"," ",title_match.group(1)).strip() if title_match else "IntellCluster Data"
    description = re.sub(r"\s+"," ",desc_match.group(1)).strip() if desc_match else "Public business intelligence and company data."
    return title,description


def install_seo_middleware(app) -> None:
    if getattr(app.state,"intellcluster_seo_installed",False): return
    app.state.intellcluster_seo_installed = True
    @app.middleware("http")
    async def intellcluster_seo_metadata(request: Request, call_next):
        path = request.url.path
        if path == "/robots.txt": return await robots_txt()
        if path == "/sitemap.xml": return await sitemap_index()
        response = await call_next(request); content_type = response.headers.get("content-type","")
        if "text/html" not in content_type or not path.startswith("/data"): return response
        body=b""
        async for chunk in response.body_iterator: body += chunk
        text=body.decode("utf-8",errors="replace"); base=_base_url(); clean_path=_canonical_path(path); canonical=base+clean_path
        noindex=response.status_code>=400 or path.startswith("/data/search") or path.startswith("/data/suggest") or (clean_path in {"/data/companies","/data/suppliers"} and bool(request.query_params))
        robots="noindex,follow" if noindex else "index,follow,max-image-preview:large,max-snippet:-1"; title,description=_rendered_meta(text)
        head_bits=[f'<link rel="canonical" href="{html_escape(canonical,quote=True)}">',f'<meta name="robots" content="{robots}">',f'<meta property="og:url" content="{html_escape(canonical,quote=True)}">','<meta property="og:type" content="website">',f'<meta property="og:title" content="{html_escape(title,quote=True)}">',f'<meta property="og:description" content="{html_escape(description,quote=True)}">','<meta name="twitter:card" content="summary">',f'<meta name="twitter:title" content="{html_escape(title,quote=True)}">',f'<meta name="twitter:description" content="{html_escape(description,quote=True)}">']
        company_name=None; company_match=re.fullmatch(r"/data/company/([^/]+)",clean_path)
        if company_match and response.status_code==200:
            try:
                with connect() as conn: company=get_entity_by_slug(conn,company_match.group(1))
                if company:
                    company_name=str(company.get("name") or company.get("canonical_name") or "Company"); schema=json.dumps(_organization_schema(company,canonical),ensure_ascii=False,separators=(",",":")); head_bits.append(f'<script type="application/ld+json">{schema.replace("</","<\\/")}</script>')
            except Exception: pass
        if not noindex and response.status_code==200:
            breadcrumb=_breadcrumb_schema(clean_path,company_name=company_name)
            if breadcrumb:
                schema=json.dumps(breadcrumb,ensure_ascii=False,separators=(",",":")); head_bits.append(f'<script type="application/ld+json">{schema.replace("</","<\\/")}</script>')
        if "</head>" in text: text=text.replace("</head>","\n".join(head_bits)+"\n</head>",1)
        headers=dict(response.headers); headers.pop("content-length",None)
        return Response(text,status_code=response.status_code,headers=headers,media_type="text/html")
