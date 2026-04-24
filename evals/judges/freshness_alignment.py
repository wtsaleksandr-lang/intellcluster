"""
Freshness alignment judge (deterministic).

Two properties:

  1. The freshness detector's decision matches the prompt's expectation.
     If the prompt is marked `needs_freshness=True` and the detector
     returned "not_needed", that's a regression in freshness.py.

  2. When freshness was required AND sources were retrieved, at least
     half of them should be younger than 18 months. Stale sources on a
     freshness-required prompt is a wiring bug.

SKIP when retrieval wasn't configured (no Tavily/Brave key in the run).
"""

from __future__ import annotations

from datetime import datetime, timezone

from evals.judges.base import JudgeResult, JudgeVerdict


name = "freshness_alignment"


STALE_DAYS_THRESHOLD = 18 * 30   # ~18 months
MIN_FRESH_FRACTION = 0.5


def _days_since(published_iso: str | None) -> int | None:
    if not published_iso:
        return None
    try:
        s = published_iso.replace("Z", "+00:00")
        if len(s) == 10:
            dt = datetime.fromisoformat(s + "T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return max(0, (datetime.now(timezone.utc) - dt).days)


async def judge(record: dict) -> JudgeResult:
    expectations = record.get("expectations") or {}
    detected = record.get("freshness_level")   # "required" | "helpful" | "not_needed" | None
    sources = record.get("sources") or []
    retrieval_configured = record.get("retrieval_configured", False)

    needs_freshness = bool(expectations.get("needs_freshness"))

    # Property 1: detector alignment.
    detector_ok = True
    if needs_freshness and detected == "not_needed":
        detector_ok = False
    elif (not needs_freshness) and detected == "required":
        # Soft mismatch — detector was more aggressive than expected. WARN, not FAIL.
        pass

    # Property 2: source freshness (only evaluable with retrieval).
    if not retrieval_configured:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.SKIP,
            score=0.0,
            note="retrieval not configured — cannot evaluate source freshness",
            details={"detector_ok": detector_ok, "detected": detected},
        )

    if not sources:
        if needs_freshness:
            return JudgeResult(
                judge=name,
                verdict=JudgeVerdict.WARN,
                score=0.5,
                note="freshness-required prompt returned zero sources",
                details={"detector_ok": detector_ok, "detected": detected},
            )
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.PASS,
            score=1.0,
            note="no sources retrieved but freshness wasn't needed",
            details={"detector_ok": detector_ok, "detected": detected},
        )

    ages = [_days_since(s.get("published")) for s in sources]
    dated = [a for a in ages if a is not None]
    fresh = [a for a in dated if a <= STALE_DAYS_THRESHOLD]

    # Only the freshness-required branch cares about the <18mo check.
    if needs_freshness:
        if not dated:
            # Sources retrieved but none ship a publish date. Not a hard
            # regression (Tavily/Brave don't always surface dates) — WARN.
            return JudgeResult(
                judge=name,
                verdict=JudgeVerdict.WARN,
                score=0.6,
                note=f"freshness-required but none of {len(sources)} sources carried a date",
                details={"detector_ok": detector_ok},
            )
        fresh_fraction = len(fresh) / len(dated)
        if not detector_ok:
            return JudgeResult(
                judge=name,
                verdict=JudgeVerdict.FAIL,
                score=0.0,
                note=f"freshness detector said '{detected}' for a freshness-required prompt",
                details={
                    "fresh_fraction": round(fresh_fraction, 3),
                    "detected": detected,
                },
            )
        if fresh_fraction < MIN_FRESH_FRACTION:
            return JudgeResult(
                judge=name,
                verdict=JudgeVerdict.WARN,
                score=round(fresh_fraction, 3),
                note=f"only {int(fresh_fraction * 100)}% of dated sources are <18mo",
                details={
                    "fresh_fraction": round(fresh_fraction, 3),
                    "dated_count": len(dated),
                    "total_sources": len(sources),
                },
            )
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.PASS,
            score=round(fresh_fraction, 3),
            note=f"{int(fresh_fraction * 100)}% of dated sources are <18mo",
            details={
                "fresh_fraction": round(fresh_fraction, 3),
                "dated_count": len(dated),
                "total_sources": len(sources),
            },
        )

    # Prompt didn't need freshness — no stale-penalty applies.
    return JudgeResult(
        judge=name,
        verdict=JudgeVerdict.PASS,
        score=1.0,
        note="freshness not required for this prompt",
        details={"detector_ok": detector_ok, "detected": detected},
    )
