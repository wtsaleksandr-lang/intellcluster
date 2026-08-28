from __future__ import annotations

from sqlalchemy import and_, select, update
from sqlalchemy.engine import Connection

from intelligence.database import json_safe, source_records
from intelligence.models import SourceRecord
from intelligence.repository import upsert_source_record


def upsert_source_record_incremental(conn: Connection, record: SourceRecord) -> tuple[int, bool, str]:
    """Upsert one source record while distinguishing new/updated/unchanged.

    Unlike the bulk bootstrap path, unchanged records do not touch the entity or
    source row. This is the core primitive for cheap recurring maintenance syncs.
    Returns (entity_id, entity_created, state).
    """
    existing = conn.execute(
        select(
            source_records.c.id,
            source_records.c.entity_id,
            source_records.c.source_url,
            source_records.c.attributes,
            source_records.c.source_updated_at,
        ).where(
            and_(
                source_records.c.source == record.source,
                source_records.c.source_record_id == record.source_record_id,
            )
        )
    ).mappings().first()

    attrs = json_safe(record.attributes if isinstance(record.attributes, dict) else {})
    if existing is not None:
        same = (
            (existing["attributes"] or {}) == attrs
            and (existing["source_url"] or "") == (record.source_url or "")
            and str(existing["source_updated_at"] or "") == str(record.source_updated_at or "")
        )
        if same:
            return int(existing["entity_id"]), False, "unchanged"

    entity_id, entity_created = upsert_source_record(conn, record)
    if existing is None:
        return entity_id, entity_created, "new"

    conn.execute(
        update(source_records)
        .where(source_records.c.id == existing["id"])
        .values(
            entity_id=entity_id,
            source_url=record.source_url,
            attributes=attrs,
            source_updated_at=record.source_updated_at,
        )
    )
    return entity_id, entity_created, "updated"
