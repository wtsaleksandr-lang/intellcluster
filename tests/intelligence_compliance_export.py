from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import set_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)


def run() -> int:
    record = SourceRecord(
        source="test_us_company",
        source_record_id="COMPLIANCE-EXPORT-1",
        name="Compliance Export Test LLC",
        entity_type="company",
        country="US",
        region="TX",
        city="Houston",
        postal_code="77002",
        attributes={},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = conn.execute(entities.select().where(entities.c.id == entity_id)).mappings().one()["slug"]
        set_entity_enrichment(
            conn,
            entity_id,
            "epa_echo",
            {
                "facility_count": 1,
                "major_facility_count": 1,
                "active_facility_count": 1,
                "inspections_5y": 3,
                "formal_actions_5y": 1,
                "informal_actions_5y": 2,
                "penalty_events_5y": 1,
                "total_penalties": 2500,
                "facilities": [
                    {
                        "registry_id": "110000000001",
                        "name": "Compliance Export Test Facility",
                        "address": "100 Test St",
                        "city": "Houston",
                        "state": "TX",
                        "postal_code": "77002",
                        "detail_url": "https://echo.epa.gov/example",
                    }
                ],
            },
        )
        set_entity_enrichment(
            conn,
            entity_id,
            "osha",
            {
                "inspection_count_shown": 1,
                "violations_shown": 2,
                "latest_inspection": "08/01/2026",
                "states": ["TX"],
                "naics": ["484110"],
                "inspections": [
                    {
                        "activity": "1234567.001",
                        "date_opened": "08/01/2026",
                        "state": "TX",
                        "type": "Referral",
                        "scope": "Partial",
                        "naics": "484110",
                        "violations": 2,
                        "establishment_name": "Compliance Export Test LLC",
                        "detail_url": "https://www.osha.gov/example",
                    }
                ],
            },
        )

    try:
        response = client.get(f"/data/company/{slug}/compliance.csv")
        if response.status_code != 200:
            print(f"Compliance export FAILED: HTTP {response.status_code}")
            return 1
        text = response.text
        required = (
            "epa_summary,facility_count,1",
            "epa_facility,110000000001,Compliance Export Test Facility",
            "osha_summary,inspection_count_shown,1",
            "osha_summary,violations_shown,2",
            "osha_inspection,1234567.001,Compliance Export Test LLC",
        )
        missing = [item for item in required if item not in text]
        disposition = response.headers.get("content-disposition", "")
        if missing or "compliance.csv" not in disposition:
            print("Compliance export FAILED")
            if missing:
                print("Missing:", missing)
            if "compliance.csv" not in disposition:
                print("Missing compliance filename")
            return 1
        print("Compliance export OK")
        return 0
    finally:
        with connect() as conn:
            conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
            conn.execute(entities.delete().where(entities.c.id == entity_id))


if __name__ == "__main__":
    raise SystemExit(run())
