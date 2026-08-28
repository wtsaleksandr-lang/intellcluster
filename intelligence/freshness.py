from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from intelligence.database import connect, entities, importer_relationships, sync_checkpoints, sync_runs


def _iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    return str(value)


def directory_freshness() -> dict:
    """Return a cheap, database-only directory freshness snapshot.

    During the initial corpus backfill we intentionally avoid claiming daily
    add/update/retire deltas that are not yet measured. The UI can later consume
    those fields unchanged when incremental sync statistics are persisted.
    """
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
        checkpoints = conn.execute(select(sync_checkpoints)).mappings().all()

    active = [row for row in checkpoints if str(row.get("status") or "") in {"running", "interrupted", "paused"}]
    active.sort(key=lambda row: _iso(row.get("updated_at")), reverse=True)
    checkpoint = active[0] if active else None

    last_checked = _iso(latest_completed.get("finished_at")) if latest_completed else ""
    last_source = str(latest_completed.get("source") or "") if latest_completed else ""
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
        "delta_available": False,
        "added": None,
        "updated": None,
        "retired": None,
    }
