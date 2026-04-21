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

from fastapi import FastAPI, Request, UploadFile, File
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

# Synthesis imports
from synthesis.orchestrator.pipeline import run_pipeline as run_synthesis_pipeline

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="IntellCluster", version="0.1.0")

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


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "tools": ["phronesis", "synthesis"],
        "providers": settings.available_judges(),
        "has_api_keys": settings.has_any_api_key(),
    }


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
    return templates.TemplateResponse(request, "result.html", {"result": decision})


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
    queue = asyncio.Queue()
    model_tasks = {}

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
        yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

        if event == "done" or event == "error":
            break

    try:
        await pipeline_task
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
