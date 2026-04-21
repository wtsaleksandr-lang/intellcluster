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

# Synthesis imports
from synthesis.orchestrator.pipeline import run_pipeline as run_synthesis_pipeline

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="IntellCluster", version="0.1.0")

# Mount admin routes (/admin, /admin/login, /admin/logout)
app.include_router(admin_router)

# Templates — search multiple directories (Jinja2 searches in order)
templates = Jinja2Templates(directory=[
    "shared/templates",
    "phronesis/templates",
    "synthesis/templates",
    "homepage",
])


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
    from fastapi.responses import FileResponse
    return FileResponse("shared/static/sitemap.xml", media_type="application/xml")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("shared/static/favicon.svg", media_type="image/svg+xml")


@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    return templates.TemplateResponse(request, "pricing.html")


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
    with open(wl_file, "a", encoding="utf-8") as f:
        f.write(_json.dumps({
            "timestamp": _dt.now(_tz.utc).isoformat(),
            "plan": plan,
            "email": email.strip().lower()[:200],
        }) + "\n")
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

    def on_step(step: str, detail: str):
        queue.put_nowait({"step": step, "detail": detail})

    async def run():
        try:
            result = await run_decision_pipeline(input_data, on_step=on_step)
            queue.put_nowait({"result": _phronesis_result_dict(result)})
        except Exception as e:
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
        _stream_synthesis(run_id, req_body.prompt, req_body.category, req_body.mode, models, admin_overrides),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def _stream_synthesis(run_id: str, prompt: str, category: str, mode: str, models: list, admin_overrides: dict):
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
            quick_mode=False,
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
