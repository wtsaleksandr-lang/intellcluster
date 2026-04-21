"""
Synthesis history — persists completed research runs for shareable URLs.
JSONL format, same pattern as Phronesis decision history.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR = Path("history")


def save_synthesis_run(data: dict) -> str:
    """Append a completed Synthesis run to the history log."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / "synthesis_runs.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return str(path)


def get_synthesis_run(run_id: str) -> dict | None:
    """Look up a Synthesis run by run_id."""
    path = HISTORY_DIR / "synthesis_runs.jsonl"
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


def get_recent_synthesis_runs(limit: int = 20) -> list[dict]:
    """Load recent Synthesis runs."""
    path = HISTORY_DIR / "synthesis_runs.jsonl"
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

    return entries[-limit:][::-1]
