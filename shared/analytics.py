"""
Lightweight server-side event logging.
Writes JSONL to history/analytics.jsonl for later inspection/dashboarding.

Optionally proxies pageview events via Plausible if PLAUSIBLE_DOMAIN is set.

Usage:
    from shared.analytics import log_event
    log_event("decision_completed", {"run_id": "...", "winner": "..."})
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ANALYTICS_DIR = Path("history")
ANALYTICS_FILE = "analytics.jsonl"


def log_event(event: str, props: dict[str, Any] | None = None) -> None:
    """Append a structured event to analytics.jsonl."""
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **(props or {}),
    }
    try:
        with open(ANALYTICS_DIR / ANALYTICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # Never crash the app because of analytics
        pass


def recent_events(limit: int = 200, event_filter: str | None = None) -> list[dict]:
    """Load recent events from the log."""
    path = ANALYTICS_DIR / ANALYTICS_FILE
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if event_filter and entry.get("event") != event_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries[-limit:][::-1]


def summary_last_24h() -> dict[str, int]:
    """Count events in last 24 hours by type."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    counts: dict[str, int] = {}
    for entry in recent_events(limit=10000):
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts < cutoff:
                continue
            evt = entry.get("event", "unknown")
            counts[evt] = counts.get(evt, 0) + 1
        except Exception:
            continue
    return counts


def get_plausible_domain() -> str | None:
    """Return Plausible domain if configured (None = not using Plausible)."""
    return os.environ.get("PLAUSIBLE_DOMAIN") or None
