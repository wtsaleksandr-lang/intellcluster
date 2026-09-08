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
from intelligence.launch_gate import launch_gate_report, production_environment_report
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


def _environment_gate_checks() -> None:
    names = (
        "DATABASE_URL",
        "PUBLIC_BASE_URL",
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "ADMIN_SECRET_KEY",
        "IMPORTYETI_ALLOW_LIVE",
        "RATE_LIMIT_ENABLED",
        "DEBUG",
        "SEC_EDGAR_USER_AGENT",
        "PLAUSIBLE_DOMAIN",
    )
    previous = {name: os.environ.get(name) for name in names}
    try:
        os.environ.pop("DATABASE_URL", None)
        os.environ["PUBLIC_BASE_URL"] = "http://localhost:5000"
        os.environ["ADMIN_USERNAME"] = "admin"
        os.environ["ADMIN_PASSWORD"] = "short"
        os.environ["ADMIN_SECRET_KEY"] = "change-me"
        os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
        os.environ["RATE_LIMIT_ENABLED"] = "false"
        os.environ["DEBUG"] = "true"
        unsafe = production_environment_report(production=True)
        assert unsafe["healthy"] is False
        joined = "\n".join(unsafe["blockers"])
        assert "DATABASE_URL" in joined
        assert "PUBLIC_BASE_URL" in joined
        assert "ADMIN_PASSWORD" in joined
        assert "ADMIN_SECRET_KEY" in joined
        assert "IMPORTYETI_ALLOW_LIVE" in joined
        assert "RATE_LIMIT_ENABLED" in joined
        assert "DEBUG" in joined
        assert "short" not in str(unsafe)
        assert "change-me" not in str(unsafe)

        os.environ["DATABASE_URL"] = "postgresql://example.invalid/intellcluster"
        os.environ["PUBLIC_BASE_URL"] = "https://intellcluster.com"
        os.environ["ADMIN_USERNAME"] = "ops@example.com"
        os.environ["ADMIN_PASSWORD"] = "long-random-admin-passphrase"
        os.environ["ADMIN_SECRET_KEY"] = "random-admin-signing-key-1234567890"
        os.environ["IMPORTYETI_ALLOW_LIVE"] = "false"
        os.environ["RATE_LIMIT_ENABLED"] = "true"
        os.environ["DEBUG"] = "false"
        os.environ["SEC_EDGAR_USER_AGENT"] = "IntellCluster test contact@example.com"
        os.environ["PLAUSIBLE_DOMAIN"] = "intellcluster.com"
        safe = production_environment_report(production=True)
        assert safe["healthy"] is True, safe
        assert safe["blockers"] == []
        assert safe["paid_sources_called"] is False
        assert safe["network_calls"] == 0
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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

        _environment_gate_checks()
        gate = launch_gate_report(production=False)
        assert gate["network_calls"] == 0
        assert gate["paid_sources_called"] is False
        assert "ingestion" in gate
        assert "data_quality" in gate
        assert "environment" in gate
        assert isinstance(gate["ready_to_launch"], bool)

        anonymous = TestClient(app).get("/api/intelligence/admin/post-ingest-readiness")
        assert anonymous.status_code == 401
        anonymous_gate = TestClient(app).get("/api/intelligence/admin/launch-gate")
        assert anonymous_gate.status_code == 401

        admin = TestClient(app)
        admin.cookies.set(
            ADMIN_COOKIE,
            create_admin_token(os.environ["ADMIN_USERNAME"]),
        )
        response = admin.get("/api/intelligence/admin/post-ingest-readiness")
        assert response.status_code == 200, response.text
        assert response.json()["paid_sources_called"] is False
        gate_response = admin.get("/api/intelligence/admin/launch-gate?production=false")
        assert gate_response.status_code == 200, gate_response.text
        assert gate_response.json()["paid_sources_called"] is False
        assert gate_response.json()["network_calls"] == 0

        print("Post-ingest readiness and launch-gate checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
