"""
Golden-set evaluation runner.

Runs each prompt through the real Synthesis pipeline (or a mock-mode
equivalent), collects the structured report + sources + scope +
confidence from the SSE queue, then feeds the consolidated record to
each judge.

CLI
---
    python -m evals.runner --mock                  # CI-safe, no API calls
    python -m evals.runner --real                  # full sweep, costs ~$1-5
    python -m evals.runner --real --quick          # 3 prompts, fast sanity
    python -m evals.runner --real --judge llm      # include factuality judge
    python -m evals.runner --real --out results/2026-04.jsonl

Exit code: 0 if CI gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── Import bootstrap ──
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Env that `main.py` requires to import cleanly when we don't go through
# TestClient (we import pipeline directly).
os.environ.setdefault("ADMIN_PASSWORD", "eval-runner")
os.environ.setdefault("ADMIN_USERNAME", "eval")
os.environ.setdefault("ADMIN_SECRET_KEY", "eval-secret")


from evals.prompts import GoldenPrompt, get_prompts
from evals.judges import DETERMINISTIC_JUDGES, LLM_JUDGES
from evals.judges.base import JudgeResult, JudgeVerdict
from evals.scorecard import build_scorecard, render


RESULTS_DIR = REPO_ROOT / "evals" / "results"


# ─────────────────────────── pipeline driver ───────────────────────────

async def _drain_pipeline(prompt: GoldenPrompt) -> dict:
    """Run the Synthesis pipeline end-to-end, return a consolidated record."""
    from synthesis.orchestrator.pipeline import run_pipeline
    from synthesis.config import settings as synth_settings

    run_id = f"eval-{uuid.uuid4().hex[:8]}"
    queue: asyncio.Queue = asyncio.Queue()
    model_tasks: dict = {}

    # Pick research models from the mode pool — if none are available
    # (no API keys configured), pipeline will return an error state
    # and we skip cleanly.
    mode_config = synth_settings.get_mode_config(prompt.mode)
    models = list(mode_config["research_models"])

    record: dict = {
        "run_id": run_id,
        "prompt_id": prompt.id,
        "prompt": prompt.prompt,
        "category": prompt.category,
        "mode": prompt.mode,
        "expectations": dict(prompt.expectations),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "freshness_level": None,
        "sources": [],
        "source_quality": {},
        "scope": None,
        "report": None,
        "retrieval_configured": False,
        "error": None,
        "pipeline_events": [],
    }

    pipeline_task = asyncio.create_task(
        run_pipeline(
            run_id=run_id,
            category=prompt.category,
            prompt=prompt.prompt,
            models=models,
            queue=queue,
            model_tasks=model_tasks,
            mode=prompt.mode,
            quick_mode=False,
        )
    )

    # Drain events until done/error. Safety cap so a hung provider
    # doesn't freeze CI: 10 minutes per prompt.
    deadline = time.time() + 600
    while True:
        try:
            remaining = max(1, deadline - time.time())
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            record["error"] = "timeout waiting for pipeline events"
            break

        event = item.get("event", "")
        data = item.get("data", {})
        record["pipeline_events"].append({"event": event})

        if event == "freshness":
            record["freshness_level"] = data.get("level")
        elif event == "sources":
            record["sources"] = data.get("sources") or []
            record["retrieval_configured"] = (data.get("provider") or "none") != "none"
            record["providers_used"] = data.get("providers_used", [])
            record["providers_returning"] = data.get("providers_returning", [])
        elif event == "source_quality":
            record["source_quality"] = data.get("quality") or {}
        elif event == "scope":
            record["scope"] = data.get("scope")
        elif event == "structured_report":
            record["report"] = data.get("report")
        elif event == "done":
            break
        elif event == "error":
            record["error"] = data.get("message", "pipeline error")
            break

    # Wait for pipeline task to finish (or already did).
    try:
        await asyncio.wait_for(pipeline_task, timeout=5)
    except (asyncio.TimeoutError, Exception):
        pipeline_task.cancel()

    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


# ─────────────────────────── mock-mode driver ───────────────────────────

def _synthetic_record(prompt: GoldenPrompt) -> dict:
    """Build a realistic-shape record without any API calls.

    Used by --mock to exercise the judges + scorecard wiring in CI.
    The shape intentionally exercises EVERY judge's pass path so CI
    stays green when nothing regressed.
    """
    needs_fresh = bool(prompt.expectations.get("needs_freshness"))
    recent_date = "2026-01-10"

    # Two sources: dated + recent so freshness judge passes.
    sources = [
        {
            "id": 1, "title": "Stub A", "url": "https://a.example.com/x",
            "domain": "a.example.com", "published": recent_date,
            "snippet": "A snippet", "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "relevance": 0.9, "query": prompt.prompt[:80], "full_content": "full body A",
            "provider": "tavily", "providers_agreeing": ["tavily"],
        },
        {
            "id": 2, "title": "Stub B", "url": "https://b.example.com/y",
            "domain": "b.example.com", "published": recent_date,
            "snippet": "B snippet", "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "relevance": 0.8, "query": prompt.prompt[:80], "full_content": None,
            "provider": "brave", "providers_agreeing": ["brave"],
        },
    ]

    report = {
        "executive_summary": (
            "This is a realistic stub executive summary. "
            "It covers the prompt in two sentences."
        ),
        "key_findings": [
            {"finding": "A well-grounded finding with specific detail.",
             "citations": [1], "strength": "strong"},
            {"finding": "A secondary finding also cited.",
             "citations": [2], "strength": "moderate"},
        ],
        "evidence_table": [
            {"claim": "A specific claim with evidence.", "citations": [1, 2],
             "strength": "strong", "note": "stub"},
        ],
        "source_confidence_note": "Sources are stub-generated for mock mode.",
        "contradictions": [],
        "risks_unknowns": ["Stub risk"],
        "recommendation": "Recommendation stub.",
        "what_could_change": ["Stub signal"],
        "next_actions": ["Stub action"],
        "confidence": {
            "band": "moderate-high",
            "components": {
                "source_quality": 0.7, "evidence_quantity": 0.8,
                "source_agreement": 0.6, "freshness": 0.85,
                "contradiction_penalty": 0.1, "model_consensus": 0.72,
            },
            "rationale": "Stub rationale.",
        },
    }

    return {
        "run_id": f"mock-{prompt.id}",
        "prompt_id": prompt.id,
        "prompt": prompt.prompt,
        "category": prompt.category,
        "mode": prompt.mode,
        "expectations": dict(prompt.expectations),
        "freshness_level": "required" if needs_fresh else "not_needed",
        "sources": sources,
        "source_quality": {
            "1": {"overall": 0.8}, "2": {"overall": 0.6},
        },
        "scope": {"timeframe": "2026", "region": None,
                  "audience": None, "decision_intent": None},
        "report": report,
        "retrieval_configured": True,
        "error": None,
    }


# ─────────────────────────── factuality call adapter ───────────────────

async def _make_factuality_callable():
    """Return an async (prompt, system) -> (raw_text, provider) or None if unavailable."""
    try:
        from synthesis.orchestrator.providers import call_with_role_fallback
    except Exception:
        return None

    async def _call(prompt: str, system: str):
        result, provider = await call_with_role_fallback(
            role="strategist", prompt=prompt, system=system, tier="cost_efficient",
        )
        return (result.response_content or "", provider)

    return _call


# ─────────────────────────── judge orchestration ───────────────────────

async def _run_judges_for_record(
    record: dict,
    include_llm: bool,
) -> list[JudgeResult]:
    results: list[JudgeResult] = []

    for mod in DETERMINISTIC_JUDGES:
        try:
            r = await mod.judge(record)
        except Exception as e:
            r = JudgeResult(
                judge=mod.name, verdict=JudgeVerdict.ERROR, score=0.0,
                note=f"judge raised: {str(e)[:200]}",
            )
        results.append(r)

    if include_llm:
        call_fn = await _make_factuality_callable()
        for mod in LLM_JUDGES:
            try:
                r = await mod.judge(record, call_fn=call_fn)
            except Exception as e:
                r = JudgeResult(
                    judge=mod.name, verdict=JudgeVerdict.ERROR, score=0.0,
                    note=f"judge raised: {str(e)[:200]}",
                )
            results.append(r)

    return results


# ─────────────────────────── main ──────────────────────────────────────

async def run_all(
    *,
    mode: str,
    quick: bool,
    include_llm: bool,
    out_path: Path | None,
) -> int:
    prompts = get_prompts(quick=quick)
    print(f"[evals] running {len(prompts)} prompt(s) in {mode} mode "
          f"(llm judges {'ON' if include_llm else 'OFF'})")
    print()

    per_prompt_records: list[dict] = []
    for i, p in enumerate(prompts, 1):
        print(f"[{i}/{len(prompts)}] {p.id}  ({p.category}/{p.mode})")
        if mode == "mock":
            record = _synthetic_record(p)
        else:
            try:
                record = await _drain_pipeline(p)
            except Exception as e:
                record = {
                    "prompt_id": p.id, "prompt": p.prompt,
                    "category": p.category, "mode": p.mode,
                    "expectations": dict(p.expectations),
                    "error": f"driver raised: {str(e)[:200]}",
                    "sources": [], "report": None,
                }

        judges = await _run_judges_for_record(record, include_llm=include_llm)
        per_prompt_records.append({"prompt_id": p.id, "judges": judges})

        # Short line per prompt so CI log is scannable.
        summary = " ".join(f"{j.judge[:4]}={j.verdict.value[:4]}" for j in judges)
        print(f"   {summary}")

        # Persist detail (record + judges as dicts).
        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a", encoding="utf-8") as f:
                payload = {
                    "prompt_id": p.id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "record": {
                        k: v for k, v in record.items()
                        if k != "pipeline_events"   # keep JSONL small
                    },
                    "judges": [j.to_dict() for j in judges],
                }
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    scorecard = build_scorecard(per_prompt_records)
    print()
    print(render(scorecard))
    return 0 if scorecard.ci_verdict == "pass" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesis golden-set eval runner")
    mode_grp = parser.add_mutually_exclusive_group(required=True)
    mode_grp.add_argument("--mock", action="store_true", help="no API calls; CI-safe")
    mode_grp.add_argument("--real", action="store_true", help="full pipeline, real APIs")
    parser.add_argument("--quick", action="store_true", help="3 prompts instead of 20")
    parser.add_argument("--judge", choices=("det", "llm"), default="det",
                        help="det = deterministic judges only (default); "
                             "llm = also run factuality (requires provider keys)")
    default_out = RESULTS_DIR / f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"
    parser.add_argument("--out", type=Path, default=default_out,
                        help=f"JSONL output path (default: {default_out})")
    args = parser.parse_args()

    exit_code = asyncio.run(run_all(
        mode="mock" if args.mock else "real",
        quick=args.quick,
        include_llm=(args.judge == "llm"),
        out_path=args.out,
    ))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
