#!/usr/bin/env python3
"""
Round 3 Benchmark — 20 real-world business prompts.
Commercial scoring rubric. Pipeline integrity logging.

Usage:
    python evaluation/run_round3.py --app-url http://localhost:8099
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
from synthesis.evaluation.collectors.standalone_collector import collect_standalone_output
from synthesis.evaluation.judges.blind_judge import anonymize_responses, run_judge
from synthesis.evaluation.pipeline_logger import PipelineExecutionLog, save_pipeline_logs, generate_integrity_summary
from synthesis.evaluation.rubric import DIMENSIONS_COMMERCIAL, build_judge_system, build_judge_prompt
from synthesis.evaluation.cost_profiles import get_testing_profile, CostTracker
from synthesis.evaluation.aggregator import (
    aggregate_full_evaluation,
    save_report,
)


OUTPUTS_DIR = Path("evaluation/outputs")
R3_PROMPTS_FILE = Path("evaluation/round3_prompts.json")


def load_prompts(filter_ids: list[str] | None = None) -> list[dict]:
    with open(R3_PROMPTS_FILE) as f:
        prompts = json.load(f)
    if filter_ids:
        prompts = [p for p in prompts if p["id"] in filter_ids]
    return prompts


def save_outputs(prompt_id: str, outputs: list[dict]):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    path.write_text(json.dumps(outputs, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cached(prompt_id: str) -> list[dict] | None:
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        systems = {o.get("system") for o in data}
        if len(systems) >= 4 and all(o.get("final_output") for o in data):
            return data
    return None


async def collect_for_prompt(prompt: dict, app_url: str,
                             cost_tracker: CostTracker | None = None) -> tuple[list[dict], PipelineExecutionLog]:
    prompt_text = prompt["prompt"]
    category = prompt.get("category", "deep_research")
    outputs = []
    plog = PipelineExecutionLog(prompt["id"], prompt["title"], category)

    # Map categories to valid backend categories
    cat_map = {"logistics": "deep_research", "smb_growth": "marketing_growth"}
    backend_cat = cat_map.get(category, category)

    print(f"  [app] collecting...", end="", flush=True)
    try:
        t0 = time.time()
        app_out = await collect_app_output(prompt_text, backend_cat, base_url=app_url, pipeline_log=plog)
        app_out["prompt_id"] = prompt["id"]
        app_out["timestamp"] = datetime.now(timezone.utc).isoformat()
        outputs.append(app_out)
        print(f" {len(app_out.get('final_output',''))} chars, {time.time()-t0:.0f}s")
    except Exception as e:
        print(f" FAILED: {e}")
        plog.errors.append(f"App collection failed: {e}")

    providers = [
        ("openai", settings.openai_api_key),
        ("anthropic", settings.anthropic_api_key),
        ("google", settings.google_api_key),
    ]
    for pname, key in providers:
        if not key:
            continue
        print(f"  [{pname}] collecting...", end="", flush=True)
        try:
            t0 = time.time()
            out = await collect_standalone_output(prompt_text, pname, key)
            out["prompt_id"] = prompt["id"]
            out["timestamp"] = datetime.now(timezone.utc).isoformat()
            outputs.append(out)
            out_len = len(out.get('final_output',''))
            print(f" {out_len} chars, {time.time()-t0:.0f}s")
            if cost_tracker:
                model = out.get("model", pname)
                cost_tracker.record(f"standalone_{pname}", model, "collection", len(prompt_text), out_len)
        except Exception as e:
            print(f" FAILED: {e}")

    plog.mode = "standard"
    plog.finalize(int((time.time() - t0) * 1000) if outputs else 0)
    return outputs, plog


async def judge_outputs(prompt: dict, outputs: list[dict],
                        cost_tracker: CostTracker | None = None) -> tuple[list[dict], dict]:
    valid = [o for o in outputs if o.get("final_output")]
    if len(valid) < 2:
        return [], {}

    anonymized, key_map = anonymize_responses(valid)
    profile = get_testing_profile()

    judge_keys = [
        ("judge_openai", settings.openai_api_key),
        ("judge_anthropic", settings.anthropic_api_key),
        ("judge_google", settings.google_api_key),
    ]

    results = []
    for jname, key in judge_keys:
        if not key:
            continue
        # Use cost-profile model override
        model_override = profile["judge_models"].get(jname)
        print(f"  [{jname}] judging (model={model_override})...", end="", flush=True)
        try:
            r = await run_judge(jname, key, prompt["prompt"], anonymized,
                                commercial=True, model_override=model_override)
            if "error" in r:
                print(f" error: {r['error'][:60]}")
            else:
                ranking = r.get("ranking", [])
                winner = key_map.get(ranking[0], "?") if ranking else "?"
                print(f" winner={winner}")
                # Track judge cost
                if cost_tracker and model_override:
                    prompt_len = len(prompt["prompt"]) + sum(len(v) for v in anonymized.values())
                    cost_tracker.record(jname, model_override, "judge", prompt_len, 2000)
            results.append(r)
        except Exception as e:
            print(f" FAILED: {e}")
            results.append({"error": str(e)})

    return results, key_map


def aggregate_r3_prompt(prompt: dict, judge_results: list[dict], key_map: dict) -> dict:
    """Aggregate scores using commercial dimensions."""
    label_to_system = key_map
    system_scores = {}
    system_rank_points = {}
    hallucinations = {}  # system -> [hallucination notes]

    for jr in judge_results:
        if "error" in jr:
            continue
        evals = jr.get("evaluations", {})
        ranking = jr.get("ranking", [])

        for label, scores in evals.items():
            system = label_to_system.get(label, "unknown")
            if system not in system_scores:
                system_scores[system] = {d["name"]: [] for d in DIMENSIONS_COMMERCIAL}
                system_rank_points[system] = []
                hallucinations[system] = []

            for dim in DIMENSIONS_COMMERCIAL:
                val = scores.get(dim["name"])
                if isinstance(val, (int, float)):
                    system_scores[system][dim["name"]].append(val)

            h = scores.get("hallucinations", "")
            if h and h.lower() != "none detected" and h.lower() != "none":
                hallucinations[system].append(h)

        for rank_pos, label in enumerate(ranking):
            system = label_to_system.get(label, "unknown")
            if system not in system_rank_points:
                system_rank_points[system] = []
            system_rank_points[system].append(len(ranking) - rank_pos)

    systems = {}
    for system, dims in system_scores.items():
        avg = {}
        for dim_name, scores in dims.items():
            avg[dim_name] = round(sum(scores) / len(scores), 2) if scores else 0
        if "overall" not in avg:
            avg["overall"] = round(sum(v for k, v in avg.items()) / len(avg), 2) if avg else 0
        systems[system] = {
            "avg_scores": avg,
            "rank_points": sum(system_rank_points.get(system, [])),
            "hallucinations": hallucinations.get(system, []),
        }

    # Winner: primary = overall score, tiebreaker = rank_points (from judge rankings)
    if systems:
        all_zero = all(systems[s]["avg_scores"].get("overall", 0) == 0 for s in systems)
        if all_zero:
            # Scores failed to parse — fall back to rank points from judge rankings
            winner = max(systems, key=lambda s: systems[s].get("rank_points", 0))
        else:
            winner = max(systems, key=lambda s: (
                systems[s]["avg_scores"].get("overall", 0),
                systems[s].get("rank_points", 0),
            ))
    else:
        winner = "none"

    judge_winners = []
    for jr in judge_results:
        if "error" not in jr and jr.get("ranking"):
            judge_winners.append(label_to_system.get(jr["ranking"][0], "unknown"))
    judges_agree = len(set(judge_winners)) <= 1 if judge_winners else False

    return {
        "prompt_id": prompt["id"],
        "prompt_title": prompt["title"],
        "category": prompt["category"],
        "systems": systems,
        "winner": winner,
        "judges_agree": judges_agree,
        "judge_count": len([j for j in judge_results if "error" not in j]),
    }


def generate_r3_report(prompt_results: list[dict], full_agg: dict,
                        speed_data: dict, pipeline_logs: list) -> str:
    """Generate Round 3 commercial evaluation report."""
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(prompt_results)

    orch_wins = sum(1 for pr in prompt_results if pr["winner"] == "orchestrator")
    orch_rate = orch_wins / total if total else 0

    # Separate categories
    logistics = [pr for pr in prompt_results if pr["category"] == "logistics"]
    smb = [pr for pr in prompt_results if pr["category"] == "smb_growth"]
    log_wins = sum(1 for pr in logistics if pr["winner"] == "orchestrator")
    smb_wins = sum(1 for pr in smb if pr["winner"] == "orchestrator")

    lines.append("# Round 3 — Real-World Business Value Benchmark")
    lines.append(f"\nGenerated: {now}")
    lines.append(f"Total prompts: {total} (10 Logistics + 10 SMB Growth)")
    lines.append(f"Scoring: Commercial rubric (accuracy, usefulness, actionability, commercial value, freshness, clarity, assumptions, overall)")

    # EXECUTIVE SUMMARY
    lines.append("\n## Executive Summary\n")
    lines.append(f"- **Overall**: Orchestrator won **{orch_wins}/{total}** ({orch_rate:.0%})")
    lines.append(f"- **Logistics**: Orchestrator won **{log_wins}/{len(logistics)}**")
    lines.append(f"- **SMB Growth**: Orchestrator won **{smb_wins}/{len(smb)}**")

    # LEADERBOARD
    lines.append("\n## Overall Leaderboard\n")
    all_systems = {}
    for pr in prompt_results:
        for sys, data in pr.get("systems", {}).items():
            if sys not in all_systems:
                all_systems[sys] = {"scores": [], "wins": 0}
            all_systems[sys]["scores"].append(data["avg_scores"].get("overall", 0))
            if pr["winner"] == sys:
                all_systems[sys]["wins"] += 1

    lines.append("| Rank | System | Wins | Win Rate | Avg Score |")
    lines.append("|------|--------|------|----------|-----------|")
    ranked = sorted(all_systems.items(), key=lambda x: sum(x[1]["scores"])/len(x[1]["scores"]) if x[1]["scores"] else 0, reverse=True)
    for rank, (sys, data) in enumerate(ranked, 1):
        display = sys.replace("standalone_", "").replace("_", " ").title()
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        rate = data["wins"] / total if total else 0
        lines.append(f"| {rank} | {display} | {data['wins']} | {rate:.0%} | {avg:.1f} |")

    # LOGISTICS RESULTS
    lines.append("\n## Logistics / Freight Results\n")
    for pr in logistics:
        w = pr["winner"].replace("standalone_", "").replace("_", " ").title()
        agree = "unanimous" if pr.get("judges_agree") else "split"
        lines.append(f"- **{pr['prompt_title']}**: {w} ({agree})")

    # SMB RESULTS
    lines.append("\n## SMB Growth / Automation Results\n")
    for pr in smb:
        w = pr["winner"].replace("standalone_", "").replace("_", " ").title()
        agree = "unanimous" if pr.get("judges_agree") else "split"
        lines.append(f"- **{pr['prompt_title']}**: {w} ({agree})")

    # SPEED TABLE
    if speed_data:
        lines.append("\n## Response Speed\n")
        lines.append("| System | Avg Time | Fastest | Slowest |")
        lines.append("|--------|----------|---------|---------|")
        for sys, data in speed_data.items():
            display = sys.replace("standalone_", "").replace("_", " ").title()
            lines.append(f"| {display} | {data['avg']:.0f}s | {data['min']:.0f}s | {data['max']:.0f}s |")

    # DETAILED PER-PROMPT
    lines.append("\n## Per-Prompt Scores\n")
    dims = [d["name"] for d in DIMENSIONS_COMMERCIAL]
    for pr in prompt_results:
        w = pr["winner"].replace("standalone_", "").replace("_", " ").title()
        agree = "unanimous" if pr.get("judges_agree") else "split"
        lines.append(f"### {pr['prompt_id']}: {pr['prompt_title']}")
        lines.append(f"Winner: **{w}** ({agree})\n")
        lines.append("| System | " + " | ".join(d[:6].title() for d in dims) + " |")
        lines.append("|--------|" + "|".join("------" for _ in dims) + "|")
        sys_sorted = sorted(pr.get("systems", {}).items(), key=lambda x: x[1]["avg_scores"].get("overall", 0), reverse=True)
        for sys, data in sys_sorted:
            display = sys.replace("standalone_", "").replace("_", " ").title()
            vals = " | ".join(f"{data['avg_scores'].get(d, 0):.1f}" for d in dims)
            lines.append(f"| {display} | {vals} |")
        lines.append("")

    # WHERE ORCHESTRATOR LOSES
    losses = [pr for pr in prompt_results if pr["winner"] != "orchestrator"]
    lines.append("\n## Where the Orchestrator Loses\n")
    if losses:
        for pr in losses:
            w = pr["winner"].replace("standalone_", "").replace("_", " ").title()
            orch_s = pr.get("systems", {}).get("orchestrator", {}).get("avg_scores", {}).get("overall", 0)
            win_s = pr.get("systems", {}).get(pr["winner"], {}).get("avg_scores", {}).get("overall", 0)
            margin = win_s - orch_s
            lines.append(f"- **{pr['prompt_title']}** ({pr['category']}): Lost to {w} by {margin:.1f} pts")
    else:
        lines.append("The Orchestrator won every prompt.")

    # HALLUCINATION TRACKING
    lines.append("\n## Hallucination Report\n")
    all_halluc = {}
    for pr in prompt_results:
        for sys, data in pr.get("systems", {}).items():
            h = data.get("hallucinations", [])
            if h:
                display = sys.replace("standalone_", "").replace("_", " ").title()
                all_halluc.setdefault(display, []).extend(h)
    if all_halluc:
        for sys, items in all_halluc.items():
            lines.append(f"**{sys}**: {len(items)} instance(s)")
            for item in items[:3]:
                lines.append(f"  - {item[:100]}")
    else:
        lines.append("No hallucinations detected by judges.")

    # PIPELINE INTEGRITY
    if pipeline_logs:
        lines.append(generate_integrity_summary(pipeline_logs))

    # FINAL VERDICT
    lines.append("\n## Final Verdict\n")
    if orch_rate >= 0.7:
        lines.append("### **Keep Building — Commercial Opportunity Confirmed**\n")
        lines.append("The Orchestrator delivers consistently superior real-world business value. "
                      "Multi-model synthesis produces more accurate, actionable, and commercially useful outputs "
                      "across both logistics and SMB domains.")
    elif orch_rate >= 0.5:
        lines.append("### **Keep Building — With Focus**\n")
        lines.append("The Orchestrator adds genuine value but not universally. "
                      "Focus the product on the categories where it clearly wins.")
    elif orch_rate >= 0.3:
        lines.append("### **Pivot Recommended**\n")
        lines.append("The Orchestrator shows mixed results in real-world scenarios. "
                      "Consider repositioning as a comparison/transparency tool rather than a quality tool.")
    else:
        lines.append("### **Use Only Internally**\n")
        lines.append("Standalone models outperform the Orchestrator in most real-world business scenarios. "
                      "The synthesis overhead is not justified commercially.")

    best_for = "logistics" if log_wins > smb_wins else "SMB growth" if smb_wins > log_wins else "both equally"
    lines.append(f"\n**Best market fit**: {best_for}")

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://localhost:8099")
    parser.add_argument("--prompts", type=str, help="Comma-separated prompt IDs")
    parser.add_argument("--fresh", action="store_true", help="Ignore cached outputs, re-collect everything")
    args = parser.parse_args()

    profile = get_testing_profile()
    print(f"Testing profile: {profile['name']} — {profile['description']}")

    filter_ids = args.prompts.split(",") if args.prompts else None
    prompts = load_prompts(filter_ids)
    print(f"Round 3 Benchmark: {len(prompts)} prompts")
    print(f"App URL: {args.app_url}\n")

    cost_tracker = CostTracker()
    all_results = []
    pipeline_logs = []
    speed_records = {}

    for i, prompt in enumerate(prompts):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(prompts)}] {prompt['id']}: {prompt['title']}")
        print(f"  Category: {prompt['category']}")
        print(f"{'='*60}")

        cached = None if args.fresh else load_cached(prompt["id"])
        plog = None
        if cached:
            print(f"  CACHED: reusing {len(cached)} outputs")
            outputs = cached
        else:
            outputs, plog = await collect_for_prompt(prompt, args.app_url, cost_tracker)
            save_outputs(prompt["id"], outputs)
            print(f"  Saved {len(outputs)} outputs")

        if plog:
            print(f"  PIPELINE: {plog.summary_line()}")
            pipeline_logs.append(plog)

        for o in outputs:
            sys = o.get("system", "unknown")
            rt = o.get("runtime_ms", 0)
            if rt > 0:
                speed_records.setdefault(sys, []).append(rt)

        if not outputs:
            continue

        judge_results, key_map = await judge_outputs(prompt, outputs, cost_tracker)
        result = aggregate_r3_prompt(prompt, judge_results, key_map)
        all_results.append(result)

        w = result["winner"].replace("standalone_", "").replace("_", " ").title()
        agree = "unanimous" if result["judges_agree"] else "split"
        print(f"  >>> Winner: {w} ({agree})")

    # AGGREGATION
    print(f"\n{'='*60}")
    print("FINAL AGGREGATION")
    print(f"{'='*60}")

    full_agg = aggregate_full_evaluation(all_results)

    speed_data = {}
    for sys, times in speed_records.items():
        ts = [t / 1000 for t in times]
        speed_data[sys] = {"avg": sum(ts)/len(ts), "min": min(ts), "max": max(ts)}

    orch_wins = full_agg["win_counts"].get("orchestrator", 0)
    total = len(all_results)
    print(f"\nOrchestrator: {orch_wins}/{total} wins ({full_agg['win_rate'].get('orchestrator', 0):.0%})")
    print(f"Win counts: {full_agg['win_counts']}")

    logistics = [r for r in all_results if r["category"] == "logistics"]
    smb = [r for r in all_results if r["category"] == "smb_growth"]
    print(f"Logistics: {sum(1 for r in logistics if r['winner']=='orchestrator')}/{len(logistics)}")
    print(f"SMB: {sum(1 for r in smb if r['winner']=='orchestrator')}/{len(smb)}")

    if pipeline_logs:
        v = sum(1 for l in pipeline_logs if l.validity in ("VALID", "VALID_WITH_WARNINGS"))
        d = sum(1 for l in pipeline_logs if l.validity == "DEGRADED")
        inv = sum(1 for l in pipeline_logs if l.validity == "INVALID")
        print(f"Pipeline: VALID={v} DEGRADED={d} INVALID={inv}")
        plog_path = save_pipeline_logs(pipeline_logs)
        print(f"Pipeline log: {plog_path}")

    report = generate_r3_report(all_results, full_agg, speed_data, pipeline_logs)

    # Append cost summary
    cost_lines = cost_tracker.report_lines()
    report += "\n" + "\n".join(cost_lines)
    print(f"\nEstimated total cost: ${cost_tracker.total():.4f}")
    print(f"Profile: {profile['name']}")
    for line in cost_lines[2:]:  # skip header
        if line.strip():
            print(f"  {line.strip()}")

    results_json = {
        "round": "3-fixed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "testing_profile": profile["name"],
        "prompts": [p["id"] for p in prompts],
        "per_prompt": all_results,
        "aggregation": full_agg,
        "speed_data": speed_data,
        "cost_summary": cost_tracker.summary(),
        "cost_total": cost_tracker.total(),
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
