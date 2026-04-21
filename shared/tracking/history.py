"""
Decision history — stores completed evaluations as JSONL.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR = Path("history")


def save_decision(decision_data: dict) -> str:
    """Append a completed decision to the history log."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / "decisions.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **decision_data,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return str(path)


def get_recent_decisions(limit: int = 20) -> list[dict]:
    """Load recent decisions from history."""
    path = HISTORY_DIR / "decisions.jsonl"
    if not path.exists():
        return []

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return entries[-limit:][::-1]  # newest first


def get_decision_by_run_id(run_id: str) -> dict | None:
    """Look up a single decision by run_id."""
    path = HISTORY_DIR / "decisions.jsonl"
    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("run_id") == run_id:
                    return entry
            except json.JSONDecodeError:
                continue

    return None
