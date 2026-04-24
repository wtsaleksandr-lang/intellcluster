"""
SQLite index over the append-only Synthesis runs JSONL.

Design
------
- JSONL is the source of truth. The DB is a derived index — losing it
  never loses data; we rebuild on the next call.
- The index stores (run_id, byte_offset, length) plus summary columns
  so listings can run without opening the JSONL file at all. Only the
  full-detail lookup path seeks into the JSONL.
- Writes are single-process, single-writer (uvicorn default = 1 worker).
  WAL mode is enabled so concurrent readers never block the writer if
  that assumption ever changes.
- Schema is tiny and additive: new columns can be added via ALTER TABLE
  with a migration block below.

Public API
----------
  ensure_index(jsonl_path)                         — idempotent, cheap
  index_append(jsonl_path, entry, line_bytes, off) — call after JSONL write
  lookup(jsonl_path, run_id) -> dict | None
  list_recent(jsonl_path, limit=20, user_email=None) -> list[dict]
  rebuild(jsonl_path)                              — full reindex, idempotent

Everything is keyed on the absolute JSONL path — so a test can point at
a temp directory without touching production history.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


# One lock per absolute JSONL path protects against concurrent rebuilds
# within a single process. sqlite3 itself serialises writes, but we want
# a coarser guard around the "check then rebuild" path.
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock_for(jsonl_path: Path) -> threading.Lock:
    key = str(jsonl_path.resolve())
    with _locks_lock:
        lk = _locks.get(key)
        if lk is None:
            lk = threading.Lock()
            _locks[key] = lk
        return lk


def _db_path_for(jsonl_path: Path) -> Path:
    """Place the SQLite file next to the JSONL, same basename, .db suffix."""
    return jsonl_path.with_suffix(".db")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS synthesis_run_index (
    run_id               TEXT PRIMARY KEY,
    timestamp            TEXT NOT NULL,
    user_email           TEXT,
    category             TEXT,
    mode                 TEXT,
    prompt_preview       TEXT,
    source_count         INTEGER NOT NULL DEFAULT 0,
    has_structured_report INTEGER NOT NULL DEFAULT 0,
    model_count          INTEGER NOT NULL DEFAULT 0,
    jsonl_offset         INTEGER NOT NULL,
    jsonl_length         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_timestamp   ON synthesis_run_index(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_user_email  ON synthesis_run_index(user_email);
CREATE INDEX IF NOT EXISTS idx_category    ON synthesis_run_index(category);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the index DB with pragmas tuned for a sidecar index."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA_SQL)
    return conn


def _row_from_entry(entry: dict, offset: int, length: int) -> tuple:
    """Extract the row the index stores for one JSONL entry."""
    prompt = entry.get("prompt") or entry.get("original_prompt") or ""
    return (
        entry.get("run_id"),
        entry.get("timestamp") or "",
        entry.get("user_email"),
        entry.get("category"),
        entry.get("mode"),
        prompt[:300],
        len(entry.get("sources") or []),
        1 if entry.get("structured_report") else 0,
        int(entry.get("model_count") or 0),
        int(offset),
        int(length),
    )


UPSERT_SQL = """
INSERT INTO synthesis_run_index (
    run_id, timestamp, user_email, category, mode, prompt_preview,
    source_count, has_structured_report, model_count,
    jsonl_offset, jsonl_length
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(run_id) DO UPDATE SET
    timestamp=excluded.timestamp,
    user_email=excluded.user_email,
    category=excluded.category,
    mode=excluded.mode,
    prompt_preview=excluded.prompt_preview,
    source_count=excluded.source_count,
    has_structured_report=excluded.has_structured_report,
    model_count=excluded.model_count,
    jsonl_offset=excluded.jsonl_offset,
    jsonl_length=excluded.jsonl_length;
"""


def rebuild(jsonl_path: Path) -> int:
    """Wipe and rebuild the index from the JSONL. Returns row count.

    Safe to call concurrently with readers (WAL). Not safe to call
    concurrently with writers — hold the per-path lock.
    """
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)

    with _lock_for(jsonl_path):
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM synthesis_run_index")
            count = 0
            if jsonl_path.exists():
                with open(jsonl_path, "rb") as f:
                    while True:
                        offset = f.tell()
                        line = f.readline()
                        if not line:
                            break
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line.decode("utf-8"))
                        except Exception:
                            continue
                        if not entry.get("run_id"):
                            continue
                        conn.execute(UPSERT_SQL, _row_from_entry(entry, offset, len(line)))
                        count += 1
            conn.execute("COMMIT")
            return count
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def ensure_index(jsonl_path: Path) -> None:
    """Make sure the index exists and is at least as long as the JSONL.

    Cheap: just compares DB row count vs a quick JSONL line count. Only
    rebuilds when they disagree. If the DB is missing, it's created
    empty and then rebuilt.
    """
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)

    # Fresh DB — rebuild if a JSONL exists.
    if not db_path.exists():
        if jsonl_path.exists():
            rebuild(jsonl_path)
        else:
            _connect(db_path).close()   # create empty schema
        return

    # DB exists. Cheap sanity check: count JSONL lines vs DB rows.
    try:
        jsonl_lines = 0
        if jsonl_path.exists():
            with open(jsonl_path, "rb") as f:
                for line in f:
                    if line.strip():
                        jsonl_lines += 1
        conn = _connect(db_path)
        try:
            db_rows = conn.execute(
                "SELECT COUNT(*) FROM synthesis_run_index"
            ).fetchone()[0]
        finally:
            conn.close()
        if db_rows != jsonl_lines:
            rebuild(jsonl_path)
    except Exception:
        # Corrupt DB or read error — rebuild defensively.
        rebuild(jsonl_path)


def index_append(
    jsonl_path: Path,
    entry: dict,
    line_length: int,
    byte_offset: int,
) -> None:
    """Record a newly-appended JSONL line in the index.

    The caller must have already written the line and captured the
    offset+length at write time (so this call is lossless even if two
    writers raced — only one offset wins; the JSONL remains canonical).
    """
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)

    with _lock_for(jsonl_path):
        conn = _connect(db_path)
        try:
            conn.execute(UPSERT_SQL, _row_from_entry(entry, byte_offset, line_length))
        finally:
            conn.close()


def lookup(jsonl_path: Path, run_id: str) -> dict | None:
    """Return the full JSON entry for a run_id, or None.

    Index lookup (O(log n)) → one seek-read on the JSONL.
    """
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)
    if not db_path.exists() and jsonl_path.exists():
        rebuild(jsonl_path)
    if not db_path.exists():
        return None

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT jsonl_offset, jsonl_length FROM synthesis_run_index WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not jsonl_path.exists():
        return None

    try:
        with open(jsonl_path, "rb") as f:
            f.seek(int(row["jsonl_offset"]))
            line_bytes = f.read(int(row["jsonl_length"]))
        return json.loads(line_bytes.decode("utf-8"))
    except Exception:
        # JSONL was truncated/rewritten — stale index. Rebuild and retry.
        rebuild(jsonl_path)
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT jsonl_offset, jsonl_length FROM synthesis_run_index WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            with open(jsonl_path, "rb") as f:
                f.seek(int(row["jsonl_offset"]))
                line_bytes = f.read(int(row["jsonl_length"]))
            return json.loads(line_bytes.decode("utf-8"))
        except Exception:
            return None


def list_recent(
    jsonl_path: Path,
    limit: int = 20,
    user_email: str | None = None,
) -> list[dict]:
    """Return the most recent runs, newest first.

    Uses the index only — no JSONL seek. Returns the summary columns
    plus the run_id (enough for list views). Callers that need full
    detail should call `lookup()` on each id.
    """
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)
    if not db_path.exists() and jsonl_path.exists():
        rebuild(jsonl_path)
    if not db_path.exists():
        return []

    # prompt_preview is aliased to `prompt` so existing Jinja templates
    # that access `r.prompt[:120]` keep working without touching them.
    select_cols = (
        "run_id, timestamp, user_email, category, mode, "
        "prompt_preview AS prompt, prompt_preview, "
        "source_count, has_structured_report, model_count"
    )
    conn = _connect(db_path)
    try:
        if user_email:
            rows = conn.execute(
                f"""SELECT {select_cols}
                    FROM synthesis_run_index
                    WHERE user_email = ?
                    ORDER BY timestamp DESC
                    LIMIT ?""",
                (user_email, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT {select_cols}
                    FROM synthesis_run_index
                    ORDER BY timestamp DESC
                    LIMIT ?""",
                (limit,),
            ).fetchall()
    finally:
        conn.close()

    return [dict(r) for r in rows]


def stats(jsonl_path: Path) -> dict[str, Any]:
    """Cheap introspection — size, oldest/newest timestamp."""
    jsonl_path = Path(jsonl_path)
    db_path = _db_path_for(jsonl_path)
    if not db_path.exists():
        return {"rows": 0, "oldest": None, "newest": None}
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS rows,
                      MIN(timestamp) AS oldest,
                      MAX(timestamp) AS newest
               FROM synthesis_run_index"""
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {"rows": 0, "oldest": None, "newest": None}
