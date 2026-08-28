from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, String, Table, Text, func, select

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    metadata,
    sync_checkpoints,
    sync_runs,
)

sync_delta_stats = Table(
    "intel_sync_delta_stats",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(80), nullable=False),
    Column("status", String(30), nullable=False, default="completed"),
    Column("files_changed", Integer, nullable=False, default=0),
    Column("records_added", Integer, nullable=False, default=0),
    Column("records_updated", Integer, nullable=False, default=0),
    Column("records_unchanged", Integer, nullable=False, default=0),
    Column("records_retired", Integer, nullable=False, default=0),
    Column("message", Text),
    Column("checked_at", DateTime(timezone=True), server_default=func.now()),
)


def _iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return str(value)


def directory_freshness() -> dict:
    """Return a cheap, database-only directory freshness snapshot."""
    with connect() as conn:
        company_count = int(conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0)
        importer_count = int(
            conn.execute(select(func.count()).select_from(entities).where(entities.c.is_importer.is_(True))).scalar_one()
            or 0
        )
        relationship_count = int(
            conn.execute(select(func.count()).select_from(importer_relationships)).scalar_one() or 0
        )
        latest_completed = conn.execute(
            select(sync_runs)
            .where(sync_runs.c.status == "completed")
            .order_by(sync_runs.c.finished_at.desc(), sync_runs.c.id.desc())
            .limit(1)
        ).mappings().first()
        latest_delta = conn.execute(
            select(sync_delta_stats)
            .where(sync_delta_stats.c.status == "completed")
            .order_by(sync_delta_stats.c.checked_at.desc(), sync_delta_stats.c.id.desc())
            .limit(1)
        ).mappings().first()
        checkpoints = conn.execute(select(sync_checkpoints)).mappings().all()

    active = [row for row in checkpoints if str(row.get("status") or "") in {"running", "interrupted", "paused"}]
    active.sort(key=lambda row: _iso(row.get("updated_at")), reverse=True)
    checkpoint = active[0] if active else None

    if latest_delta:
        last_checked = _iso(latest_delta.get("checked_at"))
        last_source = str(latest_delta.get("source") or "")
        added = int(latest_delta.get("records_added") or 0)
        updated = int(latest_delta.get("records_updated") or 0)
        retired = int(latest_delta.get("records_retired") or 0)
        delta_available = True
    else:
        last_checked = _iso(latest_completed.get("finished_at")) if latest_completed else ""
        last_source = str(latest_completed.get("source") or "") if latest_completed else ""
        added = updated = retired = None
        delta_available = False

    status = "syncing" if checkpoint and checkpoint.get("status") == "running" else "ready"
    if checkpoint and checkpoint.get("status") in {"interrupted", "paused"}:
        status = str(checkpoint.get("status"))

    return {
        "status": status,
        "company_count": company_count,
        "importer_count": importer_count,
        "relationship_count": relationship_count,
        "last_checked": last_checked,
        "last_source": last_source,
        "checkpoint_source": str(checkpoint.get("source") or "") if checkpoint else "",
        "checkpoint_position": int(checkpoint.get("position") or 0) if checkpoint else 0,
        "delta_available": delta_available,
        "added": added,
        "updated": updated,
        "retired": retired,
    }
