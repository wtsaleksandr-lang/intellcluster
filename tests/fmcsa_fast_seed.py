from __future__ import annotations

from sqlalchemy import select

from intelligence.database import connect, entities, source_records
from intelligence.fmcsa_fast_seed import (
    SOURCE_KEY,
    fast_seed_fmcsa_records,
    fast_seed_readiness,
)
from intelligence.models import SourceRecord
from intelligence.repository import upsert_source_record

TEST_DOTS = {"9100001", "9100002", "9100003"}
FOREIGN_SOURCE = "fmcsa-fast-seed-foreign"


def _fmcsa_record(dot: str, name: str, *, status: str = "A") -> SourceRecord:
    return SourceRecord(
        source=SOURCE_KEY,
        source_record_id=dot,
        name=name,
        entity_type="company",
        country="US",
        region="TX",
        city="Houston",
        postal_code="77002",
        address="100 Main St, Houston, TX, 77002",
        attributes={
            "usdot_number": dot,
            "status": status,
            "power_units": 12,
            "total_drivers": 15,
            "dataset": "FMCSA Company Census File",
        },
    )


def _cleanup_test_rows() -> None:
    with connect() as conn:
        entity_ids = conn.execute(
            select(source_records.c.entity_id).where(
                (source_records.c.source == SOURCE_KEY)
                & (source_records.c.source_record_id.in_(TEST_DOTS))
            )
        ).scalars().all()
        foreign_ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source == FOREIGN_SOURCE)
        ).scalars().all()
        all_ids = {int(value) for value in [*entity_ids, *foreign_ids]}
        conn.execute(
            source_records.delete().where(
                (source_records.c.source == SOURCE_KEY)
                & (source_records.c.source_record_id.in_(TEST_DOTS))
            )
        )
        conn.execute(source_records.delete().where(source_records.c.source == FOREIGN_SOURCE))
        for entity_id in all_ids:
            remaining = conn.execute(
                select(source_records.c.id).where(source_records.c.entity_id == entity_id).limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    _cleanup_test_rows()
    records = [
        _fmcsa_record("9100001", "Fast Seed Logistics One LLC"),
        _fmcsa_record("9100002", "Fast Seed Logistics Two LLC", status="I"),
    ]
    try:
        with connect() as conn:
            initial = fast_seed_readiness(conn)
        assert initial["safe"] is True
        assert initial["non_fmcsa_us_entities"] == 0

        with connect() as conn:
            first = fast_seed_fmcsa_records(conn, records)
        assert first["created"] == 2
        assert first["existing"] == 0

        with connect() as conn:
            rows = conn.execute(
                select(
                    entities.c.slug,
                    entities.c.corporate_status,
                    entities.c.enrichment,
                    source_records.c.source_record_id,
                )
                .select_from(source_records.join(entities, source_records.c.entity_id == entities.c.id))
                .where(
                    (source_records.c.source == SOURCE_KEY)
                    & (source_records.c.source_record_id.in_({"9100001", "9100002"}))
                )
                .order_by(source_records.c.source_record_id)
            ).mappings().all()
            resumed_readiness = fast_seed_readiness(conn)
        assert len(rows) == 2
        assert rows[0]["slug"].endswith("usdot9100001")
        assert rows[0]["corporate_status"] == "Active"
        fleet = rows[0]["enrichment"]["fmcsa"]
        assert fleet["dot_number"] == "9100001"
        assert fleet["usdot_number"] == "9100001"
        assert fleet["legal_name"] == "Fast Seed Logistics One LLC"
        assert rows[1]["corporate_status"] == "Inactive"
        assert resumed_readiness["safe"] is True
        assert resumed_readiness["fmcsa_linked_us_entities"] >= 2

        with connect() as conn:
            resumed = fast_seed_fmcsa_records(conn, records)
        assert resumed["created"] == 0
        assert resumed["existing"] == 2

        foreign = SourceRecord(
            source=FOREIGN_SOURCE,
            source_record_id="FOREIGN-US-1",
            name="Existing U.S. Cross Source Entity Inc.",
            entity_type="company",
            country="US",
            region="NY",
            city="New York",
            attributes={},
        )
        with connect() as conn:
            foreign_id, _ = upsert_source_record(conn, foreign)
        try:
            with connect() as conn:
                blocked = fast_seed_readiness(conn)
                assert blocked["safe"] is False
                assert blocked["non_fmcsa_us_entities"] >= 1
                try:
                    fast_seed_fmcsa_records(
                        conn,
                        [_fmcsa_record("9100003", "Should Refuse Fast Seed LLC")],
                    )
                except RuntimeError as exc:
                    assert "non-FMCSA U.S. entities" in str(exc)
                else:
                    raise AssertionError("Fast FMCSA seed should refuse mixed-source U.S. canonical data")
        finally:
            with connect() as conn:
                conn.execute(source_records.delete().where(source_records.c.entity_id == foreign_id))
                conn.execute(entities.delete().where(entities.c.id == foreign_id))

        print("FMCSA fast seed checks OK")
        return 0
    finally:
        _cleanup_test_rows()


if __name__ == "__main__":
    raise SystemExit(run())
