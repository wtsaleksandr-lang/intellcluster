"""
Synthesis history — persists completed research runs for shareable URLs.

JSONL remains the source of truth (append-only, easy to inspect/backup).
A SQLite sidecar index provides O(log n) lookup and O(1) listing; if it
is ever missing or drifts from the JSONL, it rebuilds itself.

Public API is unchanged — callers do not need to know the index exists.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.tracking import synthesis_index


HISTORY_DIR = Path("history")
HISTORY_FILE = HISTORY_DIR / "synthesis_runs.jsonl"


def _path() -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_FILE


def save_synthesis_run(data: dict) -> str:
    """Append a completed Synthesis run to the JSONL and update the index.

    The JSONL append happens in binary mode so the byte offset we capture
    is exact — the index stores `(offset, length)` and seeks directly
    into the file on lookup.
    """
    path = _path()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    line_bytes = line.encode("utf-8")

    with open(path, "ab") as f:
        offset = f.tell()
        f.write(line_bytes)

    try:
        synthesis_index.index_append(
            jsonl_path=path,
            entry=entry,
            line_length=len(line_bytes),
            byte_offset=offset,
        )
    except Exception as e:
        # Index is derived — a failure here must not break the save.
        # Next ensure_index() call rebuilds from JSONL.
        print(f"[synthesis_history] index_append failed: {e}")

    return str(path)


def get_synthesis_run(run_id: str) -> dict | None:
    """Look up a Synthesis run by run_id via the index (seek-read)."""
    path = HISTORY_FILE
    if not path.exists():
        return None
    # Self-heals if index is missing or drifted.
    synthesis_index.ensure_index(path)
    return synthesis_index.lookup(path, run_id)


def get_recent_synthesis_runs(limit: int = 20) -> list[dict]:
    """Return recent runs, newest first.

    Uses the index only — returns the summary fields needed for list
    views. Call `get_synthesis_run(run_id)` for full detail on a
    specific row.
    """
    path = HISTORY_FILE
    if not path.exists():
        return []
    synthesis_index.ensure_index(path)
    return synthesis_index.list_recent(path, limit=limit)
