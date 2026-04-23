"""
Outcome-reminder worker.

Once per cycle (default: every 6 hours), scan decisions.jsonl for runs that:
  * have a user_email attached (signed-in user ran it),
  * are between OUTCOME_REMINDER_DAYS and OUTCOME_REMINDER_MAX_DAYS old,
  * have not been rated yet (no outcomes.jsonl row for the run_id),
  * have not already received a reminder (idempotency ledger).

Sends `outcome_reminder()` and records the send in history/outcome_reminders_sent.jsonl.

Configurable via env:
  OUTCOME_REMINDER_ENABLED         default "true"
  OUTCOME_REMINDER_INTERVAL_SECS   default 21600 (6h)
  OUTCOME_REMINDER_DAYS            default 14
  OUTCOME_REMINDER_MAX_DAYS        default 60  (stop nagging after this)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.tracking.history import get_recent_decisions

_SENT_FILE = Path("history/outcome_reminders_sent.jsonl")
_OUTCOMES_FILE = Path("history/outcomes.jsonl")


def _env_bool(name: str, default: bool = True) -> bool:
    return os.environ.get(name, "true" if default else "false").lower() == "true"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _days_old(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return 0.0
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def _sent_run_ids() -> set[str]:
    if not _SENT_FILE.exists():
        return set()
    out: set[str] = set()
    with open(_SENT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rid = rec.get("run_id")
            if rid:
                out.add(rid)
    return out


def _rated_run_ids() -> set[str]:
    if not _OUTCOMES_FILE.exists():
        return set()
    out: set[str] = set()
    with open(_OUTCOMES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rid = rec.get("run_id")
            if rid:
                out.add(rid)
    return out


def _record_sent(run_id: str, email: str) -> None:
    _SENT_FILE.parent.mkdir(exist_ok=True)
    with open(_SENT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "run_id": run_id,
            "email": email,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }) + "\n")


def send_due_outcome_reminders() -> dict[str, int]:
    """One pass. Returns counts: {scanned, sent, skipped}. Never raises."""
    if not _env_bool("OUTCOME_REMINDER_ENABLED"):
        return {"scanned": 0, "sent": 0, "skipped": 0, "disabled": 1}

    days_min = _env_int("OUTCOME_REMINDER_DAYS", 14)
    days_max = _env_int("OUTCOME_REMINDER_MAX_DAYS", 60)

    sent_ids = _sent_run_ids()
    rated_ids = _rated_run_ids()

    scanned = 0
    sent = 0
    skipped = 0

    # Scan the most recent 2000 decisions — older ones are past the max-days window.
    decisions = get_recent_decisions(limit=2000)
    from shared.email import outcome_reminder as _send

    for d in decisions:
        scanned += 1
        email = (d.get("user_email") or "").strip().lower()
        run_id = d.get("run_id")
        ts = d.get("timestamp") or ""
        if not email or not run_id or not ts:
            skipped += 1
            continue
        if run_id in sent_ids or run_id in rated_ids:
            skipped += 1
            continue
        age = _days_old(ts)
        if age < days_min or age > days_max:
            skipped += 1
            continue

        try:
            ok = _send(
                email=email,
                question=d.get("question", ""),
                winner=d.get("winner", ""),
                run_id=run_id,
                days_since=int(age),
            )
            if ok:
                _record_sent(run_id, email)
                sent += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"[reminder] send failed for {run_id}: {e}")
            skipped += 1

    if sent:
        print(f"[reminder] sent {sent} outcome reminder(s) "
              f"(scanned={scanned}, skipped={skipped})")
    return {"scanned": scanned, "sent": sent, "skipped": skipped}


async def outcome_reminder_loop() -> None:
    """Run forever. Call inside FastAPI lifespan as a background task."""
    interval = _env_int("OUTCOME_REMINDER_INTERVAL_SECS", 21600)  # 6h
    # Start with a short delay so the server comes up cleanly first.
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(send_due_outcome_reminders)
        except Exception as e:
            print(f"[reminder] loop error: {e}")
        await asyncio.sleep(interval)
