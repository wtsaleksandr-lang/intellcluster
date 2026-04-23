"""
User ledger — history/users.jsonl, append-only with last-write-wins snapshot.

We keep it simple: one row per mutation, readers reconstruct the latest state
per email. Good for our scale (hundreds to thousands of users before we'd
need to care). At growth we'd swap to SQLite or Postgres behind the same
functions.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path("history/users.jsonl")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(_norm(email)[:200]))


def _read_rows() -> list[dict[str, Any]]:
    if not _FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _append(row: dict[str, Any]) -> None:
    _FILE.parent.mkdir(exist_ok=True)
    with open(_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snapshot() -> dict[str, dict[str, Any]]:
    """Reduce the JSONL log to a {email: latest-state} snapshot."""
    snap: dict[str, dict[str, Any]] = {}
    for row in _read_rows():
        email = _norm(row.get("email", ""))
        if not email:
            continue
        existing = snap.get(email, {})
        existing.update(row)
        snap[email] = existing
    return snap


def get_user(email: str) -> dict[str, Any] | None:
    email = _norm(email)
    if not email:
        return None
    snap = _snapshot()
    return snap.get(email)


def list_users(limit: int = 500) -> list[dict[str, Any]]:
    users = list(_snapshot().values())
    users.sort(key=lambda u: u.get("last_login") or u.get("created_at") or "", reverse=True)
    return users[:limit]


def upsert_user(email: str, **fields: Any) -> dict[str, Any]:
    """Create a user row or merge fields into an existing one.

    Sets `created_at` on first seen, always updates `last_login`, and is
    safe to call on every magic-link verify.
    """
    email = _norm(email)
    if not is_valid_email(email):
        raise ValueError("invalid email")

    now = datetime.now(timezone.utc).isoformat()
    existing = get_user(email)
    row: dict[str, Any] = {"email": email, "last_login": now}
    if not existing:
        row["created_at"] = now
        row["plan"] = fields.get("plan", "free")
    row.update({k: v for k, v in fields.items() if v is not None})
    _append(row)

    merged = dict(existing or {})
    merged.update(row)
    return merged


def update_user_plan(email: str, plan: str) -> dict[str, Any] | None:
    email = _norm(email)
    if not email:
        return None
    row = {
        "email": email,
        "plan": plan,
        "plan_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _append(row)
    return get_user(email)


def user_count() -> int:
    return len(_snapshot())
