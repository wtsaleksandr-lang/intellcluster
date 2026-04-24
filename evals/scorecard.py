"""
Scorecard aggregation + CI gate.

Given a list of per-prompt records — each containing a list of
JudgeResult — produce:

  1. Per-judge pass rate (across all prompts)
  2. Per-prompt summary (which judges passed/warned/failed)
  3. Overall health score
  4. A clear CI verdict (exit 0 vs exit 1)

CI gate is conservative by default:
  - any deterministic FAIL   -> exit 1
  - >1 prompt with >=1 FAIL  -> exit 1
  - overall pass rate < 0.85 -> exit 1

Threshold constants are tunable via ENV vars so CI can tighten/loosen
without a code change.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

from evals.judges.base import JudgeResult, JudgeVerdict


MIN_OVERALL_PASS_RATE = float(os.environ.get("EVALS_MIN_PASS_RATE", "0.85"))
MAX_PROMPTS_WITH_FAIL = int(os.environ.get("EVALS_MAX_PROMPTS_WITH_FAIL", "1"))


@dataclass
class Scorecard:
    per_prompt: list[dict[str, Any]]          # one entry per prompt with verdicts
    per_judge_pass_rate: dict[str, float]     # judge_name -> pass fraction
    overall_pass_rate: float
    ci_verdict: str                           # "pass" | "fail"
    ci_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "per_prompt": self.per_prompt,
            "per_judge_pass_rate": self.per_judge_pass_rate,
            "overall_pass_rate": self.overall_pass_rate,
            "ci_verdict": self.ci_verdict,
            "ci_reasons": self.ci_reasons,
        }


def _prompt_summary(prompt_id: str, judges: list[JudgeResult]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    per_judge = {}
    for jr in judges:
        counts[jr.verdict.value] += 1
        per_judge[jr.judge] = {
            "verdict": jr.verdict.value,
            "score": jr.score,
            "note": jr.note,
        }
    overall = "pass"
    if counts.get("fail", 0) > 0 or counts.get("error", 0) > 0:
        overall = "fail"
    elif counts.get("warn", 0) > 0:
        overall = "warn"
    return {
        "prompt_id": prompt_id,
        "judges": per_judge,
        "counts": dict(counts),
        "overall": overall,
    }


def build_scorecard(records: list[dict[str, Any]]) -> Scorecard:
    """records: [{"prompt_id": str, "judges": [JudgeResult, ...]}, ...]"""
    per_prompt = [_prompt_summary(r["prompt_id"], r["judges"]) for r in records]

    # Per-judge pass rate: fraction of prompts where that judge returned PASS.
    judge_counts: dict[str, Counter[str]] = {}
    for entry in per_prompt:
        for judge_name, jd in entry["judges"].items():
            judge_counts.setdefault(judge_name, Counter())[jd["verdict"]] += 1

    per_judge_pass_rate: dict[str, float] = {}
    for judge_name, counts in judge_counts.items():
        # Exclude SKIP from denominator — N/A shouldn't drag the score.
        denom = sum(v for k, v in counts.items() if k != "skip") or 1
        per_judge_pass_rate[judge_name] = round(counts.get("pass", 0) / denom, 3)

    # Overall pass rate: fraction of prompts whose overall == "pass".
    passed_prompts = sum(1 for entry in per_prompt if entry["overall"] == "pass")
    overall_pass_rate = round(passed_prompts / max(1, len(per_prompt)), 3)

    # CI gate.
    ci_reasons: list[str] = []
    prompts_with_fail = sum(1 for entry in per_prompt if entry["overall"] == "fail")
    if prompts_with_fail > MAX_PROMPTS_WITH_FAIL:
        ci_reasons.append(
            f"{prompts_with_fail} prompts failing (limit {MAX_PROMPTS_WITH_FAIL})"
        )
    if overall_pass_rate < MIN_OVERALL_PASS_RATE:
        ci_reasons.append(
            f"overall pass rate {overall_pass_rate} < {MIN_OVERALL_PASS_RATE}"
        )
    # Deterministic judges must individually stay above 0.9 pass rate.
    DETERMINISTIC_NAMES = {
        "citation_validity", "structural",
        "freshness_alignment", "confidence_consistency",
    }
    for judge_name, rate in per_judge_pass_rate.items():
        if judge_name in DETERMINISTIC_NAMES and rate < 0.9:
            ci_reasons.append(
                f"deterministic judge '{judge_name}' pass rate {rate} < 0.9"
            )

    ci_verdict = "fail" if ci_reasons else "pass"

    return Scorecard(
        per_prompt=per_prompt,
        per_judge_pass_rate=per_judge_pass_rate,
        overall_pass_rate=overall_pass_rate,
        ci_verdict=ci_verdict,
        ci_reasons=ci_reasons,
    )


# ───── Pretty-print ─────

def render(scorecard: Scorecard) -> str:
    lines = []
    lines.append("=" * 70)
    lines.append(f"Synthesis Golden-Set Scorecard")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Overall pass rate:  {scorecard.overall_pass_rate}")
    lines.append(f"CI verdict:         {scorecard.ci_verdict.upper()}")
    if scorecard.ci_reasons:
        for r in scorecard.ci_reasons:
            lines.append(f"  - {r}")
    lines.append("")
    lines.append("Per-judge pass rate:")
    for jn, rate in sorted(scorecard.per_judge_pass_rate.items()):
        bar = "█" * int(rate * 20)
        lines.append(f"  {jn:<28} {rate:.2f}  {bar}")
    lines.append("")
    lines.append("Per-prompt:")
    lines.append(f"  {'ID':<22} {'verdict':<8} {'judges':<50}")
    for entry in scorecard.per_prompt:
        summary = " ".join(
            f"{jn[:3]}={jd['verdict'][:4]}"
            for jn, jd in sorted(entry["judges"].items())
        )
        lines.append(f"  {entry['prompt_id']:<22} {entry['overall']:<8} {summary}")
    lines.append("=" * 70)
    return "\n".join(lines)
