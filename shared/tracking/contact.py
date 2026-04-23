"""
Contact-form submissions — append-only JSONL.

Anonymous-friendly: we don't require an account to submit a contact form.
The admin dashboard reads this file to surface incoming messages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path("history/contact.jsonl")


def record_contact(
    name: str,
    email: str,
    reason: str,
    message: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a contact submission. Returns the saved entry."""
    _FILE.parent.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "name": name.strip()[:120],
        "email": email.strip().lower()[:200],
        "reason": reason.strip()[:40],
        "message": message.strip()[:4000],
        "meta": meta or {},
    }
    with open(_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_recent(limit: int = 100) -> list[dict[str, Any]]:
    if not _FILE.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    out.reverse()
    return out[:limit]
