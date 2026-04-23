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


def delete_user(email: str) -> dict[str, Any]:
    """
    GDPR art. 17 — delete the user's row and all their runs / contact rows.

    Purchase records are retained (financial-recordkeeping obligation,
    7 years, called out in /privacy) but their `email` field is wiped
    to 'deleted@redacted.local' so they can't be used to re-identify.

    Returns counts of what was removed, so we can surface it on /account.
    """
    import json as _json
    from pathlib import Path as _Path

    email = _norm(email)
    if not email:
        return {"removed": 0}

    counts = {
        "users": 0,
        "decisions": 0,
        "synthesis_runs": 0,
        "contact_submissions": 0,
        "purchase_records_redacted": 0,
        "outcome_reminders_cleared": 0,
    }

    def _filter_jsonl(path: _Path, match_key: str) -> int:
        if not path.exists():
            return 0
        kept, removed = [], 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    kept.append(line)
                    continue
                if (rec.get(match_key) or "").strip().lower() == email:
                    removed += 1
                else:
                    kept.append(_json.dumps(rec, ensure_ascii=False))
        if removed:
            path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        return removed

    def _redact_purchases(path: _Path) -> int:
        if not path.exists():
            return 0
        rewritten, redacted = [], 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    rewritten.append(line)
                    continue
                if (rec.get("email") or "").strip().lower() == email:
                    rec["email"] = "deleted@redacted.local"
                    redacted += 1
                rewritten.append(_json.dumps(rec, ensure_ascii=False))
        if redacted:
            path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        return redacted

    counts["users"] = _filter_jsonl(_FILE, "email")
    counts["decisions"] = _filter_jsonl(_Path("history/decisions.jsonl"), "user_email")
    counts["synthesis_runs"] = _filter_jsonl(_Path("history/synthesis_runs.jsonl"), "user_email")
    counts["contact_submissions"] = _filter_jsonl(_Path("history/contact.jsonl"), "email")
    counts["outcome_reminders_cleared"] = _filter_jsonl(_Path("history/outcome_reminders_sent.jsonl"), "email")
    counts["purchase_records_redacted"] = _redact_purchases(_Path("history/purchases.jsonl"))

    return counts


def export_user(email: str) -> dict[str, Any]:
    """GDPR art. 20 — return everything we have on this email as a dict."""
    import json as _json
    from pathlib import Path as _Path

    email = _norm(email)
    out: dict[str, Any] = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "email": email,
        "account": get_user(email),
        "phronesis_runs": [],
        "synthesis_runs": [],
        "contact_submissions": [],
        "purchases": [],
    }

    def _read_matching(path: _Path, match_key: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _json.loads(line)
                except Exception:
                    continue
                if (rec.get(match_key) or "").strip().lower() == email:
                    rows.append(rec)
        return rows

    out["phronesis_runs"] = _read_matching(_Path("history/decisions.jsonl"), "user_email")
    out["synthesis_runs"] = _read_matching(_Path("history/synthesis_runs.jsonl"), "user_email")
    out["contact_submissions"] = _read_matching(_Path("history/contact.jsonl"), "email")
    out["purchases"] = _read_matching(_Path("history/purchases.jsonl"), "email")

    return out
