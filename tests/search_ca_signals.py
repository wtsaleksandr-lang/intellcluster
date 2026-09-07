from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import set_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)
SOURCE = "search-ca-signal-regression"


def _cleanup() -> None:
    with connect() as conn:
        ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source == SOURCE)
        ).scalars().all()
        conn.execute(source_records.delete().where(source_records.c.source == SOURCE))
        for entity_id in {int(value) for value in ids}:
            remaining = conn.execute(
                select(source_records.c.id).where(source_records.c.entity_id == entity_id).limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    _cleanup()
    record = SourceRecord(
        source=SOURCE,
        source_record_id="CA-SIGNAL-1001",
        name="IntellCluster Canada Signal Systems Inc",
        entity_type="company",
        country="CA",
        region="ON",
        city="Toronto",
        attributes={"dataset": SOURCE},
    )
    try:
        with connect() as conn:
            entity_id, _ = upsert_source_record(conn, record)
            slug = str(
                conn.execute(select(entities.c.slug).where(entities.c.id == entity_id)).scalar_one()
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "canadabuys_contracts",
                {"contract_count": 6, "cad_value_shown": 2_750_000},
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "uspto_patents",
                {"total_patents": 4, "latest_grant_date": "2025-09-30"},
            )

        response = client.get(
            "/data/search?q=IntellCluster%20Canada%20Signal&country=CA"
        )
        assert response.status_code == 200
        text = response.text
        assert f'/data/company/{slug}' in text
        assert "intellcluster-us-search-signal-data" in text
        assert '"label":"CanadaBuys","value":"$2.8M CAD · 6 contracts"' in text
        assert '"target":"canadabuys-contract-intelligence","kind":"contract-ca"' in text
        assert '"label":"Patents","value":"4 granted · latest 2025"' in text
        assert '"target":"uspto-patent-intelligence","kind":"patent"' in text

        print("Canada search signal checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
