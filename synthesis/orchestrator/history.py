"""
Lightweight run history — JSONL file storage.
Stores completed run summaries for review and reuse.
"""

import json
import os
from datetime import datetime, timezone

HISTORY_DIR = "history"
HISTORY_FILE = os.path.join(HISTORY_DIR, "runs.jsonl")


def _ensure_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def save_run(
    run_id: str,
    category: str,
    original_prompt: str,
    refined_prompt: str,
    models: list[str],
    strategist_output: str,
    decision_output: str,
    status: str = "completed",
    mode: str = "standard",
    quick_mode: bool = False,
    attachments: list[dict] | None = None,
    model_outputs: list[dict] | None = None,
):
    """Save a completed run to history.

    model_outputs: [{model_name, status, response_content, latency_ms}]
    """
    _ensure_dir()
    entry = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "original_prompt": original_prompt,
        "refined_prompt": refined_prompt,
        "models": models,
        "strategist_output": strategist_output,
        "decision_output": decision_output,
        "status": status,
        "mode": mode,
        "quick_mode": quick_mode,
        "attachments": [a.get("name", "") for a in (attachments or [])],
        "model_outputs": model_outputs or [],
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_recent_runs(limit: int = 20) -> list[dict]:
    """Get the most recent runs (newest first)."""
    if not os.path.exists(HISTORY_FILE):
        return []

    runs = []
    skipped = 0
    with open(HISTORY_FILE, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
    if skipped:
        import sys
        print(f"[history] WARNING: skipped {skipped} corrupted lines in {HISTORY_FILE}", file=sys.stderr)

    # Return newest first, limited
    runs.reverse()
    return runs[:limit]


def get_run(run_id: str) -> dict | None:
    """Get a specific run by ID."""
    if not os.path.exists(HISTORY_FILE):
        return None

    with open(HISTORY_FILE, "r") as f:
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
