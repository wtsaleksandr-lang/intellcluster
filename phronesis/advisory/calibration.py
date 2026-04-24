"""
Calibration feedback loop.

When a user (or later, a follow-up prompt we send them) rates how their
advisory decision actually turned out, we store the outcome in a ledger.

Each rating is:
  * run_id                 — links back to the AdvisorySession
  * user_email             — so we can personalise the adjustment
  * rating                 — 1-5 (1=much worse than expected, 5=much better)
  * outcome_note           — optional free-text
  * stated_confidence      — the system's confidence_level at the time
                             (low / moderate / moderate-high / high)
  * stated_confidence_pct  — best-effort numeric from confidence_range

CALIBRATION PROCESS:

  For each user's run history, we bucket stated confidences and compute
  the "actual good outcome" rate (rating >= 4 means the recommendation
  held up). A well-calibrated system has:
      actual_rate(high)          ≈ 0.85
      actual_rate(moderate-high) ≈ 0.72
      actual_rate(moderate)      ≈ 0.55
      actual_rate(low)           ≈ 0.40

  For each bucket we compute an adjustment = actual_rate - expected_rate.
  Positive adjustment means the system is UNDERCONFIDENT for this user —
  push confidence up. Negative means OVERCONFIDENT — push confidence down.

  Adjustments are in the range [-0.15, +0.15] and applied to the
  Synthesizer's prompt as a hint. We DO NOT silently mutate the
  confidence — we tell the model "this user's historical calibration
  data suggests adjusting stated confidence by X"; the model decides.

  A minimum of 5 rated runs per user is required before any adjustment
  becomes non-zero. Below that, we use global calibration (aggregated
  across all users) if we have ≥ 20 global ratings, else zero.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path("history/advisory_calibrations.jsonl")

# Expected hit-rate per confidence bucket — what a well-calibrated system
# SHOULD show. Deviation from these is the calibration error.
EXPECTED_HIT_RATE = {
    "low": 0.40,
    "moderate": 0.55,
    "moderate-high": 0.72,
    "high": 0.85,
}

# Minimum rated runs before per-user calibration kicks in.
MIN_PER_USER = 5
# Minimum total rated runs before global calibration kicks in.
MIN_GLOBAL = 20
# Clamp on the suggested adjustment.
MAX_ADJUSTMENT = 0.15


def record_rating(
    run_id: str,
    user_email: str | None,
    rating: int,
    outcome_note: str,
    stated_confidence: str,
    stated_confidence_pct: float | None = None,
) -> dict[str, Any]:
    """Append one rating row. Safe to call multiple times (idempotent by
    latest-wins on run_id — we just add a new row, read-time uses the latest)."""
    _FILE.parent.mkdir(exist_ok=True)
    rating = max(1, min(5, int(rating)))
    row = {
        "run_id": run_id,
        "user_email": (user_email or "").strip().lower() or None,
        "rating": rating,
        "outcome_note": (outcome_note or "")[:1000],
        "stated_confidence": (stated_confidence or "moderate").lower(),
        "stated_confidence_pct": stated_confidence_pct,
        "rated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _load_ratings(user_email: str | None = None) -> list[dict[str, Any]]:
    if not _FILE.exists():
        return []
    out: list[dict[str, Any]] = []
    email = (user_email or "").strip().lower() or None
    # Latest per run_id wins
    latest: dict[str, dict[str, Any]] = {}
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if email and (row.get("user_email") or "") != email:
                continue
            rid = row.get("run_id")
            if rid:
                latest[rid] = row
    return list(latest.values())


def get_latest_rating(run_id: str) -> dict[str, Any] | None:
    if not _FILE.exists():
        return None
    latest = None
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("run_id") == run_id:
                latest = row
    return latest


def compute_user_calibration(user_email: str | None) -> dict[str, float]:
    """
    Return per-confidence-bucket adjustment suggestions for a user.

    Returns dict like {"high": +0.05, "moderate": -0.08} — meaning
    the user's high-confidence calls did better than expected, but
    moderate-confidence calls did WORSE than expected, so future
    moderate calls should be stated with lower confidence.

    Falls back to global calibration when per-user data is thin, then
    returns zeros when no data exists.
    """
    ratings = _load_ratings(user_email)
    if len(ratings) < MIN_PER_USER:
        # Fall back to global
        all_ratings = _load_ratings(None)
        if len(all_ratings) < MIN_GLOBAL:
            return {}
        ratings = all_ratings

    # Bucket ratings by stated_confidence, compute hit rate per bucket.
    buckets: dict[str, list[int]] = {}
    for r in ratings:
        conf = (r.get("stated_confidence") or "moderate").lower()
        if conf not in EXPECTED_HIT_RATE:
            continue
        buckets.setdefault(conf, []).append(int(r.get("rating", 0) or 0))

    adjustments: dict[str, float] = {}
    for conf, rs in buckets.items():
        if len(rs) < 3:   # need ≥3 samples in a bucket
            continue
        hit_rate = sum(1 for r in rs if r >= 4) / len(rs)
        expected = EXPECTED_HIT_RATE[conf]
        delta = hit_rate - expected    # positive = under-confident
        # Clamp and apply light dampening (don't over-correct on small n)
        dampen = min(1.0, len(rs) / 10.0)  # full weight at n≥10
        adj = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, delta * dampen))
        adjustments[conf] = round(adj, 3)
    return adjustments


def calibration_hint(user_email: str | None) -> str:
    """
    Human-readable prompt fragment the Synthesizer Agent receives so it
    can take historical calibration into account when stating confidence.

    Empty string when we have no data — the Synthesizer behaves normally.
    """
    adj = compute_user_calibration(user_email)
    if not adj:
        return ""

    lines = [
        "HISTORICAL CALIBRATION HINT:",
        "This user's past rated outcomes show the following systematic bias",
        "in stated confidence. Use this as a gentle nudge when deciding the",
        "final confidence_level — you can still deviate if the evidence warrants:",
    ]
    for conf, delta in sorted(adj.items(), key=lambda kv: kv[0]):
        if delta > 0.03:
            direction = f"under-stated by ~{int(delta*100)}pp — recommend nudging UP one level when leaning toward '{conf}'"
        elif delta < -0.03:
            direction = f"over-stated by ~{int(-delta*100)}pp — recommend nudging DOWN one level when leaning toward '{conf}'"
        else:
            direction = "well-calibrated — state as-is"
        lines.append(f"  - {conf}: {direction}")
    return "\n".join(lines)


def aggregate_stats() -> dict[str, Any]:
    """For /admin/advisory — overall calibration quality across the user base."""
    ratings = _load_ratings(None)
    if not ratings:
        return {"total": 0, "per_bucket": {}, "avg_rating": 0.0}
    per_bucket: dict[str, dict[str, float]] = {}
    for conf in EXPECTED_HIT_RATE:
        bucket = [r for r in ratings if (r.get("stated_confidence") or "").lower() == conf]
        if not bucket:
            continue
        hit_rate = sum(1 for r in bucket if int(r.get("rating", 0) or 0) >= 4) / len(bucket)
        per_bucket[conf] = {
            "n": len(bucket),
            "actual_hit_rate": round(hit_rate, 3),
            "expected": EXPECTED_HIT_RATE[conf],
            "delta": round(hit_rate - EXPECTED_HIT_RATE[conf], 3),
        }
    avg = sum(int(r.get("rating", 0) or 0) for r in ratings) / len(ratings)
    return {
        "total": len(ratings),
        "per_bucket": per_bucket,
        "avg_rating": round(avg, 2),
    }
