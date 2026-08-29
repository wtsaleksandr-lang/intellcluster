from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from intelligence.data_quality import data_quality_report
from intelligence.database import (
    connect,
    entities,
    source_records,
    supplier_relationships,
    sync_checkpoints,
    sync_runs,
)
from intelligence.models import SourceRecord
from intelligence.post_ingest_readiness import post_ingest_readiness
from intelligence.repository import upsert_source_record
from intelligence.supplier_backfill import SOURCE_KEY, run_supplier_backfill
from main_data import app
from shared.admin import ADMIN_COOKIE, create_admin_token

TEST_SOURCE = "post-ingest-readiness-test"


def _cleanup() -> None:
    with connect() as conn:
        ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source == TEST_SOURCE)
        ).scalars().all()
        for entity_id in ids:
            conn.execute(
                supplier_relationships.delete().where(
                    supplier_relationships.c.importer_entity_id == int(entity_id)
                )
            )
        conn.execute(source_records.delete().where(source_records.c.source == TEST_SOURCE))
        for entity_id in ids:
            remaining = conn.execute(
                select(source_records.c.id)
                .where(source_records.c.entity_id == int(entity_id))
                .limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == int(entity_id)))
        conn.execute(sync_checkpoints.delete().where(sync_checkpoints.c.source == SOURCE_KEY))
        conn.execute(sync_runs.delete().where(sync_runs.c.source == SOURCE_KEY))


def _seed(name: str, source_id: str, supplier: str) -> int:
    record = SourceRecord(
        source=TEST_SOURCE,
        source_record_id=source_id,
        name=name,
        entity_type="company",
        country="US",
        region="CA",
        city="Long Beach",
        postal_code="90802",
        attributes={"dataset": TEST_SOURCE},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        conn.execute(
            update(entities)
            .where(entities.c.id == entity_id)
            .values(
                enrichment={
                    "importyeti": {
                        "_cachedAt": "2026-08-29T12:00:00Z",
                        "suppliers_table": [
                            {
                                "supplier_name": supplier,
                                "country": "CN",
                                "total_shipments": 12,
                                "product_descriptions": ["Test components"],
                            }
                        ],
                        "recent_bols": [],
                    }
                }
            )
        )
    return int(entity_id)


def run() -> int:
    _cleanup()
    try:
        first = _seed("Backfill Resume One LLC", "READY-1", "Supplier Alpha Ltd")
        second = _seed("Backfill Resume Two LLC", "READY-2", "Supplier Beta Ltd")
        assert second > first

        with connect() as conn:
            conn.execute(
                sync_checkpoints.insert().values(
                    source=SOURCE_KEY,
                    position=first - 1,
                    status="paused",
                    message="Test checkpoint",
                )
            )

        paused = run_supplier_backfill(resume=True, batch_size=50, limit_entities=1)
        assert paused["status"] == "paused"
        assert paused["network_calls"] == 0
        assert paused["end_entity_id"] == first
        assert paused["supplier_relationships_written"] == 1

        completed = run_supplier_backfill(resume=True, batch_size=50)
        assert completed["status"] == "completed"
        assert completed["network_calls"] == 0
        assert completed["end_entity_id"] >= second
        with connect() as conn:
            relationship_count = int(
                conn.execute(
                    select(func.count())
                    .select_from(supplier_relationships)
                    .where(supplier_relationships.c.importer_entity_id.in_([first, second]))
                ).scalar_one()
                or 0
            )
        assert relationship_count == 2

        report = post_ingest_readiness()
        assert report["network_calls"] == 0
        assert report["paid_sources_called"] is False
        assert "recommended_sequence" in report
        assert report["supplier_index"]["recommended_command"] == "python -m intelligence.supplier_backfill"

        quality = data_quality_report()
        assert quality["network_calls"] == 0
        assert quality["paid_sources_called"] is False
        assert quality["checks"]["orphan_source_records"] == 0
        assert quality["checks"]["orphan_supplier_relationships"] == 0

        anonymous = TestClient(app).get("/api/intelligence/admin/post-ingest-readiness")
        assert anonymous.status_code == 401
        admin = TestClient(app)
        admin.cookies.set(
            ADMIN_COOKIE,
            create_admin_token(os.environ["ADMIN_USERNAME"]),
        )
        response = admin.get("/api/intelligence/admin/post-ingest-readiness")
        assert response.status_code == 200, response.text
        assert response.json()["paid_sources_called"] is False

        print("Post-ingest readiness checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
