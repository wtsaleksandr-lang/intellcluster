"""
Blind LLM-judge for IntellCluster eval runs.

For each blind-pair file produced by run_baseline.py, sends the question
+ grading guide + all anonymized answers to Claude Sonnet 4.6 with the
50-point rubric, and asks for a JSON scoring matrix. Unblinds afterward
via the label_map_DO_NOT_SHOW_GRADER kept in the runner output.

The judge sees only A/B/C/D labels — never the source of each answer —
preventing model preference bias. (Sonnet judging Sonnet output is a
known weak spot but it doesn't know which is which.)

Run from repo root:
    .venv/Scripts/python.exe evals/v1/judge_blind.py <run_dir>

Output: <run_dir>/scored.json + <run_dir>/SUMMARY.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx


JUDGE_MODEL = "claude-sonnet-4-6"


JUDGE_SYSTEM = """You are a strict, blind grader for an AI accuracy benchmark.

You will receive:
1. A question (decision or research)
2. A grading guide describing what a strong answer looks like
3. Multiple anonymized answers labeled A, B, C, D, ...

Score each answer on 5 dimensions, 0-10 each:

1. **correctness** — Does it align with the grading guide's strong-answer criteria? Is the conclusion right? 10 = aligns with grading guide. 0 = wrong, against grading guide.

2. **completeness** — Does it address all major angles the grading guide expects? 10 = covers everything. 0 = misses the actual question.

3. **hallucination_freedom** — Are facts, sources, numbers verifiable? 10 = no fabrications. 0 = riddled with invented "facts" stated authoritatively.

4. **calibration** — Does expressed confidence match actual reliability? 10 = appropriately hedged where uncertain, confident where right. 0 = confidently wrong, OR hedges everything to avoid commitment.

5. **specificity** — Specific numbers, names, recommendations vs vague platitudes. 10 = concrete and actionable. 0 = pure "it depends" hedging.

Rules:
- Score blind. Do NOT try to identify which model wrote which answer.
- Don't penalize length. A short right answer outscores a long wrong one.
- A confidently wrong answer scores 0 on correctness AND 0 on calibration.
- Hedging without commitment is 0 on specificity, NOT 10 on calibration.
- A claim that cites a study by name that doesn't exist is a hallucination.

Output strict JSON only:
{
  "A": {"correctness": int, "completeness": int, "hallucination_freedom": int, "calibration": int, "specificity": int, "notes": "1-2 sentences on what stood out"},
  "B": {...},
  ...
}

No prose before or after the JSON."""


def build_user_prompt(case_blind: dict, grading_guide: str) -> str:
    parts = [
        f"## Question",
        case_blind["question"],
        "",
        f"## Kind",
        case_blind["kind"],
        "",
        f"## Grading guide",
        grading_guide,
        "",
        f"## Answers (anonymized)",
    ]
    for ans in case_blind["answers_blind"]:
        parts.append("")
        parts.append(f"### Answer {ans['label']}")
        parts.append(ans["content"])
    parts.append("")
    parts.append("Return strict JSON with scores for each labeled answer.")
    return "\n".join(parts)


async def call_judge(case_blind: dict, grading_guide: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        return {"error": "no ANTHROPIC_API_KEY"}
    user_prompt = build_user_prompt(case_blind, grading_guide)
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
                    "model": JUDGE_MODEL,
                    "max_tokens": 2500,
                    "system": JUDGE_SYSTEM,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            # Extract JSON from possibly-prosy response
            m = re.search(r"\{[\s\S]*\}", text)
            if not m:
                return {"error": "no JSON in response", "raw": text[:300]}
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e:
                return {"error": f"json parse: {e}", "raw": text[:300]}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def load_grading_guides(cases_file: Path) -> dict:
    cases_data = json.loads(cases_file.read_text(encoding="utf-8"))
    guides = {}
    for c in cases_data["decisions"] + cases_data["research"]:
        guides[c["id"]] = c.get("grading_guide", "")
    return guides


def total_for_label(scores: dict) -> int:
    if not isinstance(scores, dict):
        return 0
    return sum(int(scores.get(k, 0)) for k in ["correctness", "completeness", "hallucination_freedom", "calibration", "specificity"])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", help="Path to runs/ts_*/ directory produced by run_baseline.py")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}")
        sys.exit(1)

    blind_dir = run_dir / "blind_pairs"
    if not blind_dir.is_dir():
        print(f"ERROR: no blind_pairs/ subdirectory")
        sys.exit(1)

    grading_guides = load_grading_guides(ROOT / "evals" / "v1" / "cases.json")

    blind_files = sorted(blind_dir.glob("*.json"))
    print(f"Grading {len(blind_files)} cases…")

    scored_cases: list[dict] = []
    # source -> list of total scores
    source_totals: dict[str, list[int]] = defaultdict(list)
    # source -> per-dim sums
    source_dims: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for bfile in blind_files:
        bdata = json.loads(bfile.read_text(encoding="utf-8"))
        cid = bdata["case_id"]
        guide = grading_guides.get(cid, "")
        if not guide:
            print(f"  [skip] {cid}: no grading guide")
            continue
        scores = await call_judge(bdata, guide)
        if "error" in scores:
            print(f"  [err]  {cid}: {scores['error']}")
            scored_cases.append({"case_id": cid, "error": scores["error"]})
            continue
        # Unblind: map labels -> source
        label_map = bdata.get("label_map_DO_NOT_SHOW_GRADER", {})
        per_source = {}
        for label, src in label_map.items():
            s = scores.get(label, {})
            tot = total_for_label(s)
            per_source[src] = {**s, "total": tot}
            source_totals[src].append(tot)
            for dim in ["correctness", "completeness", "hallucination_freedom", "calibration", "specificity"]:
                if dim in s:
                    source_dims[src][dim].append(int(s[dim]))
        scored_cases.append({
            "case_id": cid,
            "kind": bdata["kind"],
            "question": bdata["question"],
            "scores": per_source,
        })
        # Quick log line
        line = f"  [ok]   {cid}:"
        for src, info in per_source.items():
            line += f" {src.split('_')[0]}={info.get('total', '?'):2d}"
        print(line)
        sys.stdout.flush()

    # Aggregate
    summary = {"per_source": {}}
    for src, totals in source_totals.items():
        if not totals:
            continue
        avg_total = sum(totals) / len(totals)
        per_dim_avg = {dim: round(sum(scores) / len(scores), 2) for dim, scores in source_dims[src].items() if scores}
        summary["per_source"][src] = {
            "n": len(totals),
            "avg_total": round(avg_total, 2),
            "min_total": min(totals),
            "max_total": max(totals),
            "per_dim_avg": per_dim_avg,
        }

    output = {
        "run_dir": str(run_dir),
        "judge_model": JUDGE_MODEL,
        "summary": summary,
        "cases": scored_cases,
    }
    out_path = run_dir / "scored.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    # Markdown summary
    md = ["# IntellCluster Eval — Scored Results", ""]
    md.append(f"Run: `{run_dir.name}`  ·  Judge: `{JUDGE_MODEL}`")
    md.append(f"Cases scored: {len(scored_cases)} (errors excluded from totals)")
    md.append("")
    md.append("## Per-source averages (max 50 per case)")
    md.append("")
    md.append("| Source | n | Avg total | Min | Max | Correct | Complete | Halluc-free | Calib | Specific |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    # Order: solo baselines first, orchestration last
    order = ["gpt4o_solo", "sonnet_solo", "gemini_solo", "intellcluster"]
    for src in order:
        if src not in summary["per_source"]:
            continue
        s = summary["per_source"][src]
        d = s["per_dim_avg"]
        md.append(
            f"| {src} | {s['n']} | **{s['avg_total']}** | {s['min_total']} | {s['max_total']} | "
            f"{d.get('correctness', '?')} | {d.get('completeness', '?')} | "
            f"{d.get('hallucination_freedom', '?')} | {d.get('calibration', '?')} | "
            f"{d.get('specificity', '?')} |"
        )
    md.append("")
    md.append("## Per-case totals")
    md.append("")
    md.append("| Case | Kind | GPT-4o | Sonnet | Gemini | IntellCluster |")
    md.append("|---|---|---|---|---|---|")
    for c in scored_cases:
        if "error" in c:
            md.append(f"| {c['case_id']} | err | - | - | - | - |")
            continue
        s = c["scores"]
        def t(src):
            return str(s.get(src, {}).get("total", "-"))
        md.append(f"| {c['case_id']} | {c['kind'][:3]} | {t('gpt4o_solo')} | {t('sonnet_solo')} | {t('gemini_solo')} | {t('intellcluster')} |")

    md_path = run_dir / "SUMMARY.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print(f"\nScored: {len(scored_cases)} cases")
    print(f"Saved: {out_path}")
    print(f"Summary: {md_path}")
    if "per_source" in summary:
        print("\n=== Averages ===")
        for src in order:
            if src in summary["per_source"]:
                print(f"  {src:20s} avg={summary['per_source'][src]['avg_total']:5.2f} (n={summary['per_source'][src]['n']})")


if __name__ == "__main__":
    asyncio.run(main())
