from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from intelligence.database import (
    connect,
    source_records,
    supplier_relationships,
    sync_checkpoints,
    sync_runs,
)
from shared.admin import require_admin

router = APIRouter(prefix="/api/intelligence/admin", tags=["intelligence-admin"])

# These are conservative snapshot hints, not schema guarantees. Operators can
# override them when a public source publishes a materially different corpus.
_DEFAULT_TOTAL_HINTS = {
    "corporations_canada": 1_562_095,
    "canadian_importers": 485_934,
}
_ENV_TOTAL_KEYS = {
    "corporations_canada": "INTELLIGENCE_CORPORATIONS_CANADA_EXPECTED_TOTAL",
    "canadian_importers": "INTELLIGENCE_CANADIAN_IMPORTERS_EXPECTED_TOTAL",
}
_RESUME_RE = re.compile(r"Resume from\s+([\d,]+)", re.IGNORECASE)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _expected_totals(overrides: dict[str, int] | None = None) -> dict[str, int]:
    totals = dict(_DEFAULT_TOTAL_HINTS)
    for source, env_key in _ENV_TOTAL_KEYS.items():
        raw = os.environ.get(env_key, "").strip()
        if not raw:
            continue
        try:
            value = int(raw.replace(",", ""))
        except ValueError:
            continue
        if value > 0:
            totals[source] = value
    if overrides:
        for source, value in overrides.items():
            if int(value) > 0:
                totals[source] = int(value)
    return totals


def _resume_from(message: str | None) -> int | None:
    match = _RESUME_RE.search(str(message or ""))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _seconds_label(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def sync_status_snapshot(
    *,
    expected_totals: dict[str, int] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return persisted ingestion state without contacting any external source.

    The current run's speed is inferred from checkpoint movement since the
    persisted resume position. This works with the existing resumable ingestion
    process because the checkpoint advances after each committed batch, even
    though ``intel_sync_runs.records_written`` is finalized only when a run ends.
    """

    totals = _expected_totals(expected_totals)
    current_time = _utc(now) or datetime.now(timezone.utc)

    with connect() as conn:
        stored_rows = conn.execute(
            select(source_records.c.source, func.count().label("count"))
            .group_by(source_records.c.source)
        ).all()
        checkpoint_rows = conn.execute(select(sync_checkpoints)).mappings().all()
        run_rows = conn.execute(
            select(sync_runs).order_by(sync_runs.c.id.desc()).limit(100)
        ).mappings().all()
        supplier_rows = int(
            conn.execute(select(func.count()).select_from(supplier_relationships)).scalar_one()
            or 0
        )
        supplier_count = int(
            conn.execute(
                select(func.count(func.distinct(supplier_relationships.c.supplier_normalized)))
            ).scalar_one()
            or 0
        )

    stored = {str(source): int(count or 0) for source, count in stored_rows}
    checkpoints = {str(row["source"]): dict(row) for row in checkpoint_rows}
    latest_runs: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        source = str(row["source"])
        latest_runs.setdefault(source, dict(row))

    source_keys = sorted(set(stored) | set(checkpoints) | set(latest_runs) | set(totals))
    sources: list[dict[str, Any]] = []
    for source in source_keys:
        checkpoint = checkpoints.get(source) or {}
        run = latest_runs.get(source) or {}
        position = int(checkpoint.get("position") or stored.get(source) or 0)
        expected = totals.get(source)
        remaining = max(0, expected - position) if expected else None
        progress = round(min(100.0, position * 100.0 / expected), 2) if expected else None

        run_status = str(run.get("status") or checkpoint.get("status") or "unknown")
        started_at = _utc(run.get("started_at"))
        elapsed = (
            max(0.0, (current_time - started_at).total_seconds())
            if started_at and run_status == "running"
            else None
        )
        resume_from = _resume_from(run.get("message"))
        current_run_written = None
        rate = None
        eta_seconds = None
        if elapsed and elapsed > 0:
            if resume_from is not None and position >= resume_from:
                current_run_written = position - resume_from
            else:
                written = int(run.get("records_written") or 0)
                current_run_written = written if written > 0 else None
            if current_run_written is not None and current_run_written > 0:
                rate = current_run_written / elapsed
                if remaining is not None and rate > 0:
                    eta_seconds = remaining / rate

        sources.append(
            {
                "source": source,
                "status": run_status,
                "stored_source_records": stored.get(source, 0),
                "checkpoint_position": position,
                "expected_total_hint": expected,
                "progress_percent": progress,
                "remaining_records_estimate": remaining,
                "current_run_written_estimate": current_run_written,
                "writes_per_second_estimate": round(rate, 2) if rate else None,
                "writes_per_hour_estimate": round(rate * 3600) if rate else None,
                "eta_seconds_estimate": round(eta_seconds) if eta_seconds is not None else None,
                "eta_label": _seconds_label(eta_seconds),
                "checkpoint_updated_at": checkpoint.get("updated_at"),
                "run_started_at": run.get("started_at"),
                "run_finished_at": run.get("finished_at"),
                "run_id": run.get("id"),
                "message": checkpoint.get("message") or run.get("message"),
            }
        )

    return {
        "generated_at": current_time,
        "sources": sources,
        "supplier_index": {
            "relationships": supplier_rows,
            "suppliers": supplier_count,
            "population_rule": (
                "Named supplier relationships are derived from cached ImportYeti company profiles. "
                "Corporations Canada and Canadian Importers ingestion does not populate this table."
            ),
            "safe_backfill_command": "python -m intelligence.supplier_explorer",
            "backfill_network_calls": False,
        },
        "notes": [
            "Expected totals are snapshot hints and may drift as public datasets change.",
            "ETA is derived from committed checkpoint movement; it does not contact the source website.",
        ],
    }


@router.get("/sync-status")
async def intelligence_admin_sync_status(
    _admin: bool = Depends(require_admin),
) -> dict[str, Any]:
    return sync_status_snapshot()


if __name__ == "__main__":
    import json

    print(json.dumps(sync_status_snapshot(), indent=2, default=str))
