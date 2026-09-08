from __future__ import annotations

import os
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(tags=["discovery"])


def _base_url() -> str:
    return (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("SITE_URL")
        or "https://intellcluster.com"
    ).strip().rstrip("/")


def _url(path: str, *, priority: str, changefreq: str, lastmod: str = "") -> str:
    mod = f"<lastmod>{xml_escape(lastmod)}</lastmod>" if lastmod else ""
    return (
        f"<url><loc>{xml_escape(_base_url() + path)}</loc>{mod}"
        f"<priority>{priority}</priority><changefreq>{changefreq}</changefreq></url>"
    )


@router.get("/sitemaps/site.xml")
async def site_sitemap() -> Response:
    """Expose the non-directory IntellCluster product and content pages.

    The intelligence sitemap layer owns the root sitemap index. Keeping the core
    product URLs in their own child sitemap prevents the business-directory launch
    from accidentally hiding the existing advisory, synthesis, pricing and blog
    surfaces from search engines.
    """
    from shared.blog import all_tags, list_published
    from shared.seo_pages import all_compare_slugs
    from shared.templates_library import load_templates

    urls: list[str] = []
    for path, priority, freq in [
        ("/", "1.0", "weekly"),
        ("/advisory", "0.9", "weekly"),
        ("/phronesis", "0.8", "weekly"),
        ("/synthesis", "0.9", "weekly"),
        ("/pricing", "0.7", "monthly"),
        ("/templates", "0.7", "weekly"),
        ("/compare", "0.7", "weekly"),
        ("/blog", "0.8", "weekly"),
        ("/about", "0.5", "monthly"),
        ("/contact", "0.4", "monthly"),
        ("/faq", "0.5", "monthly"),
        ("/docs", "0.5", "monthly"),
        ("/privacy", "0.2", "yearly"),
        ("/terms", "0.2", "yearly"),
    ]:
        urls.append(_url(path, priority=priority, changefreq=freq))

    for slug in all_compare_slugs():
        urls.append(_url(f"/compare/{slug}", priority="0.6", changefreq="monthly"))
    for template in load_templates():
        slug = str(template.get("slug") or "").strip()
        if slug:
            urls.append(_url(f"/templates/{slug}", priority="0.6", changefreq="monthly"))
    for post in list_published():
        slug = str(post.get("slug") or "").strip()
        if not slug:
            continue
        lastmod = str(post.get("updated_date") or post.get("publish_date") or "")
        urls.append(
            _url(
                f"/blog/{slug}",
                priority="0.7",
                changefreq="monthly",
                lastmod=lastmod,
            )
        )
    for tag, _count in all_tags():
        urls.append(_url(f"/blog/tag/{tag}", priority="0.5", changefreq="weekly"))

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(urls)
        + "</urlset>"
    )
    return Response(body, media_type="application/xml; charset=utf-8")


def combined_robots_txt() -> Response:
    """Serve one robots policy for the core site and intelligence directory."""
    base = _base_url()
    body = f"""# IntellCluster — {base}
# Public marketing, editorial and /data intelligence pages are crawlable.
# Authenticated, API, upload, generated-image and search-result endpoints are not.

User-agent: *
Allow: /
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /uploads/
Disallow: /og/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: GPTBot
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /uploads/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: ClaudeBot
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /uploads/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: Claude-Web
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /uploads/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: Google-Extended
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: PerplexityBot
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: CCBot
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /uploads/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: anthropic-ai
Disallow: /api/
Disallow: /phronesis/api/
Disallow: /synthesis/api/
Disallow: /admin/
Disallow: /auth/
Disallow: /account/
Disallow: /data/suggest
Disallow: /data/search?

User-agent: SemrushBot
Disallow: /
User-agent: AhrefsBot
Disallow: /
User-agent: MJ12bot
Disallow: /
User-agent: DotBot
Disallow: /

Sitemap: {base}/sitemap.xml
"""
    return Response(body, media_type="text/plain; charset=utf-8")


def install_root_discovery(app) -> None:
    """Keep the root robots policy complete after intelligence SEO middleware mounts."""
    if getattr(app.state, "intellcluster_root_discovery_installed", False):
        return
    app.state.intellcluster_root_discovery_installed = True

    @app.middleware("http")
    async def root_discovery_policy(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/robots.txt":
            return combined_robots_txt()
        return await call_next(request)
