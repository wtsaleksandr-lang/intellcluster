"""
Compare two eval runs (typically v1 baseline vs v2 architecture).

Usage:
    python evals/v1/compare.py <baseline_run_dir> <v2_run_dir> [--out RESULTS.md]

Both directories must contain a `scored.json` from judge_blind.py. Produces
a markdown report with per-source averages, deltas, per-case wins/losses,
and statistical sanity checks (paired Wilcoxon-style observations).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, stdev


def load_scored(run_dir: Path) -> dict:
    p = run_dir / "scored.json"
    if not p.exists():
        raise FileNotFoundError(f"missing scored.json in {run_dir}")
    return json.loads(p.read_text(encoding="utf-8"))


def per_case_totals(scored: dict, source: str) -> dict[str, int]:
    """case_id -> total score for `source`. Skips cases where this source errored."""
    out = {}
    for c in scored.get("cases", []):
        if "error" in c:
            continue
        s = c.get("scores", {}).get(source)
        if s and "total" in s:
            out[c["case_id"]] = s["total"]
    return out


def wilcoxon_summary(deltas: list[int]) -> str:
    """Quick non-parametric sense of significance — count of positive / negative / zero."""
    pos = sum(1 for d in deltas if d > 0)
    neg = sum(1 for d in deltas if d < 0)
    zero = sum(1 for d in deltas if d == 0)
    return f"{pos} wins / {neg} losses / {zero} ties (n={len(deltas)})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline_run", help="Path to baseline scored run directory")
    ap.add_argument("v2_run", help="Path to v2 scored run directory")
    ap.add_argument("--out", default=None, help="Output markdown path (default: alongside v2 run)")
    args = ap.parse_args()

    base_dir = Path(args.baseline_run)
    v2_dir = Path(args.v2_run)
    out_path = Path(args.out) if args.out else v2_dir / "RESULTS.md"

    base = load_scored(base_dir)
    v2 = load_scored(v2_dir)

    sources = ["gpt4o_solo", "sonnet_solo", "gemini_solo", "intellcluster"]

    md = ["# IntellCluster v2 Architecture — Eval Results", ""]
    md.append(f"Baseline run: `{base_dir.name}`  ·  V2 run: `{v2_dir.name}`")
    md.append(f"Judge: `{base.get('judge_model', '?')}`")
    md.append("")

    md.append("## Per-source averages (max 50)")
    md.append("")
    md.append("| Source | n | Baseline avg | V2 avg | Δ |")
    md.append("|---|---|---|---|---|")
    for src in sources:
        b_per = base.get("summary", {}).get("per_source", {}).get(src, {})
        v_per = v2.get("summary", {}).get("per_source", {}).get(src, {})
        if not b_per or not v_per:
            continue
        b_avg = b_per.get("avg_total", 0)
        v_avg = v_per.get("avg_total", 0)
        delta = v_avg - b_avg
        sign = "+" if delta > 0 else ""
        md.append(f"| {src} | {b_per.get('n', '?')} → {v_per.get('n', '?')} | {b_avg} | {v_avg} | **{sign}{delta:.2f}** |")
    md.append("")

    # Per-dimension delta for intellcluster only — that's the source we changed
    md.append("## Per-dimension delta for IntellCluster orchestration")
    md.append("")
    md.append("| Dimension | Baseline | V2 | Δ |")
    md.append("|---|---|---|---|")
    b_dim = base.get("summary", {}).get("per_source", {}).get("intellcluster", {}).get("per_dim_avg", {})
    v_dim = v2.get("summary", {}).get("per_source", {}).get("intellcluster", {}).get("per_dim_avg", {})
    for dim in ["correctness", "completeness", "hallucination_freedom", "calibration", "specificity"]:
        b = b_dim.get(dim)
        v = v_dim.get(dim)
        if b is None or v is None:
            continue
        d = v - b
        sign = "+" if d > 0 else ""
        md.append(f"| {dim} | {b} | {v} | **{sign}{d:.2f}** |")
    md.append("")

    # Per-case paired comparison for intellcluster
    md.append("## IntellCluster — paired per-case results")
    md.append("")
    md.append("Each row = same case, same judging rubric.")
    md.append("")
    md.append("| Case | Baseline | V2 | Δ |")
    md.append("|---|---|---|---|")
    b_per = per_case_totals(base, "intellcluster")
    v_per = per_case_totals(v2, "intellcluster")
    common = sorted(set(b_per) & set(v_per))
    deltas = []
    for cid in common:
        b = b_per[cid]
        v = v_per[cid]
        d = v - b
        deltas.append(d)
        sign = "+" if d > 0 else ""
        md.append(f"| {cid} | {b} | {v} | {sign}{d} |")
    if deltas:
        md.append(f"| **Average** | **{mean([b_per[c] for c in common]):.2f}** | **{mean([v_per[c] for c in common]):.2f}** | **{mean(deltas):+.2f}** |")
        md.append("")
        md.append(f"**Win/loss summary:** {wilcoxon_summary(deltas)}")
        md.append("")
        if len(deltas) > 2:
            md.append(f"**Standard deviation of delta:** {stdev(deltas):.2f}")
            md.append("")

    # IntellCluster vs each baseline (the headline claim)
    md.append("## IntellCluster v2 vs each solo baseline")
    md.append("")
    md.append("Per-case: did v2 IntellCluster beat the solo model on the same case?")
    md.append("")
    md.append("| Solo model | Wins | Losses | Ties | IC v2 avg | Solo avg |")
    md.append("|---|---|---|---|---|---|")
    v2_ic = per_case_totals(v2, "intellcluster")
    for solo_src in ["gpt4o_solo", "sonnet_solo", "gemini_solo"]:
        v2_solo = per_case_totals(v2, solo_src)
        common = sorted(set(v2_ic) & set(v2_solo))
        wins = sum(1 for c in common if v2_ic[c] > v2_solo[c])
        losses = sum(1 for c in common if v2_ic[c] < v2_solo[c])
        ties = sum(1 for c in common if v2_ic[c] == v2_solo[c])
        ic_avg = mean([v2_ic[c] for c in common]) if common else 0
        solo_avg = mean([v2_solo[c] for c in common]) if common else 0
        md.append(f"| {solo_src} | {wins} | {losses} | {ties} | {ic_avg:.2f} | {solo_avg:.2f} |")
    md.append("")

    md.append("## Notes")
    md.append("")
    md.append("- Each total is out of 50 (5 dimensions × 10 each).")
    md.append("- Wilcoxon-style win/loss is a non-parametric sanity check; for small N it's a directional signal not a formal p-value.")
    md.append("- Cases where any source errored are excluded from comparisons.")
    md.append("")

    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {out_path}")
    print()
    # echo headlines
    for line in md:
        if line.startswith("|") and ("Δ" in line or "**" in line):
            print(line)


if __name__ == "__main__":
    main()
