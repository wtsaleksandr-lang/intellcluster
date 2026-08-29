from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, exists, insert, select
from sqlalchemy.engine import Connection

from intelligence.database import entities, json_safe, normalize_name, slugify, source_records
from intelligence.models import SourceRecord

SOURCE_KEY = "fmcsa_company_census"
STATUS_MAP = {"A": "Active", "P": "Pending", "I": "Inactive"}


def _chunks(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _fleet_payload(record: SourceRecord) -> dict[str, Any]:
    attrs = record.attributes if isinstance(record.attributes, dict) else {}
    code = str(attrs.get("status") or "").strip().upper()
    return {
        "dot_number": str(attrs.get("usdot_number") or record.source_record_id).strip() or None,
        "status_code": code or None,
        "status": STATUS_MAP.get(code, code or None),
        "dba_name": attrs.get("dba_name"),
        "phone": attrs.get("phone"),
        "cell_phone": attrs.get("cell_phone"),
        "power_units": attrs.get("power_units"),
        "total_drivers": attrs.get("total_drivers"),
        "mcs150_date": attrs.get("mcs150_date"),
        "add_date": attrs.get("add_date"),
        "carrier_operation": attrs.get("carrier_operation"),
        "dataset": attrs.get("dataset") or "FMCSA Company Census File",
    }


def assert_fast_seed_safe(conn: Connection) -> None:
    """Refuse fast bootstrap when unrelated U.S. canonical entities already exist.

    Fast seed intentionally creates one canonical entity per USDOT registration to
    avoid millions of row-by-row entity-resolution queries. It is safe for a fresh
    U.S. market and for resuming a previous FMCSA bootstrap. If U.S. entities from
    other sources already exist, the conservative resolver must be used instead so
    cross-source duplicates are not introduced.
    """
    fmcsa_for_entity = exists(
        select(source_records.c.id).where(
            and_(
                source_records.c.entity_id == entities.c.id,
                source_records.c.source == SOURCE_KEY,
            )
        )
    )
    foreign_us = conn.execute(
        select(entities.c.id)
        .where(entities.c.country == "US", ~fmcsa_for_entity)
        .limit(1)
    ).scalar_one_or_none()
    if foreign_us is not None:
        raise RuntimeError(
            "FMCSA fast seed is unsafe because non-FMCSA U.S. entities already exist. "
            "Use the conservative FMCSA ingestion path so entity resolution can run."
        )


def _existing_source_ids(conn: Connection, record_ids: list[str]) -> set[str]:
    found: set[str] = set()
    for batch in _chunks(record_ids):
        rows = conn.execute(
            select(source_records.c.source_record_id).where(
                source_records.c.source == SOURCE_KEY,
                source_records.c.source_record_id.in_(batch),
            )
        ).scalars().all()
        found.update(str(value) for value in rows)
    return found


def _existing_slugs(conn: Connection, slugs: list[str]) -> set[str]:
    found: set[str] = set()
    for batch in _chunks(slugs):
        rows = conn.execute(select(entities.c.slug).where(entities.c.slug.in_(batch))).scalars().all()
        found.update(str(value) for value in rows)
    return found


def fast_seed_fmcsa_records(conn: Connection, records: list[SourceRecord]) -> dict[str, int]:
    """Bulk-create canonical FMCSA entities and source rows for an initial U.S. seed.

    PostgreSQL uses SQLAlchemy's insert-many-values/RETURNING path so a page can be
    created with a small number of database round trips. SQLite deliberately uses
    individual entity inserts for test compatibility, while source rows are still
    inserted as a batch.
    """
    assert_fast_seed_safe(conn)
    valid: list[SourceRecord] = []
    seen_ids: set[str] = set()
    for record in records:
        record_id = str(record.source_record_id or "").strip()
        if (
            record.source != SOURCE_KEY
            or str(record.country or "").upper() != "US"
            or not record_id.isdigit()
            or record_id in seen_ids
        ):
            continue
        seen_ids.add(record_id)
        valid.append(record)

    if not valid:
        return {"received": len(records), "created": 0, "existing": 0, "skipped": len(records)}

    existing_ids = _existing_source_ids(conn, [record.source_record_id for record in valid])
    pending = [record for record in valid if record.source_record_id not in existing_ids]
    if not pending:
        return {
            "received": len(records),
            "created": 0,
            "existing": len(valid),
            "skipped": len(records) - len(valid),
        }

    entity_values: list[dict[str, Any]] = []
    generated_slugs: list[str] = []
    for record in pending:
        attrs = record.attributes if isinstance(record.attributes, dict) else {}
        code = str(attrs.get("status") or "").strip().upper()
        slug = slugify(record.name, f"usdot{record.source_record_id}")
        generated_slugs.append(slug)
        entity_values.append(
            {
                "slug": slug,
                "entity_type": record.entity_type,
                "canonical_name": record.name,
                "name_normalized": normalize_name(record.name),
                "country": "US",
                "region": record.region,
                "city": record.city,
                "postal_code": record.postal_code,
                "address": record.address,
                "website": record.website,
                "corporation_number": None,
                "corporate_status": STATUS_MAP.get(code, code or None),
                "incorporated_year": None,
                "is_importer": False,
                "enrichment": {"fmcsa": json_safe(_fleet_payload(record))},
            }
        )

    collisions = _existing_slugs(conn, generated_slugs)
    if collisions:
        sample = sorted(collisions)[0]
        raise RuntimeError(f"FMCSA fast seed slug collision: {sample}")

    entity_ids: list[int] = []
    if conn.dialect.name == "postgresql":
        stmt = insert(entities).returning(entities.c.id, sort_by_parameter_order=True)
        entity_ids = [int(value) for value in conn.execute(stmt, entity_values).scalars().all()]
    else:
        for values in entity_values:
            result = conn.execute(insert(entities).values(**values))
            entity_ids.append(int(result.inserted_primary_key[0]))

    if len(entity_ids) != len(pending):
        raise RuntimeError("FMCSA fast seed could not map inserted entity IDs to source records")

    source_values = []
    for entity_id, record in zip(entity_ids, pending, strict=True):
        attrs = record.attributes if isinstance(record.attributes, dict) else {}
        source_values.append(
            {
                "entity_id": entity_id,
                "source": SOURCE_KEY,
                "source_record_id": record.source_record_id,
                "source_url": record.source_url,
                "attributes": json_safe(attrs),
                "source_updated_at": record.source_updated_at,
            }
        )
    conn.execute(insert(source_records), source_values)
    return {
        "received": len(records),
        "created": len(pending),
        "existing": len(existing_ids),
        "skipped": len(records) - len(valid),
    }
