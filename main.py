"""
IntellCluster — Unified FastAPI application.

Mounts two tools:
  /                 → Homepage (picks a tool)
  /phronesis        → Phronesis (decision intelligence)
  /synthesis        → Synthesis (multi-model research)
"""

import asyncio
import json
import os
import sys
import uuid as _uuid
from pathlib import Path

# Ensure we can import from the project root
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, UploadFile, File, Form as FastAPIForm
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import settings

# Phronesis imports
from phronesis.engine.types import DecisionInput, AnalysisSettings
from phronesis.engine.pipeline import run_decision_pipeline
from phronesis.engine.extractor import extract_decision, suggest_chips
from shared.tracking.history import get_recent_decisions, get_decision_by_run_id
from shared.admin import admin_router
from shared.auth import user_router, current_user as _current_user

# Synthesis imports
from synthesis.orchestrator.pipeline import run_pipeline as run_synthesis_pipeline

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="IntellCluster", version="0.1.0")

# Rate limiting middleware
from shared.rate_limit import rate_limit_middleware
app.middleware("http")(rate_limit_middleware)


# Attach signed-in user to request.state so every template can render nav state
@app.middleware("http")
async def _attach_user(request: Request, call_next):
    try:
        request.state.user = _current_user(request)
    except Exception:
        request.state.user = None
    return await call_next(request)


# ─── Branded 500 handler ───

from fastapi import Request as _FastAPIRequest
from starlette.exceptions import HTTPException as _StarletteHTTPException


@app.exception_handler(500)
async def server_error_handler(request: _FastAPIRequest, exc: Exception):
    """Render a branded 500 page instead of the default FastAPI trace."""
    import traceback
    import uuid as _uuid_err
    ref = _uuid_err.uuid4().hex[:8]
    print(f"[500] ref={ref} path={request.url.path}\n{''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}")
    try:
        return templates.TemplateResponse(
            request, "500.html", {"request_id": ref}, status_code=500,
        )
    except Exception:
        return HTMLResponse(
            content=f"<h1>500</h1><p>Something broke (ref: {ref}).</p><p><a href='/'>Home</a></p>",
            status_code=500,
        )


@app.exception_handler(_StarletteHTTPException)
async def http_exception_handler(request: _FastAPIRequest, exc: _StarletteHTTPException):
    # 404 gets a branded template; pass everything else through as JSON.
    if exc.status_code == 404:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

# Analytics
from shared.analytics import log_event, get_plausible_domain

# Mount admin routes (/admin, /admin/login, /admin/logout)
app.include_router(admin_router)
# Mount user auth routes (/login, /auth/*, /account)
app.include_router(user_router)

# Templates — search multiple directories (Jinja2 searches in order)
templates = Jinja2Templates(directory=[
    "shared/templates",
    "phronesis/templates",
    "synthesis/templates",
    "homepage",
])

# Site-wide Jinja globals (available on every render without per-route wiring)
templates.env.globals["plausible_domain"] = os.environ.get("PLAUSIBLE_DOMAIN") or ""
templates.env.globals["site_url"] = os.environ.get("SITE_URL", "https://intellcluster.com")


# ═══════════════════════════════════════════════════════
# HOMEPAGE
# ═══════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse(request, "index.html")


# ─── SEO: robots.txt + sitemap.xml at root ───

@app.get("/robots.txt", include_in_schema=False)
async def robots():
    from fastapi.responses import FileResponse
    return FileResponse("shared/static/robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    """Dynamic sitemap — static pages + /compare/{slug} + /templates/{slug} + /blog/{slug}."""
    from fastapi.responses import Response
    from shared.seo_pages import all_compare_slugs
    from shared.templates_library import load_templates
    from shared.blog import list_published as _list_blog

    base = os.environ.get("SITE_URL", "https://intellcluster.com").rstrip("/")
    static_urls = [
        ("/", "1.0", "weekly"),
        ("/phronesis", "0.9", "weekly"),
        ("/synthesis", "0.9", "weekly"),
        ("/pricing", "0.7", "monthly"),
        ("/templates", "0.8", "weekly"),
        ("/compare", "0.8", "weekly"),
        ("/blog", "0.8", "weekly"),
        ("/about", "0.6", "monthly"),
        ("/contact", "0.5", "monthly"),
        ("/faq", "0.6", "monthly"),
        ("/privacy", "0.3", "yearly"),
        ("/terms", "0.3", "yearly"),
    ]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for path, priority, freq in static_urls:
        lines.append(f'  <url><loc>{base}{path}</loc><priority>{priority}</priority><changefreq>{freq}</changefreq></url>')
    for slug in all_compare_slugs():
        lines.append(f'  <url><loc>{base}/compare/{slug}</loc><priority>0.6</priority><changefreq>monthly</changefreq></url>')
    for t in load_templates():
        slug = t.get("slug", "")
        if slug:
            lines.append(f'  <url><loc>{base}/templates/{slug}</loc><priority>0.65</priority><changefreq>monthly</changefreq></url>')
    for p in _list_blog():
        lastmod = (p.get("updated_date") or p.get("publish_date"))
        lastmod_str = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        lines.append(f'  <url><loc>{base}/blog/{p["slug"]}</loc>{lastmod_str}<priority>0.7</priority><changefreq>monthly</changefreq></url>')
    lines.append('</urlset>')
    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("shared/static/favicon.svg", media_type="image/svg+xml")


@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    from shared.pricing import PLANS, CREDIT_PACKS, stripe_configured
    return templates.TemplateResponse(request, "pricing.html", {
        "plans": PLANS,
        "credit_packs": CREDIT_PACKS,
        "stripe_live": stripe_configured(),
    })


# ─── Stripe checkout ───

@app.post("/pricing/checkout")
async def pricing_checkout(request: Request):
    """Start a Stripe Checkout session. Body: {plan: 'starter'|'pro', billing: 'monthly'|'annual'}
       OR: {pack: 'pack_5'|'pack_15'|'pack_30'}
       Falls back to waitlist if Stripe not configured."""
    from shared.stripe_integration import create_subscription_checkout, create_credit_pack_checkout
    from shared.pricing import stripe_configured

    body = await request.json()
    email = body.get("email")
    base = str(request.base_url).rstrip("/")
    success_url = f"{base}/pricing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{base}/pricing"

    if "plan" in body:
        plan_id = body["plan"]
        billing = body.get("billing", "monthly")
        if not stripe_configured():
            return JSONResponse({"error": "Stripe not configured", "fallback_url": f"/pricing/upgrade?plan={plan_id}"}, status_code=503)
        url = create_subscription_checkout(plan_id, billing, email, success_url, cancel_url)
        if not url:
            return JSONResponse({"error": f"Could not create checkout for {plan_id}"}, status_code=400)
        return {"url": url}

    if "pack" in body:
        pack_id = body["pack"]
        if not stripe_configured():
            return JSONResponse({"error": "Stripe not configured", "fallback_url": "/pricing/upgrade?plan=pro"}, status_code=503)
        url = create_credit_pack_checkout(pack_id, email, success_url, cancel_url)
        if not url:
            return JSONResponse({"error": f"Could not create checkout for {pack_id}"}, status_code=400)
        return {"url": url}

    return JSONResponse({"error": "Missing plan or pack"}, status_code=400)


@app.get("/pricing/success", response_class=HTMLResponse)
async def pricing_success(request: Request, session_id: str | None = None):
    return templates.TemplateResponse(request, "checkout_success.html", {"session_id": session_id})


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    from shared.stripe_integration import verify_webhook_signature, handle_webhook_event
    sig_header = request.headers.get("stripe-signature", "")
    payload = await request.body()
    event = verify_webhook_signature(payload, sig_header)
    if not event:
        return JSONResponse({"error": "Invalid signature"}, status_code=400)
    handle_webhook_event(event)
    return {"received": True}


@app.get("/og/compare/{slug}.svg", include_in_schema=False)
async def og_compare(slug: str):
    """Per-compare-page OG image (1200x630 SVG)."""
    from fastapi.responses import Response
    from shared.og import compare_og_svg, homepage_og_svg
    from shared.seo_pages import get_compare_page

    page = get_compare_page(slug)
    if not page:
        svg = homepage_og_svg()
    else:
        svg = compare_og_svg(
            title=page.get("title", ""),
            options=page.get("options", []),
            category=page.get("category", ""),
        )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/og/homepage.svg", include_in_schema=False)
async def og_homepage():
    from fastapi.responses import Response
    from shared.og import homepage_og_svg
    return Response(
        content=homepage_og_svg(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/og/homepage.png", include_in_schema=False)
async def og_homepage_png():
    from fastapi.responses import Response
    from shared.exporters.og_png import homepage_og_png
    return Response(
        content=homepage_og_png(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/og/compare/{slug}.png", include_in_schema=False)
async def og_compare_png(slug: str):
    from fastapi.responses import Response
    from shared.exporters.og_png import compare_og_png, homepage_og_png
    from shared.seo_pages import get_compare_page
    page = get_compare_page(slug)
    if not page:
        png = homepage_og_png()
    else:
        png = compare_og_png(
            title=page.get("title", ""),
            options=page.get("options", []),
            category=page.get("category", ""),
        )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/og/phronesis/{run_id}.png", include_in_schema=False)
async def og_phronesis_decision_png(run_id: str):
    """Per-decision OG card — unique social preview for every shared decision."""
    from fastapi.responses import Response
    from shared.exporters.og_png import decision_og_png
    decision = get_decision_by_run_id(run_id)
    if not decision:
        return JSONResponse(status_code=404, content={"error": "Decision not found"})
    png = decision_og_png(
        question=decision.get("question", ""),
        winner=decision.get("winner", ""),
        confidence=int(decision.get("confidence_score") or 0) or None,
        agree=bool(decision.get("judges_agree")),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/phronesis/result/{run_id}.pdf", include_in_schema=False)
async def phronesis_decision_pdf(run_id: str):
    """Download a Phronesis decision as a branded PDF."""
    from fastapi.responses import Response
    from shared.exporters.decision_pdf import build_decision_pdf
    decision = get_decision_by_run_id(run_id)
    if not decision:
        return JSONResponse(status_code=404, content={"error": "Decision not found"})
    pdf = build_decision_pdf(decision)
    filename = f"phronesis-{run_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@app.get("/compare", response_class=HTMLResponse)
async def compare_index(request: Request):
    from shared.seo_pages import load_compare_pages, page_slug
    pages = load_compare_pages()
    for p in pages:
        p["slug"] = page_slug(p.get("options", []))
    return templates.TemplateResponse(request, "compare_index.html", {"pages": pages})


@app.get("/compare/{slug}", response_class=HTMLResponse)
async def compare_page_view(request: Request, slug: str):
    from shared.seo_pages import get_compare_page
    page = get_compare_page(slug)
    if not page:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "compare.html", {"page": page, "preset_slug": slug})


@app.get("/api/compare-preset/{slug}")
async def compare_preset(slug: str):
    from shared.seo_pages import get_compare_page
    page = get_compare_page(slug)
    if not page:
        return JSONResponse(status_code=404, content={"error": "Preset not found"})
    return {"question": page.get("question"), "options": page.get("options", []), "criteria": page.get("criteria", [])}


@app.get("/templates", response_class=HTMLResponse)
async def templates_index(request: Request):
    """Decision templates library — pre-filled starter frameworks."""
    from shared.templates_library import templates_by_category
    return templates.TemplateResponse(request, "templates_index.html", {
        "by_category": templates_by_category(),
    })


@app.get("/templates/{slug}", response_class=HTMLResponse)
async def template_detail(request: Request, slug: str):
    """Per-template landing page — indexable, shareable, one-click launch into Phronesis."""
    from shared.templates_library import get_template
    t = get_template(slug)
    if not t:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "template_detail.html", {"template": t})


@app.get("/og/template/{slug}.png", include_in_schema=False)
async def og_template_png(slug: str):
    """Per-template OG card using the compare-style PNG renderer."""
    from fastapi.responses import Response
    from shared.exporters.og_png import compare_og_png, homepage_og_png
    from shared.templates_library import get_template
    t = get_template(slug)
    if not t:
        png = homepage_og_png()
    else:
        png = compare_og_png(
            title=t.get("title", ""),
            options=t.get("options", []),
            category=t.get("category", ""),
        )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/template/{slug}")
async def template_lookup(slug: str):
    from shared.templates_library import get_template
    t = get_template(slug)
    if not t:
        return JSONResponse(status_code=404, content={"error": "Template not found"})
    return {
        "question": t.get("description", t.get("title", "")),
        "options": t.get("options", []),
        "criteria": t.get("criteria", []),
    }


@app.get("/api/templates")
async def templates_list():
    """Public API: list all decision templates (for third-party integration)."""
    from shared.templates_library import load_templates
    return {"templates": load_templates()}


# ─── About / Contact / FAQ ───

@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html")


@app.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request):
    return templates.TemplateResponse(request, "faq.html")


@app.get("/contact", response_class=HTMLResponse)
async def contact_get(request: Request):
    return templates.TemplateResponse(request, "contact.html", {"submitted": False})


@app.post("/contact", response_class=HTMLResponse)
async def contact_post(
    request: Request,
    name: str = FastAPIForm(...),
    email: str = FastAPIForm(...),
    reason: str = FastAPIForm(...),
    message: str = FastAPIForm(...),
    website: str = FastAPIForm(""),  # honeypot
):
    # Silent drop for bots that fill the hidden honeypot field.
    if website.strip():
        log_event("contact_honeypot_trip", {"reason": reason})
        return templates.TemplateResponse(
            request, "contact.html",
            {"submitted": True, "email": email.strip().lower()[:200]},
        )

    from shared.tracking.contact import record_contact
    from shared.email import admin_contact_notification

    entry = record_contact(
        name=name, email=email, reason=reason, message=message,
        meta={"ip": (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                     or (request.client.host if request.client else "unknown"))[:64]},
    )
    try:
        admin_contact_notification(entry["name"], entry["email"], entry["reason"], entry["message"])
    except Exception as e:
        print(f"[contact] admin notify failed: {e}")
    log_event("contact_submission", {"reason": reason, "email_hash": hash(entry["email"]) % (10**10)})

    return templates.TemplateResponse(
        request, "contact.html",
        {"submitted": True, "email": entry["email"]},
    )


# ─── Blog / Field Notes ───

@app.get("/blog", response_class=HTMLResponse)
async def blog_index(request: Request):
    from shared.blog import list_published
    return templates.TemplateResponse(request, "blog/index.html", {
        "posts": list_published(),
    })


@app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_detail(request: Request, slug: str):
    from shared.blog import get_post, list_published
    post = get_post(slug)
    if not post:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    # Related — prefer same tool_focus, then newest.
    related = [
        p for p in list_published()
        if p["slug"] != slug and (
            p.get("tool_focus") == post.get("tool_focus")
            or set(p.get("tags", [])) & set(post.get("tags", []))
        )
    ][:3]
    return templates.TemplateResponse(request, "blog/detail.html", {
        "post": post,
        "related": related,
    })


@app.get("/blog.xml", include_in_schema=False)
async def blog_rss():
    """RSS 2.0 feed of published field notes."""
    from fastapi.responses import Response
    from shared.blog import list_published
    from email.utils import format_datetime
    from datetime import datetime, time, timezone

    base = os.environ.get("SITE_URL", "https://intellcluster.com").rstrip("/")
    posts = list_published()
    last_build = posts[0]["publish_date"] if posts else None

    def _rss_date(d):
        if not d:
            return ""
        return format_datetime(datetime.combine(d, time(12, 0), tzinfo=timezone.utc))

    def _esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    items = []
    for p in posts:
        items.append(f"""    <item>
      <title>{_esc(p['title'])}</title>
      <link>{base}/blog/{p['slug']}</link>
      <guid isPermaLink="true">{base}/blog/{p['slug']}</guid>
      <pubDate>{_rss_date(p['publish_date'])}</pubDate>
      <description>{_esc(p['meta_desc'])}</description>
      {''.join(f'<category>{_esc(t)}</category>' for t in p.get('tags', []))}
    </item>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>IntellCluster Field Notes</title>
    <link>{base}/blog</link>
    <atom:link href="{base}/blog.xml" rel="self" type="application/rss+xml"/>
    <description>Essays on decision science and multi-model AI research from IntellCluster.</description>
    <language>en-us</language>
    <lastBuildDate>{_rss_date(last_build)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>"""
    return Response(content=xml, media_type="application/rss+xml")


@app.get("/og/blog/{slug}.png", include_in_schema=False)
async def og_blog_png(slug: str):
    """Per-article OG hero card."""
    from fastapi.responses import Response
    from shared.blog import get_post
    from shared.exporters.blog_og import blog_hero_og_png
    from shared.exporters.og_png import homepage_og_png
    post = get_post(slug)
    if not post:
        return Response(content=homepage_og_png(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})
    png = blog_hero_og_png(
        title=post["title"],
        tool_focus=post.get("tool_focus", "both"),
        hero_keywords=post.get("hero_keywords", []),
        hero_tag=post.get("hero_tag", "FIELD NOTE"),
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """User-facing history — reads from localStorage, no server-side user data."""
    return templates.TemplateResponse(request, "history.html")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(request, "terms.html")


@app.get("/pricing/upgrade", response_class=HTMLResponse)
async def upgrade_form(request: Request, plan: str = "pro"):
    if plan not in ("pro", "team"):
        plan = "pro"
    return templates.TemplateResponse(request, "upgrade.html", {"plan": plan, "submitted": False})


@app.post("/pricing/upgrade", response_class=HTMLResponse)
async def upgrade_submit(
    request: Request,
    plan: str = FastAPIForm(...),
    email: str = FastAPIForm(...),
):
    if plan not in ("pro", "team"):
        plan = "pro"
    # Save to waitlist (simple JSONL append)
    from pathlib import Path as _Path
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    wl_dir = _Path("history"); wl_dir.mkdir(exist_ok=True)
    wl_file = wl_dir / "waitlist.jsonl"
    clean_email = email.strip().lower()[:200]
    with open(wl_file, "a", encoding="utf-8") as f:
        f.write(_json.dumps({
            "timestamp": _dt.now(_tz.utc).isoformat(),
            "plan": plan,
            "email": clean_email,
        }) + "\n")
    # Send confirmation email (no-op in dev mode if SMTP unset)
    from shared.email import waitlist_confirmation
    try:
        waitlist_confirmation(clean_email, plan)
    except Exception:
        pass
    log_event("waitlist_signup", {"plan": plan, "email_hash": hash(clean_email) % (10**10)})
    return templates.TemplateResponse(request, "upgrade.html", {"plan": plan, "submitted": True})


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "tools": ["phronesis", "synthesis"],
        "providers": settings.available_judges(),
        "has_api_keys": settings.has_any_api_key(),
    }


# ─── Intent routing (cross-tool handoff detection) ───

from shared.intent_router import classify_intent

class IntentRequest(BaseModel):
    text: str = Field(min_length=8, max_length=4000)
    current_tool: str | None = Field(default=None, pattern="^(phronesis|synthesis)$")


@app.post("/api/intent")
async def intent(req: IntentRequest):
    """Classify user input. Returns which tool best fits + handoff recommendation."""
    result = await classify_intent(req.text, current_tool=req.current_tool)
    return result


# ═══════════════════════════════════════════════════════
# PHRONESIS — Decision Intelligence
# ═══════════════════════════════════════════════════════

class CriterionModel(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    weight: int = Field(ge=1, le=10, default=5)


class AnalysisSettingsModel(BaseModel):
    depth: str = Field(default="standard", pattern="^(quick|standard|deep)$")
    focus: str = Field(default="balanced", pattern="^(balanced|risks|practical)$")
    length: str = Field(default="standard", pattern="^(concise|standard|detailed)$")
    web_search: bool = False


class DecisionRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    options: list[str] = Field(min_length=2, max_length=10)
    criteria: list[CriterionModel] = Field(min_length=1, max_length=10)
    settings: AnalysisSettingsModel = Field(default_factory=AnalysisSettingsModel)
    attachments: list[str] = Field(default_factory=list)


@app.get("/phronesis", response_class=HTMLResponse)
async def phronesis_home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"tool": "phronesis"})


@app.get("/phronesis/result/{run_id}", response_class=HTMLResponse)
async def phronesis_result(request: Request, run_id: str):
    decision = get_decision_by_run_id(run_id)
    if not decision:
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return templates.TemplateResponse(request, "result.html", {"result": decision, "tool": "phronesis"})


@app.post("/phronesis/api/decide")
async def phronesis_decide(req_body: DecisionRequest, req: Request):
    if not settings.has_any_api_key():
        return JSONResponse(status_code=503, content={"error": "No AI judge API keys configured."})

    input_data = DecisionInput(
        question=req_body.question,
        options=req_body.options,
        criteria=[{"name": c.name, "weight": c.weight} for c in req_body.criteria],
        settings=AnalysisSettings(
            depth=req_body.settings.depth,
            focus=req_body.settings.focus,
            length=req_body.settings.length,
            web_search=req_body.settings.web_search,
        ),
        attachments=req_body.attachments,
    )

    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return StreamingResponse(
            _stream_phronesis(input_data),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    try:
        result = await run_decision_pipeline(input_data)
        return JSONResponse(content=_phronesis_result_dict(result))
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)[:300]})


async def _stream_phronesis(input_data: DecisionInput):
    queue = asyncio.Queue()

    log_event("phronesis_started", {
        "options_count": len(input_data.options),
        "criteria_count": len(input_data.criteria),
        "depth": input_data.settings.depth,
    })

    def on_step(step: str, detail: str):
        queue.put_nowait({"step": step, "detail": detail})

    async def run():
        try:
            result = await run_decision_pipeline(input_data, on_step=on_step)
            log_event("phronesis_completed", {
                "run_id": result.run_id,
                "winner": result.winner[:100],
                "confidence": result.confidence_level,
                "latency_ms": result.latency_ms,
            })
            queue.put_nowait({"result": _phronesis_result_dict(result)})
        except Exception as e:
            log_event("phronesis_error", {"error": str(e)[:200]})
            queue.put_nowait({"error": str(e)[:300]})
        queue.put_nowait(None)

    task = asyncio.create_task(run())
    while True:
        item = await queue.get()
        if item is None:
            break
        if "step" in item:
            yield f"event: step\ndata: {json.dumps(item)}\n\n"
        elif "result" in item:
            yield f"event: result\ndata: {json.dumps(item['result'])}\n\n"
        elif "error" in item:
            yield f"event: error\ndata: {json.dumps(item)}\n\n"
    await task


def _phronesis_result_dict(result) -> dict:
    return {
        "run_id": result.run_id,
        "question": result.question,
        "winner": result.winner,
        "why_winner_won": result.why_winner_won,
        "judges_agree": result.judges_agree,
        "judge_count": result.judge_count,
        "confidence_level": result.confidence_level,
        "confidence_score": result.confidence_score,
        "total_cost_usd": round(result.total_cost_usd, 4),
        "latency_ms": result.latency_ms,
        "ranked_options": [
            {
                "option": o.option,
                "rank": o.rank,
                "final_score": round(o.final_score, 2),
                "dimension_scores": {k: round(v, 2) for k, v in o.dimension_scores.items()},
                "strengths": o.strengths,
                "weaknesses": o.weaknesses,
                "rank_points": o.rank_points,
            }
            for o in result.ranked_options
        ],
    }


class ExtractRequest(BaseModel):
    text: str = Field(min_length=10, max_length=2000)


@app.post("/phronesis/api/extract")
async def phronesis_extract(req: ExtractRequest):
    result = await extract_decision(req.text)
    if not result:
        return JSONResponse(status_code=422, content={"error": "Could not parse decision."})
    return result


class SuggestRequest(BaseModel):
    text: str = Field(min_length=5, max_length=2000)


@app.post("/phronesis/api/suggest")
async def phronesis_suggest(req: SuggestRequest):
    chips = await suggest_chips(req.text)
    return {"chips": chips}


@app.post("/phronesis/api/upload")
async def phronesis_upload(file: UploadFile = File(...)):
    if not file.filename:
        return JSONResponse(status_code=400, content={"error": "No file provided"})
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        return JSONResponse(status_code=413, content={"error": "File too large (max 5MB)"})
    safe_name = f"{_uuid.uuid4().hex[:8]}_{file.filename}"
    path = UPLOAD_DIR / safe_name
    with open(path, "wb") as f:
        f.write(contents)
    return {"filename": safe_name, "original": file.filename, "size": len(contents)}


@app.get("/phronesis/api/history")
async def phronesis_history():
    return {"decisions": get_recent_decisions(limit=20)}


# ─── Outcome tracking ───

class OutcomeRequest(BaseModel):
    run_id: str = Field(min_length=4, max_length=64)
    rating: int = Field(ge=1, le=5)
    note: str = Field(default="", max_length=1000)
    chosen_option: str = Field(default="", max_length=200)


@app.post("/phronesis/api/outcome")
async def phronesis_outcome(req: OutcomeRequest):
    from shared.tracking.outcomes import record_outcome
    entry = record_outcome(req.run_id, req.rating, req.note, req.chosen_option)
    log_event("outcome_reported", {"run_id": req.run_id, "rating": req.rating})
    return {"ok": True, "entry": entry}


# Legacy redirects
@app.get("/decide")
async def legacy_decide():
    return RedirectResponse(url="/phronesis", status_code=302)


@app.get("/result/{run_id}")
async def legacy_result(run_id: str):
    return RedirectResponse(url=f"/phronesis/result/{run_id}", status_code=302)


# ═══════════════════════════════════════════════════════
# SYNTHESIS — Multi-Model Research
# ═══════════════════════════════════════════════════════

class SynthesisRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=8000)
    category: str = Field(default="deep_research")
    mode: str = Field(default="standard", pattern="^(standard|expert)$")
    quick_mode: bool = False


@app.get("/synthesis", response_class=HTMLResponse)
async def synthesis_home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"tool": "synthesis"})


@app.get("/synthesis/result/{run_id}", response_class=HTMLResponse)
async def synthesis_result(request: Request, run_id: str):
    from shared.tracking.synthesis_history import get_synthesis_run
    result = get_synthesis_run(run_id)
    if not result:
        return templates.TemplateResponse(request, "404.html", {"tool": "synthesis"}, status_code=404)
    return templates.TemplateResponse(request, "result.html", {"result": result, "tool": "synthesis"})


@app.post("/synthesis/api/run")
async def synthesis_run(req_body: SynthesisRequest, req: Request):
    if not settings.has_any_api_key():
        return JSONResponse(status_code=503, content={"error": "No AI API keys configured."})

    run_id = _uuid.uuid4().hex[:8]

    # Expert mode uses stronger models
    if req_body.mode == "expert":
        models = ["gpt-4o", "claude-sonnet-4-6", "gemini-2.5-flash", "deepseek-chat", "grok-3"]
        admin_overrides = {"force_tier": "expert", "force_web_search": False}
    else:
        models = ["gpt-4o-mini", "claude-haiku-4-5-20251001", "gemini-2.5-flash", "deepseek-chat", "grok-3"]
        admin_overrides = {"force_tier": "standard", "force_web_search": False}

    return StreamingResponse(
        _stream_synthesis(run_id, req_body.prompt, req_body.category, req_body.mode, models, admin_overrides, req_body.quick_mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _stream_synthesis(run_id: str, prompt: str, category: str, mode: str, models: list, admin_overrides: dict, quick_mode: bool = False):
    from shared.tracking.synthesis_history import save_synthesis_run

    queue = asyncio.Queue()
    model_tasks = {}

    # Capture outputs for persistence
    strategist_outputs = {}
    final_output = None
    phase_names = []

    pipeline_task = asyncio.create_task(
        run_synthesis_pipeline(
            run_id=run_id,
            category=category,
            prompt=prompt,
            models=models,
            queue=queue,
            model_tasks=model_tasks,
            mode=mode,
            quick_mode=quick_mode,
            admin_overrides=admin_overrides,
        )
    )

    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=1800)
        except asyncio.TimeoutError:
            yield f"event: error\ndata: {json.dumps({'message': 'Timeout after 30 minutes'})}\n\n"
            break

        event = item.get("event", "")
        data = item.get("data", {})

        # Inject run_id into key events so frontend can link to /synthesis/result/{id}
        if event in ("decision", "done"):
            data = {**data, "run_id": run_id}

        # Capture for persistence
        if event == "phases_info":
            phase_names = data.get("names", [])
        elif event == "strategist":
            phase = data.get("phase", 0)
            phase_name = phase_names[phase - 1] if 0 < phase <= len(phase_names) else f"Phase {phase}"
            strategist_outputs[phase_name] = data.get("result", "")
        elif event == "decision":
            final_output = data.get("result", "")

        yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

        if event == "done" or event == "error":
            break

    try:
        await pipeline_task
    except Exception:
        pass

    # Persist the run
    if final_output:
        try:
            save_synthesis_run({
                "run_id": run_id,
                "prompt": prompt,
                "category": category,
                "mode": mode,
                "output": final_output,
                "strategist_outputs": strategist_outputs,
                "model_count": len(models),
            })
            log_event("synthesis_completed", {
                "run_id": run_id,
                "mode": mode,
                "category": category,
                "output_length": len(final_output),
                "phases": len(strategist_outputs),
            })
        except Exception:
            pass


# ═══════════════════════════════════════════════════════
# STATIC FILES
# ═══════════════════════════════════════════════════════

if Path("shared/static").exists():
    app.mount("/static", StaticFiles(directory="shared/static"), name="static")


# ═══════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
