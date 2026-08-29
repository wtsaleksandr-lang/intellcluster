from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import set_entity_enrichment, upsert_source_record
from main_data import app


client = TestClient(app)
SOURCE = "search-us-signal-regression"


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
        source_record_id="US-SIGNAL-1001",
        name="IntellCluster Signal Test Logistics LLC",
        entity_type="company",
        country="US",
        region="TX",
        city="Houston",
        attributes={"dataset": SOURCE},
    )
    try:
        with connect() as conn:
            entity_id, _ = upsert_source_record(conn, record)
            slug = str(
                conn.execute(
                    select(entities.c.slug).where(entities.c.id == entity_id)
                ).scalar_one()
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "fmcsa",
                {"dot_number": "7654321", "power_units": 54, "total_drivers": 61},
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "usaspending",
                {"contract_awards_shown": 7, "contract_award_value_shown": 3_500_000},
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "sec_edgar",
                {"ticker": "ICSG", "latest_filing_form": "10-Q"},
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "epa_echo",
                {"facility_count": 3},
            )
            set_entity_enrichment(
                conn,
                entity_id,
                "osha",
                {"inspection_count_shown": 2},
            )

        response = client.get(
            "/data/search?q=IntellCluster%20Signal%20Test&country=US"
        )
        assert response.status_code == 200
        text = response.text
        assert f'/data/company/{slug}' in text
        assert "intellcluster-us-search-signal-data" in text
        assert '"label":"Fleet","value":"54 units · USDOT 7654321"' in text
        assert '"label":"Federal Awards","value":"$3.5M"' in text
        assert '"label":"SEC EDGAR","value":"ICSG"' in text
        assert '"label":"EPA Facilities","value":"3 cached"' in text
        assert text.count('"kind":"fleet"') == 1

        print("U.S. search signal checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
