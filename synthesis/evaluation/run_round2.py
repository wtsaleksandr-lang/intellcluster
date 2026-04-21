#!/usr/bin/env python3
"""
Round 2 Benchmark — 15 prompts, enhanced reporting.
Reuses cached outputs where available.

Usage:
    python evaluation/run_round2.py --app-url http://localhost:8099
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from synthesis.config import settings
from synthesis.evaluation.collectors.app_collector import collect_app_output
from synthesis.evaluation.pipeline_logger import PipelineExecutionLog, save_pipeline_logs, generate_integrity_summary
from synthesis.evaluation.collectors.standalone_collector import collect_standalone_output
from synthesis.evaluation.judges.blind_judge import anonymize_responses, run_judge
from synthesis.evaluation.aggregator import (
    aggregate_prompt_results,
    aggregate_full_evaluation,
    generate_report_v2,
    save_report,
)


OUTPUTS_DIR = Path("evaluation/outputs")
PROMPTS_FILE = Path("evaluation/test_prompts.json")

# Round 2 prompt selection: 15 prompts, 3 per category
ROUND2_PROMPTS = [
    # Decision Making (3)
    "P01",  # Contradictory Strategy Resolution (cached)
    "P04",  # Business Model Validation (cached)
    "P11",  # Impossible Trade-Off Prioritization (new, hard)
    # Competitor / Market Research (3)
    "P02",  # Competitive Landscape Deep Dive
    "P10",  # Year-Ahead Market Forecast
    "P12",  # Blind Spot Detection (new, hard)
    # Planning / Execution (3)
    "P05",  # Go-To-Market Under Constraints
    "P06",  # Technical Architecture Decision
    "P13",  # Crisis Execution Plan (new, hard)
    # Risk Analysis (3)
    "P08",  # Risk Analysis with Mitigations (cached)
    "P14",  # Cascade Failure Scenario (new, hard)
    "P07",  # Pricing Strategy (has risk elements)
    # Comparison / Evaluation (3)
    "P03",  # Multi-Variable Decision Matrix
    "P09",  # Content Strategy with SEO
    "P15",  # Contradictory Data Reconciliation (new, hard)
]


def load_prompts() -> list[dict]:
    with open(PROMPTS_FILE) as f:
        all_prompts = json.load(f)
    prompt_map = {p["id"]: p for p in all_prompts}
    return [prompt_map[pid] for pid in ROUND2_PROMPTS if pid in prompt_map]


def save_outputs(prompt_id: str, outputs: list[dict]):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    path.write_text(json.dumps(outputs, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cached_outputs(prompt_id: str) -> list[dict] | None:
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        # Only reuse if we have all 4 systems
        systems = {o.get("system") for o in data}
        if len(systems) >= 4 and all(o.get("final_output") for o in data):
            return data
    return None


async def collect_for_prompt(prompt: dict, app_url: str) -> tuple[list[dict], PipelineExecutionLog | None]:
    """Collect from app + 3 standalone models. Returns (outputs, pipeline_log)."""
    prompt_text = prompt["prompt"]
    category = prompt["category"]
    outputs = []

    # Create pipeline log for this run
    plog = PipelineExecutionLog(prompt["id"], prompt["title"], category)

    # App
    print(f"  [app] collecting...", end="", flush=True)
    try:
        t0 = time.time()
        app_out = await collect_app_output(prompt_text, category, base_url=app_url, pipeline_log=plog)
        app_out["prompt_id"] = prompt["id"]
        app_out["timestamp"] = datetime.now(timezone.utc).isoformat()
        outputs.append(app_out)
        elapsed = time.time() - t0
        chars = len(app_out.get("final_output", ""))
        print(f" {chars} chars, {elapsed:.0f}s")
    except Exception as e:
        print(f" FAILED: {e}")
        plog.errors.append(f"App collection failed: {e}")

    # Standalone models
    providers = [
        ("openai", settings.openai_api_key),
        ("anthropic", settings.anthropic_api_key),
        ("google", settings.google_api_key),
    ]
    for pname, key in providers:
        if not key:
            print(f"  [{pname}] skipped (no key)")
            continue
        print(f"  [{pname}] collecting...", end="", flush=True)
        try:
            t0 = time.time()
            out = await collect_standalone_output(prompt_text, pname, key)
            out["prompt_id"] = prompt["id"]
            out["timestamp"] = datetime.now(timezone.utc).isoformat()
            outputs.append(out)
            elapsed = time.time() - t0
            chars = len(out.get("final_output", ""))
            print(f" {chars} chars, {elapsed:.0f}s")
        except Exception as e:
            print(f" FAILED: {e}")

    return outputs, plog


async def judge_outputs(prompt: dict, outputs: list[dict]) -> tuple[list[dict], dict]:
    """Anonymize and run 3 judges."""
    valid = [o for o in outputs if o.get("final_output")]
    if len(valid) < 2:
        print(f"  Only {len(valid)} valid outputs — skipping")
        return [], {}

    anonymized, key_map = anonymize_responses(valid)

    judge_keys = [
        ("judge_openai", settings.openai_api_key),
        ("judge_anthropic", settings.anthropic_api_key),
        ("judge_google", settings.google_api_key),
    ]

    results = []
    for jname, key in judge_keys:
        if not key:
            continue
        print(f"  [{jname}] judging...", end="", flush=True)
        try:
            r = await run_judge(jname, key, prompt["prompt"], anonymized)
            if "error" in r:
                print(f" error: {r['error'][:60]}")
            else:
                ranking = r.get("ranking", [])
                winner_label = ranking[0] if ranking else "?"
                winner_sys = key_map.get(winner_label, "?")
                print(f" winner={winner_sys}")
            results.append(r)
        except Exception as e:
            print(f" FAILED: {e}")
            results.append({"error": str(e)})

    return results, key_map


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://localhost:8099")
    args = parser.parse_args()

    prompts = load_prompts()
    print(f"Round 2 Benchmark: {len(prompts)} prompts")
    print(f"App URL: {args.app_url}\n")

    all_prompt_results = []
    pipeline_logs = []
    speed_records = {}  # system -> [runtime_ms]
    cost_records = {}   # system -> [cost_estimate]

    for i, prompt in enumerate(prompts):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(prompts)}] {prompt['id']}: {prompt['title']}")
        print(f"{'='*60}")

        plog = None
        # Check cache
        cached = load_cached_outputs(prompt["id"])
        if cached:
            print(f"  CACHED: reusing {len(cached)} outputs")
            outputs = cached
        else:
            outputs, plog = await collect_for_prompt(prompt, args.app_url)
            save_outputs(prompt["id"], outputs)
            print(f"  Saved {len(outputs)} outputs")

        # Print pipeline validation
        if plog:
            print(f"  PIPELINE: {plog.summary_line()}")
            pipeline_logs.append(plog)

        if not outputs:
            continue

        # Track speed
        for o in outputs:
            sys = o.get("system", "unknown")
            rt = o.get("runtime_ms", 0)
            if rt > 0:
                speed_records.setdefault(sys, []).append(rt)
            ce = o.get("cost_estimate")
            if ce:
                cost_records.setdefault(sys, []).append(ce)

        # Judge
        judge_results, key_map = await judge_outputs(prompt, outputs)

        # Aggregate
        result = aggregate_prompt_results(prompt, judge_results, key_map)
        all_prompt_results.append(result)
        winner_display = result["winner"].replace("standalone_", "").replace("_", " ").title()
        agree = "unanimous" if result["judges_agree"] else "split"
        print(f"  >>> Winner: {winner_display} ({agree})")

    # FULL AGGREGATION
    print(f"\n{'='*60}")
    print("FINAL AGGREGATION")
    print(f"{'='*60}")

    full_agg = aggregate_full_evaluation(all_prompt_results)

    # Build speed/cost summaries
    speed_data = {}
    for sys, times in speed_records.items():
        times_s = [t / 1000 for t in times]
        speed_data[sys] = {
            "avg": sum(times_s) / len(times_s),
            "min": min(times_s),
            "max": max(times_s),
        }

    cost_data = {}
    for sys, costs in cost_records.items():
        cost_data[sys] = {"avg_cost": sum(costs) / len(costs), "total": sum(costs)}

    # Print summary
    print(f"\nWin counts: {full_agg['win_counts']}")
    print(f"Win rates: {full_agg['win_rate']}")
    print(f"Judge agreement: {full_agg['judge_agreement_rate']:.0%}")

    for sys, scores in full_agg.get("avg_scores_overall", {}).items():
        display = sys.replace("standalone_", "").replace("_", " ").title()
        print(f"  {display}: {scores.get('overall', 0):.1f}/10")

    # Pipeline integrity
    if pipeline_logs:
        print(f"\nPipeline Integrity:")
        valid = sum(1 for l in pipeline_logs if l.validity == "VALID")
        warn = sum(1 for l in pipeline_logs if l.validity == "VALID_WITH_WARNINGS")
        degraded = sum(1 for l in pipeline_logs if l.validity == "DEGRADED")
        invalid = sum(1 for l in pipeline_logs if l.validity == "INVALID")
        print(f"  VALID={valid}  WARNINGS={warn}  DEGRADED={degraded}  INVALID={invalid}")

        # Save pipeline logs
        plog_path = save_pipeline_logs(pipeline_logs)
        print(f"  Pipeline log: {plog_path}")

    # Generate report
    report = generate_report_v2(all_prompt_results, full_agg, cost_data, speed_data)

    # Append pipeline integrity section
    if pipeline_logs:
        report += "\n" + generate_integrity_summary(pipeline_logs)

    results_json = {
        "round": 2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts": [p["id"] for p in prompts],
        "per_prompt": all_prompt_results,
        "aggregation": full_agg,
        "speed_data": speed_data,
        "cost_data": cost_data,
        "pipeline_integrity": {
            "total": len(pipeline_logs),
            "valid": sum(1 for l in pipeline_logs if l.validity == "VALID"),
            "valid_with_warnings": sum(1 for l in pipeline_logs if l.validity == "VALID_WITH_WARNINGS"),
            "degraded": sum(1 for l in pipeline_logs if l.validity == "DEGRADED"),
            "invalid": sum(1 for l in pipeline_logs if l.validity == "INVALID"),
            "runs": [l.to_dict() for l in pipeline_logs],
        } if pipeline_logs else None,
    }

    md_path, json_path = save_report(report, results_json)
    print(f"\nReport saved:")
    print(f"  Markdown: {md_path}")
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
