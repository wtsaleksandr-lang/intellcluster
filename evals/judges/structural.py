"""
Structural completeness judge (deterministic).

Checks the StructuredReport has the minimum shape we expect from a
healthy Synthesis run:

  - executive_summary: non-empty, >=2 sentences
  - key_findings:      >=1 non-empty
  - recommendation:    non-empty
  - confidence:        has a band + 6 component keys

Everything else is optional-but-surfaced (risks, next_actions, evidence
table, contradictions). We don't penalise a report that lacks them when
the source material didn't warrant them — a comparison without real
contradictions shouldn't be forced to invent one.

FAIL if any REQUIRED section is missing. WARN if weak (e.g. single-line
executive summary). PASS otherwise.
"""

from __future__ import annotations

from evals.judges.base import JudgeResult, JudgeVerdict


name = "structural"


REQUIRED_CONFIDENCE_COMPONENTS = {
    "source_quality", "evidence_quantity", "source_agreement",
    "freshness", "contradiction_penalty", "model_consensus",
}


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    # Very rough — counts . ! ? followed by space or end.
    return sum(1 for ch in text if ch in ".!?") or 1


async def judge(record: dict) -> JudgeResult:
    report = record.get("report") or {}
    if not report:
        return JudgeResult(
            judge=name, verdict=JudgeVerdict.FAIL, score=0.0,
            note="no structured report produced",
        )

    missing: list[str] = []
    weak: list[str] = []

    exec_summary = (report.get("executive_summary") or "").strip()
    if not exec_summary:
        missing.append("executive_summary")
    elif _sentence_count(exec_summary) < 2:
        weak.append("executive_summary<2 sentences")

    key_findings = [
        f for f in (report.get("key_findings") or [])
        if isinstance(f, dict) and (f.get("finding") or "").strip()
    ]
    if not key_findings:
        missing.append("key_findings")

    recommendation = (report.get("recommendation") or "").strip()
    if not recommendation:
        missing.append("recommendation")

    confidence = report.get("confidence") or {}
    if not confidence.get("band"):
        missing.append("confidence.band")
    components = confidence.get("components") or {}
    missing_components = REQUIRED_CONFIDENCE_COMPONENTS - set(components.keys())
    if missing_components:
        missing.append(f"confidence.components({sorted(missing_components)})")

    if missing:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.FAIL,
            score=0.0,
            note=f"missing required sections: {missing}",
            details={"missing": missing, "weak": weak},
        )

    if weak:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.WARN,
            score=0.8,
            note=f"weak sections: {weak}",
            details={"weak": weak, "key_finding_count": len(key_findings)},
        )

    return JudgeResult(
        judge=name,
        verdict=JudgeVerdict.PASS,
        score=1.0,
        note=f"{len(key_findings)} key findings, all required sections present",
        details={"key_finding_count": len(key_findings)},
    )
