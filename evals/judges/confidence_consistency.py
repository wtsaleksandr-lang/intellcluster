"""
Confidence consistency judge (deterministic).

Recomputes what the confidence band SHOULD be given the components that
the pipeline reported, and flags mismatches. This catches cases where:

  - the DM overrode confidence in its JSON (forbidden by design)
  - the post-DM recompute in the pipeline drifted from the component
    weights
  - component values got corrupted in serialisation

Also enforces the safety ceiling from `expectations.max_band_without_sources`:
when retrieval returned zero sources, the band must not exceed the ceiling.
"""

from __future__ import annotations

from evals.judges.base import JudgeResult, JudgeVerdict


name = "confidence_consistency"


BAND_ORDER = ["low", "moderate", "moderate-high", "high"]


# Mirror confidence.py's WEIGHTS so the judge stays synchronised.
WEIGHTS = {
    "source_quality":     0.22,
    "evidence_quantity":  0.14,
    "source_agreement":   0.14,
    "freshness":          0.12,
    "contradiction_penalty": 0.10,   # SUBTRACTED
    "model_consensus":    0.28,
}


def _expected_band(components: dict, has_sources: bool) -> str:
    active = dict(WEIGHTS)
    if not has_sources:
        for k in ("source_quality", "evidence_quantity", "source_agreement", "freshness"):
            active[k] = 0.0
        total = sum(v for k, v in active.items() if k != "contradiction_penalty")
        if total > 0:
            factor = (1.0 - active["contradiction_penalty"]) / total
            for k in active:
                if k != "contradiction_penalty":
                    active[k] *= factor

    positive = sum(active[k] * float(components.get(k, 0.0))
                   for k in components if k != "contradiction_penalty")
    penalty = active["contradiction_penalty"] * float(components.get("contradiction_penalty", 0.0))
    positive_weight_sum = sum(v for k, v in active.items() if k != "contradiction_penalty") or 1.0
    score = max(0.0, min(1.0, (positive / positive_weight_sum) - penalty))

    if score >= 0.75: return "high"
    if score >= 0.60: return "moderate-high"
    if score >= 0.40: return "moderate"
    return "low"


def _band_order(band: str) -> int:
    try:
        return BAND_ORDER.index(band)
    except ValueError:
        return -1


async def judge(record: dict) -> JudgeResult:
    report = record.get("report") or {}
    confidence = report.get("confidence") or {}
    components = confidence.get("components") or {}
    actual_band = confidence.get("band")
    sources = record.get("sources") or []
    expectations = record.get("expectations") or {}

    if not actual_band or not components:
        return JudgeResult(
            judge=name, verdict=JudgeVerdict.SKIP, score=0.0,
            note="missing confidence data on report",
        )

    has_sources = len(sources) > 0
    expected = _expected_band(components, has_sources)

    # Strict check: actual must match computed. Allow one-step-neighbour
    # drift (component rounding vs band boundary), hard fail further.
    drift = abs(_band_order(actual_band) - _band_order(expected))

    if drift == 0:
        # Further safety ceiling: empty sources must not exceed expected cap.
        ceiling = expectations.get("max_band_without_sources")
        if (not has_sources) and ceiling:
            if _band_order(actual_band) > _band_order(ceiling):
                return JudgeResult(
                    judge=name,
                    verdict=JudgeVerdict.FAIL,
                    score=0.0,
                    note=f"band '{actual_band}' exceeds safety ceiling '{ceiling}' with no sources",
                    details={"expected_band": expected, "actual_band": actual_band, "ceiling": ceiling},
                )
        return JudgeResult(
            judge=name, verdict=JudgeVerdict.PASS, score=1.0,
            note=f"band '{actual_band}' matches recomputed components",
        )

    if drift == 1:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.WARN,
            score=0.7,
            note=f"band '{actual_band}' one step from recomputed '{expected}'",
            details={"expected_band": expected, "actual_band": actual_band, "components": components},
        )

    return JudgeResult(
        judge=name,
        verdict=JudgeVerdict.FAIL,
        score=0.0,
        note=f"band '{actual_band}' disagrees with recomputed '{expected}' by {drift} steps",
        details={"expected_band": expected, "actual_band": actual_band, "components": components},
    )
