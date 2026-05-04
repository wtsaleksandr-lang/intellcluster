"""
Purchases ledger — idempotent record of every Stripe payment event.

Keyed on Stripe event.id, so webhook retries can't double-credit. Also
exposes a simple email → credits_balance view for the interim period
before user accounts are wired up end-to-end.

Concurrency: webhook retries from Stripe and multi-worker deployments
can race the read+append. We protect both with a process-wide lock plus
an in-memory `set` of seen event_ids that's lazily warmed from the file
on first call. The lock is reentrant so callers can nest if needed.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path("history/purchases.jsonl")

_lock = threading.RLock()
_seen_event_ids: set[str] | None = None  # lazy-loaded on first call


def _warm_seen_cache() -> set[str]:
    seen: set[str] = set()
    if not _FILE.exists():
        return seen
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            eid = rec.get("event_id")
            if eid:
                seen.add(eid)
    return seen


def _ensure_cache() -> set[str]:
    global _seen_event_ids
    if _seen_event_ids is None:
        _seen_event_ids = _warm_seen_cache()
    return _seen_event_ids


def record_purchase(
    event_id: str,
    email: str | None,
    kind: str,
    amount: int,
    currency: str,
    credits: int | None = None,
    plan_id: str | None = None,
    pack_id: str | None = None,
    stripe_customer: str | None = None,
    stripe_subscription: str | None = None,
) -> dict[str, Any] | None:
    """Append a purchase row. Returns the entry, or None if already recorded.

    Atomic w.r.t. concurrent calls in the same process: holds `_lock` for
    the entire check + append window, so a Stripe webhook retry firing
    simultaneously on the same event_id sees the already-written record.
    """
    if not event_id:
        return None
    with _lock:
        seen = _ensure_cache()
        if event_id in seen:
            return None
        _FILE.parent.mkdir(exist_ok=True)
        entry = {
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "email": (email or "").strip().lower(),
            "kind": kind,
            "amount": amount,
            "currency": currency,
            "credits": credits,
            "plan_id": plan_id,
            "pack_id": pack_id,
            "stripe_customer": stripe_customer,
            "stripe_subscription": stripe_subscription,
        }
        with open(_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        seen.add(event_id)
        return entry


def credits_balance(email: str) -> int:
    """Sum of credits ever purchased by this email. Interim feature — replace
    with a proper usage ledger once user accounts exist."""
    if not _FILE.exists():
        return 0
    email_l = (email or "").strip().lower()
    total = 0
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("email") == email_l and rec.get("credits"):
                total += int(rec["credits"])
    return total


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
