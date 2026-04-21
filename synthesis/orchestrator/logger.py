"""
Configurable JSONL logger.
Supports minimal (default) and verbose modes.
"""

import json
import os
from datetime import datetime, timezone

from synthesis.config import settings


def _log_entry(
    run_id: str,
    step: str,
    phase: int | None = None,
    model: str | None = None,
    status: str | None = None,
    latency_ms: int | None = None,
    prompt: str | None = None,
    response: str | None = None,
    error: str | None = None,
) -> dict:
    """Build a log entry dict based on log_mode."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "step": step,
    }

    if phase is not None:
        entry["phase"] = phase
    if model:
        entry["model"] = model
    if status:
        entry["status"] = status
    if latency_ms is not None:
        entry["latency_ms"] = latency_ms
    if error:
        entry["error"] = error[:500]

    if settings.log_mode == "verbose":
        # Full prompt and response
        if prompt:
            entry["prompt"] = prompt
        if response:
            entry["response"] = response
    else:
        # Minimal: preview only
        if response:
            entry["preview"] = response[:200]

    return entry


def log_event(
    run_id: str,
    step: str,
    phase: int | None = None,
    model: str | None = None,
    status: str | None = None,
    latency_ms: int | None = None,
    prompt: str | None = None,
    response: str | None = None,
    error: str | None = None,
):
    """Write a log entry to logs/{run_id}.jsonl."""
    os.makedirs("logs", exist_ok=True)
    entry = _log_entry(
        run_id=run_id,
        step=step,
        phase=phase,
        model=model,
        status=status,
        latency_ms=latency_ms,
        prompt=prompt,
        response=response,
        error=error,
    )
    filepath = os.path.join("logs", f"{run_id}.jsonl")
    with open(filepath, "a") as f:
        f.write(json.dumps(entry) + "\n")
