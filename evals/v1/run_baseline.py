"""
IntellCluster baseline runner.

For each case in cases.json, runs:
  1. GPT-4o solo (with structured rubric prompt)
  2. Claude Sonnet 4.6 solo
  3. Gemini 2.5 Flash solo
  4. IntellCluster Phronesis (decisions only) — standard depth
  5. IntellCluster Synthesis (research only) — standard mode, single phase

Saves outputs to evals/v1/runs/ts_<timestamp>/runs.json plus a blind-pair
file per case for the judge.

Run from intellcluster repo root:
    .venv/Scripts/python.exe evals/v1/run_baseline.py [--cases ID1,ID2,...]

Typical cost for full 20-case run: ~$3-6 USD.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make project root importable
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx


# ─── Config ──────────────────────────────────────────────────────────────────

CASES_FILE = ROOT / "evals" / "v1" / "cases.json"
RUNS_DIR = ROOT / "evals" / "v1" / "runs"

GPT_MODEL = "gpt-4o"
SONNET_MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = "gemini-2.5-flash"

# Standard rubric prompt for solo baselines — matches what a typical user
# would write to a single model. NOT the orchestration system prompts; the
# point is to compare orchestration vs "what GPT-4o gives a smart user".
DECISION_BASELINE_SYSTEM = """You are an expert decision analyst. The user will give you a decision they're facing, with options and criteria. Provide:

1. A clear recommendation (which option) with confidence level
2. Specific quantitative or qualitative reasoning for each criterion
3. Key risks or caveats
4. What additional information would change your recommendation

Be specific. Use numbers where possible. Don't hedge with "it depends" — give a real recommendation.""".strip()

RESEARCH_BASELINE_SYSTEM = """You are a senior research analyst. The user will ask you a research question. Provide:

1. A direct answer to the question with confidence appropriate to the evidence
2. Supporting evidence — specific studies, data, or named sources where applicable
3. Where experts disagree, characterize the disagreement
4. What you're uncertain about

Be specific. Cite sources. Don't fabricate references — if you're unsure, say so.""".strip()


# ─── Solo baseline callers ───────────────────────────────────────────────────

async def call_openai(prompt: str, system: str) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GPT_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "no OPENAI_API_KEY"}
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": GPT_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 2500,
                    "temperature": 0.3,
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "status": "ok",
                "model": GPT_MODEL,
                "content": data["choices"][0]["message"]["content"],
                "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "latency_sec": round(time.time() - start, 2),
            }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "latency_sec": round(time.time() - start, 2)}


async def call_anthropic(prompt: str, system: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "no ANTHROPIC_API_KEY"}
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": SONNET_MODEL,
                    "max_tokens": 2500,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            return {
                "status": "ok",
                "model": SONNET_MODEL,
                "content": text,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "latency_sec": round(time.time() - start, 2),
            }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "latency_sec": round(time.time() - start, 2)}


async def call_google(prompt: str, system: str) -> dict:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"status": "skipped", "reason": "no GOOGLE_API_KEY"}
    start = time.time()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": system}]},
                    # thinkingBudget=0 prevents Gemini 2.5 from spending the
                    # token budget on hidden thinking before producing output.
                    "generationConfig": {
                        "maxOutputTokens": 2500,
                        "temperature": 0.3,
                        "thinkingConfig": {"thinkingBudget": 0},
                    },
                },
            )
            r.raise_for_status()
            data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                return {"status": "error", "error": "no candidates returned"}
            text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
            usage = data.get("usageMetadata", {})
            return {
                "status": "ok",
                "model": GEMINI_MODEL,
                "content": text,
                "input_tokens": usage.get("promptTokenCount", 0),
                "output_tokens": usage.get("candidatesTokenCount", 0),
                "latency_sec": round(time.time() - start, 2),
            }
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "latency_sec": round(time.time() - start, 2)}


# ─── Orchestration callers ───────────────────────────────────────────────────

async def call_phronesis(case: dict) -> dict:
    """Run a decision through IntellCluster's Phronesis pipeline."""
    from phronesis.engine.types import DecisionInput, AnalysisSettings
    from phronesis.engine.pipeline import run_decision_pipeline

    start = time.time()
    try:
        input_data = DecisionInput(
            question=case["question"],
            options=case["options"],
            criteria=case["criteria"],
            settings=AnalysisSettings(depth="standard", focus="balanced", length="detailed", web_search=False),
        )
        result = await run_decision_pipeline(input_data)
        # The synthesizer now writes a full structured analysis. Render it
        # as the primary content, append the score-detail block as supporting
        # evidence — judges scored prose-style answers far higher than score-
        # table summaries in the v1 baseline.
        content_lines = [result.why_winner_won.strip(), ""]
        content_lines.append("---")
        content_lines.append("")
        content_lines.append(f"**Confidence:** {result.confidence_level} ({round(result.confidence_score)}%)  ·  **Analyst panel:** {result.judge_count} {'in agreement' if result.judges_agree else 'split'}")
        content_lines.append("")
        content_lines.append("**Ranking:**")
        for opt in result.ranked_options:
            content_lines.append(f"{opt.rank}. {opt.option} — {opt.final_score:.2f}/10")
        content = "\n".join(content_lines)
        return {
            "status": "ok",
            "model": "phronesis-standard",
            "content": content,
            "total_cost_usd": result.total_cost_usd,
            "latency_sec": round(time.time() - start, 2),
            "internal_latency_ms": result.latency_ms,
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc().splitlines()[-3:],
            "latency_sec": round(time.time() - start, 2),
        }


async def call_synthesis(case: dict) -> dict:
    """Run a research question through IntellCluster's Synthesis pipeline (standard mode, single phase)."""
    import asyncio
    from synthesis.orchestrator.pipeline import run_pipeline

    start = time.time()
    queue: asyncio.Queue = asyncio.Queue()
    model_tasks: dict = {}
    final_output = None
    structured_report = None
    sources = []

    # Use case-supplied category if present, default to deep_research for
    # generic research questions. Synthesis pipeline rejects unknown cats.
    category = case.get("synthesis_category", "deep_research")
    pipeline_task = asyncio.create_task(
        run_pipeline(
            run_id=f"eval_{case['id']}",
            category=category,
            prompt=case["question"],
            models=["gpt-4o-mini", "claude-sonnet-4-6", "gemini-2.5-flash", "deepseek-chat", "grok-3"],
            queue=queue,
            model_tasks=model_tasks,
            mode="standard",
            quick_mode=False,
            admin_overrides={"force_tier": "standard", "force_web_search": False},
        )
    )

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=60)
            except asyncio.TimeoutError:
                if pipeline_task.done():
                    break
                continue
            event = item.get("event", "")
            data = item.get("data", {})
            if event == "decision":
                final_output = data.get("result", "")
            elif event == "structured_report":
                structured_report = data.get("report")
            elif event == "sources":
                sources = data.get("sources") or []
            if event in ("done", "error"):
                break
        try:
            await asyncio.wait_for(pipeline_task, timeout=10)
        except (asyncio.TimeoutError, Exception):
            pipeline_task.cancel()
        if not final_output:
            return {"status": "error", "error": "no decision produced", "latency_sec": round(time.time() - start, 2)}
        return {
            "status": "ok",
            "model": "synthesis-standard",
            "content": final_output,
            "structured_report": structured_report,
            "source_count": len(sources),
            "latency_sec": round(time.time() - start, 2),
        }
    except Exception as e:
        if not pipeline_task.done():
            pipeline_task.cancel()
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "latency_sec": round(time.time() - start, 2)}


# ─── Per-case driver ─────────────────────────────────────────────────────────

def format_decision_prompt(case: dict) -> str:
    parts = [f"## Decision\n{case['question']}", "## Options"]
    for o in case["options"]:
        parts.append(f"- {o}")
    parts.append("\n## Criteria")
    for c in case["criteria"]:
        parts.append(f"- {c['name']} (importance: {c['weight']}/10)")
    return "\n".join(parts)


def format_research_prompt(case: dict) -> str:
    return f"## Research question\n\n{case['question']}"


async def run_case(case: dict) -> dict:
    is_decision = case["kind"] == "decision"
    if is_decision:
        prompt = format_decision_prompt(case)
        baseline_system = DECISION_BASELINE_SYSTEM
    else:
        prompt = format_research_prompt(case)
        baseline_system = RESEARCH_BASELINE_SYSTEM

    print(f"  [{case['id']}] running {'decision' if is_decision else 'research'} case…")
    sys.stdout.flush()

    # Run baselines in parallel — they're independent calls.
    gpt_task = asyncio.create_task(call_openai(prompt, baseline_system))
    sonnet_task = asyncio.create_task(call_anthropic(prompt, baseline_system))
    gemini_task = asyncio.create_task(call_google(prompt, baseline_system))

    baselines = await asyncio.gather(gpt_task, sonnet_task, gemini_task, return_exceptions=True)
    gpt_out, sonnet_out, gemini_out = baselines

    # Run orchestration sequentially after baselines (avoids rate hits)
    if is_decision:
        orch_out = await call_phronesis(case)
    else:
        orch_out = await call_synthesis(case)

    return {
        "case_id": case["id"],
        "kind": case["kind"],
        "question": case["question"],
        "responses": {
            "gpt4o_solo": gpt_out,
            "sonnet_solo": sonnet_out,
            "gemini_solo": gemini_out,
            "intellcluster": orch_out,
        },
    }


# ─── Blind-pair builder ──────────────────────────────────────────────────────

def make_blind_pairs(case_run: dict, run_dir: Path) -> None:
    """Write a per-case file with answers labeled A/B/C/D in random order — for blind grading."""
    case_id = case_run["case_id"]
    answers = []
    for source, resp in case_run["responses"].items():
        if resp.get("status") != "ok":
            continue
        answers.append({"source": source, "content": resp.get("content", "")})

    # Shuffle for blinding
    rng = random.Random(case_id)  # deterministic per case so re-runs match
    rng.shuffle(answers)
    labels = ["A", "B", "C", "D", "E"][:len(answers)]
    blind = []
    label_map = {}
    for label, ans in zip(labels, answers):
        blind.append({"label": label, "content": ans["content"]})
        label_map[label] = ans["source"]

    out = {
        "case_id": case_id,
        "kind": case_run["kind"],
        "question": case_run["question"],
        "answers_blind": blind,
        "label_map_DO_NOT_SHOW_GRADER": label_map,
    }
    blind_dir = run_dir / "blind_pairs"
    blind_dir.mkdir(parents=True, exist_ok=True)
    (blind_dir / f"{case_id}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", help="Comma-separated case IDs (default: all)", default="")
    p.add_argument("--limit", type=int, default=0, help="Max cases to run (0=all)")
    args = p.parse_args()

    cases_data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    all_cases = cases_data["decisions"] + cases_data["research"]

    if args.cases:
        wanted = set(c.strip() for c in args.cases.split(","))
        all_cases = [c for c in all_cases if c["id"] in wanted]
    if args.limit:
        all_cases = all_cases[: args.limit]

    if not all_cases:
        print("No cases selected.")
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / f"ts_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(all_cases)} case(s) -> {run_dir}")
    sys.stdout.flush()

    results = []
    for case in all_cases:
        r = await run_case(case)
        results.append(r)
        # Stream-write so a long run doesn't lose data on crash
        (run_dir / "runs.json").write_text(
            json.dumps({"started_at": ts, "cases": results}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        make_blind_pairs(r, run_dir)

    # Final summary
    ok_counts = {}
    cost_total = {"input_tokens": 0, "output_tokens": 0}
    for r in results:
        for source, resp in r["responses"].items():
            ok_counts.setdefault(source, {"ok": 0, "error": 0, "skipped": 0})
            ok_counts[source][resp.get("status", "error")] = ok_counts[source].get(resp.get("status", "error"), 0) + 1
            cost_total["input_tokens"] += resp.get("input_tokens", 0) or 0
            cost_total["output_tokens"] += resp.get("output_tokens", 0) or 0

    print("\n=== Summary ===")
    print(f"Cases run: {len(results)}")
    print("Per-source success:")
    for source, counts in ok_counts.items():
        print(f"  {source:20s} ok={counts.get('ok', 0)}  err={counts.get('error', 0)}  skip={counts.get('skipped', 0)}")
    print(f"Approx tokens: input={cost_total['input_tokens']} output={cost_total['output_tokens']}")
    print(f"\nRuns saved to: {run_dir}")
    print(f"Blind pairs: {run_dir / 'blind_pairs'}/")


if __name__ == "__main__":
    asyncio.run(main())
