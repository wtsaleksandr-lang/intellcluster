#!/usr/bin/env python3
"""
Round 4 — Head-to-Head: Orchestrator vs Anthropic standalone.
Focused on understanding WHERE each system wins and WHY.

Usage:
    python evaluation/run_round4.py --app-url http://localhost:8099
    python evaluation/run_round4.py --app-url http://localhost:8099 --fresh
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
from synthesis.evaluation.cost_profiles import get_testing_profile, CostTracker
from synthesis.evaluation.rubric import DIMENSIONS_COMMERCIAL
from synthesis.evaluation.aggregator import save_report


OUTPUTS_DIR = Path("evaluation/outputs")
R4_PROMPTS = Path("evaluation/round4_prompts.json")

# Category mapping to valid backend categories
CAT_MAP = {
    "strategy": "decision_strategy",
    "contradiction": "decision_strategy",
    "planning": "decision_strategy",
    "competitive": "competitor_market_research",
    "pricing": "product_offer_design",
    "architecture": "ai_systems_automation",
    "logistics": "deep_research",
    "smb": "marketing_growth",
    "risk": "deep_research",
    "messy": "decision_strategy",
}


def load_prompts(ids=None):
    with open(R4_PROMPTS) as f:
        prompts = json.load(f)
    return [p for p in prompts if p["id"] in ids] if ids else prompts


def save_outputs(pid, outputs):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / f"{pid}.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")


def load_cached(pid):
    p = OUTPUTS_DIR / f"{pid}.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        systems = {o.get("system") for o in d}
        if "orchestrator" in systems and "standalone_anthropic" in systems and all(o.get("final_output") for o in d):
            return d
    return None


async def collect(prompt, app_url, ct):
    text = prompt["prompt"]
    cat = CAT_MAP.get(prompt["category"], "deep_research")
    outputs = []
    plog = PipelineExecutionLog(prompt["id"], prompt["title"], prompt["category"])

    # Orchestrator
    print(f"  [orchestrator] collecting...", end="", flush=True)
    try:
        t0 = time.time()
        out = await collect_app_output(text, cat, base_url=app_url, pipeline_log=plog)
        out["prompt_id"] = prompt["id"]
        out["timestamp"] = datetime.now(timezone.utc).isoformat()
        outputs.append(out)
        olen = len(out.get("final_output", ""))
        print(f" {olen} chars, {time.time()-t0:.0f}s")
    except Exception as e:
        print(f" FAILED: {e}")
        plog.errors.append(str(e))

    # Anthropic standalone
    key = settings.anthropic_api_key
    if key:
        print(f"  [anthropic] collecting...", end="", flush=True)
        try:
            t0 = time.time()
            out = await collect_standalone_output(text, "anthropic", key)
            out["prompt_id"] = prompt["id"]
            out["timestamp"] = datetime.now(timezone.utc).isoformat()
            outputs.append(out)
            olen = len(out.get("final_output", ""))
            print(f" {olen} chars, {time.time()-t0:.0f}s")
            ct.record("standalone_anthropic", out.get("model", "claude-sonnet-4-6"), "collection", len(text), olen)
        except Exception as e:
            print(f" FAILED: {e}")

    plog.mode = "standard"
    plog.finalize(0)
    return outputs, plog


async def judge(prompt, outputs, ct):
    valid = [o for o in outputs if o.get("final_output")]
    if len(valid) < 2:
        return [], {}

    anon, key_map = anonymize_responses(valid)
    profile = get_testing_profile()

    judges = [
        ("judge_openai", settings.openai_api_key, profile["judge_models"].get("judge_openai")),
        ("judge_google", settings.google_api_key, profile["judge_models"].get("judge_google")),
        ("judge_anthropic", settings.anthropic_api_key, profile["judge_models"].get("judge_anthropic")),
    ]

    results = []
    for jname, key, model in judges:
        if not key:
            continue
        print(f"  [{jname}] ({model})...", end="", flush=True)
        try:
            r = await run_judge(jname, key, prompt["prompt"], anon, commercial=True, model_override=model)
            if "error" in r:
                print(f" err: {r['error'][:50]}")
            else:
                ranking = r.get("ranking", [])
                w = key_map.get(ranking[0], "?") if ranking else "?"
                print(f" -> {w}")
                ct.record(jname, model, "judge", len(prompt["prompt"]) + sum(len(v) for v in anon.values()), 2000)
            results.append(r)
        except Exception as e:
            print(f" FAILED: {e}")
            results.append({"error": str(e)})

    return results, key_map


def score_prompt(prompt, judge_results, key_map):
    systems = {}
    for jr in judge_results:
        if "error" in jr:
            continue
        evals = jr.get("evaluations", {})
        ranking = jr.get("ranking", [])
        explanation = jr.get("explanation", "")

        for label, scores in evals.items():
            sys = key_map.get(label, "unknown")
            if sys not in systems:
                systems[sys] = {"scores": {d["name"]: [] for d in DIMENSIONS_COMMERCIAL}, "rank_pts": [], "explanations": [], "hallucinations": []}
            for d in DIMENSIONS_COMMERCIAL:
                v = scores.get(d["name"])
                if isinstance(v, (int, float)):
                    systems[sys]["scores"][d["name"]].append(v)
            h = scores.get("hallucinations", "")
            if h and "none" not in h.lower():
                systems[sys]["hallucinations"].append(h)

        for i, label in enumerate(ranking):
            sys = key_map.get(label, "unknown")
            if sys not in systems:
                systems[sys] = {"scores": {}, "rank_pts": [], "explanations": [], "hallucinations": []}
            systems[sys]["rank_pts"].append(len(ranking) - i)

        # Track which system won per judge + explanation
        if ranking:
            winner_sys = key_map.get(ranking[0], "unknown")
            systems.setdefault(winner_sys, {}).setdefault("explanations", []).append(explanation)

    # Average scores
    for sys in systems:
        avg = {}
        for dim, vals in systems[sys].get("scores", {}).items():
            avg[dim] = round(sum(vals) / len(vals), 1) if vals else 0
        if avg:
            avg["overall"] = round(sum(avg.values()) / len(avg), 1)
        systems[sys]["avg_scores"] = avg
        systems[sys]["total_rank_pts"] = sum(systems[sys].get("rank_pts", []))

    # Winner
    if systems:
        all_zero = all(systems[s].get("avg_scores", {}).get("overall", 0) == 0 for s in systems)
        if all_zero:
            winner = max(systems, key=lambda s: systems[s].get("total_rank_pts", 0))
        else:
            winner = max(systems, key=lambda s: (systems[s].get("avg_scores", {}).get("overall", 0), systems[s].get("total_rank_pts", 0)))
    else:
        winner = "none"

    judge_winners = []
    for jr in judge_results:
        if "error" not in jr and jr.get("ranking"):
            judge_winners.append(key_map.get(jr["ranking"][0], "unknown"))
    unanimous = len(set(judge_winners)) <= 1 if judge_winners else False

    return {
        "prompt_id": prompt["id"],
        "prompt_title": prompt["title"],
        "category": prompt["category"],
        "winner": winner,
        "unanimous": unanimous,
        "systems": {s: {"avg_scores": d.get("avg_scores", {}), "rank_pts": d.get("total_rank_pts", 0),
                         "hallucinations": d.get("hallucinations", []), "explanations": d.get("explanations", [])}
                    for s, d in systems.items()},
    }


def gen_report(results, plogs, speed, ct):
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(results)
    orch_w = sum(1 for r in results if r["winner"] == "orchestrator")
    anth_w = sum(1 for r in results if r["winner"] == "standalone_anthropic")

    lines.append("# Round 4 — Head-to-Head: Orchestrator vs Claude")
    lines.append(f"\nGenerated: {now}")
    lines.append(f"Prompts: {total}")

    lines.append("\n## Final Score\n")
    lines.append(f"| System | Wins | Rate |")
    lines.append(f"|--------|------|------|")
    lines.append(f"| **Orchestrator** | **{orch_w}** | **{orch_w/total*100:.0f}%** |")
    lines.append(f"| **Claude Standalone** | **{anth_w}** | **{anth_w/total*100:.0f}%** |")

    # By category
    cats = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"orch": 0, "anth": 0})
        if r["winner"] == "orchestrator":
            cats[c]["orch"] += 1
        else:
            cats[c]["anth"] += 1

    lines.append("\n## Win Map by Category\n")
    lines.append("| Category | Orchestrator | Claude | Edge |")
    lines.append("|----------|-------------|--------|------|")
    for c in sorted(cats):
        o, a = cats[c]["orch"], cats[c]["anth"]
        edge = "Orchestrator" if o > a else "Claude" if a > o else "Tie"
        lines.append(f"| {c.title()} | {o} | {a} | {edge} |")

    # Per-prompt detail with WHY
    lines.append("\n## Per-Prompt Results + Analysis\n")
    for r in results:
        w = "Orchestrator" if r["winner"] == "orchestrator" else "Claude"
        u = "unanimous" if r["unanimous"] else "split"
        lines.append(f"### {r['prompt_id']}: {r['prompt_title']}")
        lines.append(f"**Category:** {r['category']} | **Winner:** {w} ({u})\n")

        # Scores
        orch_s = r["systems"].get("orchestrator", {}).get("avg_scores", {})
        anth_s = r["systems"].get("standalone_anthropic", {}).get("avg_scores", {})
        if orch_s or anth_s:
            dims = [d["name"] for d in DIMENSIONS_COMMERCIAL if d["name"] != "overall"]
            lines.append("| Dim | Orchestrator | Claude | Delta |")
            lines.append("|-----|-------------|--------|-------|")
            for d in dims:
                ov = orch_s.get(d, 0)
                av = anth_s.get(d, 0)
                delta = ov - av
                marker = "+" if delta > 0 else ""
                lines.append(f"| {d[:12]} | {ov} | {av} | {marker}{delta:.1f} |")
            ov = orch_s.get("overall", 0)
            av = anth_s.get("overall", 0)
            lines.append(f"| **Overall** | **{ov}** | **{av}** | **{'+' if ov-av>0 else ''}{ov-av:.1f}** |")

        # WHY analysis
        winner_sys = r["systems"].get(r["winner"], {})
        expl = winner_sys.get("explanations", [])
        if expl:
            lines.append(f"\n**Why {w} won:** {expl[0][:200]}")

        # Hallucinations
        for sys_name, sys_data in r["systems"].items():
            h = sys_data.get("hallucinations", [])
            if h:
                display = "Orchestrator" if sys_name == "orchestrator" else "Claude"
                lines.append(f"\n**Hallucination ({display}):** {h[0][:150]}")

        lines.append("")

    # Strengths / Weaknesses summary
    lines.append("\n## Orchestrator Strengths\n")
    orch_wins = [r for r in results if r["winner"] == "orchestrator"]
    orch_cats = [r["category"] for r in orch_wins]
    from collections import Counter
    for cat, cnt in Counter(orch_cats).most_common():
        lines.append(f"- **{cat.title()}**: {cnt} wins")

    lines.append("\n## Orchestrator Weaknesses\n")
    orch_losses = [r for r in results if r["winner"] != "orchestrator"]
    loss_cats = [r["category"] for r in orch_losses]
    for cat, cnt in Counter(loss_cats).most_common():
        lines.append(f"- **{cat.title()}**: {cnt} losses")

    # Routing recommendations
    lines.append("\n## Routing Improvement Recommendations\n")
    for cat in sorted(cats):
        o, a = cats[cat]["orch"], cats[cat]["anth"]
        if a > o:
            lines.append(f"- **{cat.title()}**: Claude wins {a}/{o+a}. Consider: let Claude lead synthesis for this category, reduce model count, use direct Claude call.")
        elif o > a:
            lines.append(f"- **{cat.title()}**: Orchestrator wins {o}/{o+a}. Keep full multi-model pipeline.")
        else:
            lines.append(f"- **{cat.title()}**: Tied {o}-{a}. Monitor — could go either way.")

    # Speed
    if speed:
        lines.append("\n## Response Speed\n")
        lines.append("| System | Avg | Min | Max |")
        lines.append("|--------|-----|-----|-----|")
        for s, d in speed.items():
            display = "Orchestrator" if s == "orchestrator" else "Claude"
            lines.append(f"| {display} | {d['avg']:.0f}s | {d['min']:.0f}s | {d['max']:.0f}s |")

    # Cost
    lines.append("\n" + "\n".join(ct.report_lines()))

    # Pipeline integrity
    if plogs:
        lines.append(generate_integrity_summary(plogs))

    # Final verdict
    lines.append("\n## Final Verdict\n")
    if orch_w > anth_w * 1.5:
        lines.append("**Stay hybrid.** The orchestrator clearly outperforms standalone Claude. Multi-model synthesis is the product's core value.")
    elif orch_w > anth_w:
        lines.append("**Stay hybrid with smart routing.** The orchestrator wins more often but Claude is competitive. Route simple/expert prompts to Claude-led, complex/multi-faceted to full pipeline.")
    elif orch_w == anth_w:
        lines.append("**Pivot to Claude-led with optional multi-model.** Equal performance means the orchestrator's added cost and latency aren't justified for all prompts. Let Claude lead, use multi-model as a premium option.")
    else:
        lines.append("**Consider Claude-led architecture.** Claude standalone wins more often. The orchestrator should focus only on categories where it demonstrably wins.")

    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-url", default="http://localhost:8099")
    parser.add_argument("--prompts", type=str)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    profile = get_testing_profile()
    print(f"Profile: {profile['name']}")

    ids = args.prompts.split(",") if args.prompts else None
    prompts = load_prompts(ids)
    print(f"Round 4: {len(prompts)} prompts — Orchestrator vs Claude\n")

    ct = CostTracker()
    results = []
    plogs = []
    speed = {}

    for i, p in enumerate(prompts):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(prompts)}] {p['id']}: {p['title']} [{p['category']}]")
        print(f"{'='*60}")

        cached = None if args.fresh else load_cached(p["id"])
        plog = None
        if cached:
            print(f"  CACHED ({len(cached)} outputs)")
            outputs = cached
        else:
            outputs, plog = await collect(p, args.app_url, ct)
            save_outputs(p["id"], outputs)
            if plog:
                print(f"  PIPELINE: {plog.summary_line()}")
                plogs.append(plog)

        for o in outputs:
            s = o.get("system", "unknown")
            rt = o.get("runtime_ms", 0)
            if rt > 0:
                speed.setdefault(s, []).append(rt / 1000)

        if not outputs or len(outputs) < 2:
            continue

        jr, km = await judge(p, outputs, ct)
        r = score_prompt(p, jr, km)
        results.append(r)

        w = "Orchestrator" if r["winner"] == "orchestrator" else "Claude"
        u = "unanimous" if r["unanimous"] else "split"
        print(f"  >>> {w} ({u})")

    # Final
    print(f"\n{'='*60}")
    print("FINAL")
    print(f"{'='*60}")

    orch_w = sum(1 for r in results if r["winner"] == "orchestrator")
    anth_w = sum(1 for r in results if r["winner"] == "standalone_anthropic")
    print(f"Orchestrator: {orch_w}/{len(results)}")
    print(f"Claude: {anth_w}/{len(results)}")
    print(f"Cost: ${ct.total():.4f}")

    speed_data = {}
    for s, times in speed.items():
        speed_data[s] = {"avg": sum(times)/len(times), "min": min(times), "max": max(times)}

    report = gen_report(results, plogs, speed_data, ct)
    rjson = {
        "round": 4,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": profile["name"],
        "per_prompt": results,
        "orchestrator_wins": orch_w,
        "anthropic_wins": anth_w,
        "cost": ct.total(),
        "speed": speed_data,
    }

    md, js = save_report(report, rjson)
    print(f"\nReport: {md}")

    if plogs:
        save_pipeline_logs(plogs)


if __name__ == "__main__":
    asyncio.run(main())
