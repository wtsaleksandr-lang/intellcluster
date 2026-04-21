"""
Outcome tracking — users report how a decision actually worked out.
Builds a long-term dataset: did the tool's recommendation match reality?

Storage: history/outcomes.jsonl keyed by run_id.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR = Path("history")
OUTCOMES_FILE = "outcomes.jsonl"


def record_outcome(run_id: str, rating: int, note: str = "", chosen_option: str | None = None) -> dict:
    """Record a user-reported outcome.
    rating: 1-5 (1 = it was wrong, 5 = great recommendation)
    note: optional free text
    chosen_option: which option they actually chose (may differ from the winner)
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / OUTCOMES_FILE

    rating = max(1, min(5, int(rating)))
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "rating": rating,
        "note": note[:1000],
        "chosen_option": (chosen_option or "")[:200],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def outcomes_for_run(run_id: str) -> list[dict]:
    """Return all outcome reports for a given run_id."""
    path = HISTORY_DIR / OUTCOMES_FILE
    if not path.exists():
        return []
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("run_id") == run_id:
                    results.append(entry)
            except json.JSONDecodeError:
                continue
    return results


def aggregate_outcomes() -> dict:
    """Aggregate stats across all outcomes (for admin dashboard)."""
    path = HISTORY_DIR / OUTCOMES_FILE
    if not path.exists():
        return {"count": 0, "avg_rating": 0.0, "match_rate": 0.0}

    total = 0
    rating_sum = 0
    matches = 0  # when user chose the same option the tool recommended

    # Build lookup of run_id -> winner (from phronesis history)
    from shared.tracking.history import get_decision_by_run_id

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total += 1
                rating_sum += int(entry.get("rating", 0))
                chosen = entry.get("chosen_option", "").strip().lower()
                if chosen:
                    decision = get_decision_by_run_id(entry.get("run_id", ""))
                    if decision and decision.get("winner", "").strip().lower() == chosen:
                        matches += 1
            except Exception:
                continue

    return {
        "count": total,
        "avg_rating": round(rating_sum / total, 2) if total else 0.0,
        "match_rate": round(matches / total, 2) if total else 0.0,
    }
