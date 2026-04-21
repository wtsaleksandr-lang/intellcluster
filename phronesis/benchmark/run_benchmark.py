#!/usr/bin/env python3
"""
Phronesis — Quality Benchmark.
Runs 20 test prompts, collects outputs, evaluates with independent judges, produces report.

Usage:
    python benchmark/run_benchmark.py
    python benchmark/run_benchmark.py --prompts D01,D02,D03  # specific prompts only
    python benchmark/run_benchmark.py --skip-collect           # re-evaluate cached outputs
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

from phronesis.benchmark.collector import collect_output
from phronesis.benchmark.evaluator import evaluate_single, aggregate_eval
from phronesis.benchmark.rubric import DIMENSIONS

PROMPTS_FILE = Path("benchmark/test_prompts.json")
OUTPUTS_DIR = Path("benchmark/outputs")
REPORTS_DIR = Path("benchmark/reports")


def load_prompts(filter_ids: list[str] | None = None) -> list[dict]:
    with open(PROMPTS_FILE) as f:
        prompts = json.load(f)
    if filter_ids:
        prompts = [p for p in prompts if p["id"] in filter_ids]
    return prompts


def save_output(prompt_id: str, output: dict):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cached_output(prompt_id: str) -> dict | None:
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("winner") and not data.get("error"):
            return data
    return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", type=str, default=None, help="Comma-separated prompt IDs")
    parser.add_argument("--skip-collect", action="store_true", help="Skip collection, re-evaluate cached outputs")
    args = parser.parse_args()

    filter_ids = args.prompts.split(",") if args.prompts else None
    prompts = load_prompts(filter_ids)

    print("=" * 60)
    print("DECISION INTELLIGENCE TOOL - QUALITY BENCHMARK")
    print("=" * 60)
    print(f"Prompts: {len(prompts)}")
    print(f"Skip collect: {args.skip_collect}")
    print()

    # ─── Phase 1: Collect outputs ───
    print("PHASE 1: COLLECTING OUTPUTS")
    print("-" * 40)

    outputs = {}  # prompt_id -> output
    total_cost = 0
    total_latency = 0

    for i, prompt in enumerate(prompts):
        prompt_id = prompt["id"]

        if args.skip_collect:
            cached = load_cached_output(prompt_id)
            if cached:
                print(f"  [{i+1}/{len(prompts)}] {prompt_id}: CACHED (winner={cached['winner']})")
                outputs[prompt_id] = cached
                continue
            else:
                print(f"  [{i+1}/{len(prompts)}] {prompt_id}: no cache, collecting...")

        print(f"  [{i+1}/{len(prompts)}] {prompt_id}: {prompt['title']}...", end="", flush=True)
        try:
            output = await collect_output(prompt)
            save_output(prompt_id, output)
            outputs[prompt_id] = output
            total_cost += output.get("cost_usd", 0)
            total_latency += output.get("latency_ms", 0)
            print(f" winner={output['winner']}, {output['latency_ms']}ms, ${output.get('cost_usd', 0):.4f}")
        except Exception as e:
            print(f" FAILED: {e}")
            outputs[prompt_id] = {"prompt_id": prompt_id, "error": str(e)[:200]}

    successful = [pid for pid, o in outputs.items() if not o.get("error")]
    print(f"\nCollected: {len(successful)}/{len(prompts)} successful")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Avg latency: {total_latency / len(successful):.0f}ms" if successful else "")

    # ─── Phase 2: Evaluate outputs ───
    print(f"\nPHASE 2: EVALUATING OUTPUTS")
    print("-" * 40)

    eval_results = {}  # prompt_id -> aggregated eval

    for i, prompt in enumerate(prompts):
        prompt_id = prompt["id"]
        output = outputs.get(prompt_id)
        if not output or output.get("error"):
            print(f"  [{i+1}/{len(prompts)}] {prompt_id}: SKIPPED (no output)")
            continue

        print(f"  [{i+1}/{len(prompts)}] {prompt_id}: evaluating...", end="", flush=True)
        try:
            judge_results = await evaluate_single(prompt, output)
            agg = aggregate_eval(judge_results)
            eval_results[prompt_id] = {
                "prompt": prompt,
                "output": output,
                "evaluation": agg,
                "raw_judges": judge_results,
            }
            print(f" overall={agg['avg_overall']:.1f}/10, evals={agg['eval_count']}")
        except Exception as e:
            print(f" FAILED: {e}")

    # ─── Phase 3: Generate report ───
    print(f"\nPHASE 3: GENERATING REPORT")
    print("-" * 40)

    report = generate_report(prompts, outputs, eval_results)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = REPORTS_DIR / f"benchmark_{ts}.md"
    json_path = REPORTS_DIR / f"benchmark_{ts}.json"

    md_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts_total": len(prompts),
        "prompts_successful": len(successful),
        "eval_results": {
            pid: {
                "prompt_id": pid,
                "winner": data["output"].get("winner"),
                "confidence": data["output"].get("confidence"),
                "avg_overall": data["evaluation"]["avg_overall"],
                "avg_scores": data["evaluation"]["avg_scores"],
                "verdicts": data["evaluation"]["verdicts"],
            }
            for pid, data in eval_results.items()
        },
        "total_cost_usd": total_cost,
        "avg_latency_ms": total_latency / len(successful) if successful else 0,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nReport saved:")
    print(f"  Markdown: {md_path}")
    print(f"  JSON: {json_path}")
    print()

    # Print summary
    if eval_results:
        all_overall = [d["evaluation"]["avg_overall"] for d in eval_results.values()]
        avg = sum(all_overall) / len(all_overall)
        best = max(eval_results.items(), key=lambda x: x[1]["evaluation"]["avg_overall"])
        worst = min(eval_results.items(), key=lambda x: x[1]["evaluation"]["avg_overall"])

        print(f"SUMMARY:")
        print(f"  Average quality: {avg:.1f}/10")
        print(f"  Best:  {best[0]} ({best[1]['evaluation']['avg_overall']:.1f}/10)")
        print(f"  Worst: {worst[0]} ({worst[1]['evaluation']['avg_overall']:.1f}/10)")

        # Dimension averages
        dim_avgs = {d["name"]: [] for d in DIMENSIONS}
        for data in eval_results.values():
            for dim_name, score in data["evaluation"]["avg_scores"].items():
                if dim_name in dim_avgs:
                    dim_avgs[dim_name].append(score)

        print(f"\n  Dimension averages:")
        for dim in DIMENSIONS:
            scores = dim_avgs[dim["name"]]
            avg_s = sum(scores) / len(scores) if scores else 0
            print(f"    {dim['label']}: {avg_s:.1f}/10")


def generate_report(prompts, outputs, eval_results) -> str:
    """Generate markdown benchmark report."""
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# Phronesis - Quality Benchmark Report")
    lines.append(f"\nGenerated: {now}")
    lines.append(f"Prompts evaluated: {len(eval_results)}/{len(prompts)}")

    # Overall scores
    if eval_results:
        all_overall = [d["evaluation"]["avg_overall"] for d in eval_results.values()]
        avg = sum(all_overall) / len(all_overall)
        lines.append(f"\n## Overall Quality: {avg:.1f}/10\n")

        # Dimension breakdown
        lines.append("## Dimension Scores\n")
        lines.append("| Dimension | Avg Score | Assessment |")
        lines.append("|-----------|----------|------------|")

        dim_avgs = {d["name"]: [] for d in DIMENSIONS}
        for data in eval_results.values():
            for dim_name, score in data["evaluation"]["avg_scores"].items():
                if dim_name in dim_avgs:
                    dim_avgs[dim_name].append(score)

        for dim in DIMENSIONS:
            scores = dim_avgs[dim["name"]]
            avg_s = sum(scores) / len(scores) if scores else 0
            assessment = "Strong" if avg_s >= 7.5 else "Good" if avg_s >= 6 else "Needs work" if avg_s >= 4.5 else "Weak"
            lines.append(f"| {dim['label']} | {avg_s:.1f} | {assessment} |")

        # Per-prompt results
        lines.append("\n## Per-Prompt Results\n")
        lines.append("| ID | Title | Winner | Confidence | Quality | Verdict |")
        lines.append("|----|-------|--------|------------|---------|---------|")

        for pid, data in sorted(eval_results.items()):
            prompt = data["prompt"]
            output = data["output"]
            evl = data["evaluation"]
            verdict = evl["verdicts"][0][:60] + "..." if evl["verdicts"] else "N/A"
            lines.append(
                f"| {pid} | {prompt['title']} | {output.get('winner', 'N/A')} | "
                f"{output.get('confidence', 'N/A')} ({output.get('confidence_score', 'N/A')}) | "
                f"{evl['avg_overall']:.1f}/10 | {verdict} |"
            )

        # Category breakdown
        lines.append("\n## By Category\n")
        categories = {}
        for data in eval_results.values():
            cat = data["prompt"].get("category", "unknown")
            categories.setdefault(cat, []).append(data["evaluation"]["avg_overall"])

        for cat, scores in sorted(categories.items()):
            avg_c = sum(scores) / len(scores)
            lines.append(f"- **{cat.title()}**: {avg_c:.1f}/10 ({len(scores)} prompts)")

        # Weakest areas
        lines.append("\n## Improvement Areas\n")
        dim_sorted = sorted(dim_avgs.items(), key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0)
        for dim_name, scores in dim_sorted[:3]:
            avg_s = sum(scores) / len(scores) if scores else 0
            label = next(d["label"] for d in DIMENSIONS if d["name"] == dim_name)
            lines.append(f"- **{label}** ({avg_s:.1f}/10): Lowest scoring dimension.")

        # Verdict
        lines.append("\n## Verdict\n")
        if avg >= 7.5:
            lines.append("Phronesis produces **high-quality** recommendations across categories. Ready for public beta.")
        elif avg >= 6.0:
            lines.append("The tool produces **good quality** recommendations. Some dimensions need polish before broad launch.")
        elif avg >= 4.5:
            lines.append("Output quality is **mixed**. Workflow improvements needed before public testing.")
        else:
            lines.append("Output quality is **below threshold**. Significant engine work needed.")

    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(main())
