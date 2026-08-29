from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_by_slug, set_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)


def _seed_company(*, source_id: str, name: str, country: str, region: str, city: str) -> tuple[int, str]:
    record = SourceRecord(
        source="api-regression",
        source_record_id=source_id,
        name=name,
        entity_type="company",
        country=country,
        region=region,
        city=city,
        attributes={"dataset": "api-regression"},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = conn.execute(entities.select().where(entities.c.id == entity_id)).mappings().one()["slug"]
    return entity_id, str(slug)


def _cleanup(*entity_ids: int) -> None:
    with connect() as conn:
        for entity_id in entity_ids:
            conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
            conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    us_id, us_slug = _seed_company(
        source_id="API-US-1001",
        name="IntellCluster API Regression Logistics LLC",
        country="US",
        region="TX",
        city="Houston",
    )
    ca_id, ca_slug = _seed_company(
        source_id="API-CA-1001",
        name="IntellCluster API Regression Canada Inc.",
        country="CA",
        region="ON",
        city="Hamilton",
    )
    try:
        with connect() as conn:
            set_entity_enrichment(conn, us_id, "fmcsa", {"dot_number": "1234567", "power_units": 12})
            set_entity_enrichment(conn, us_id, "usaspending", {"name": "IntellCluster API Regression Logistics LLC", "awards": []})
            set_entity_enrichment(conn, us_id, "epa_echo", {"facility_count": 1, "facilities": []})
            set_entity_enrichment(conn, us_id, "osha", {"inspection_count_shown": 0, "inspections": []})
            assert get_entity_by_slug(conn, us_slug) is not None

        response = client.post(f"/api/intelligence/company/{us_slug}/enrich/us-public")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("paid_sources_called") is False
        lookup = payload.get("lookup") or {}
        assert lookup.get("fmcsa") == "cached"
        assert lookup.get("usaspending") == "cached"
        assert lookup.get("epa_echo") == "cached"
        assert lookup.get("osha") == "cached"

        ca_response = client.post(f"/api/intelligence/company/{ca_slug}/enrich/us-public")
        assert ca_response.status_code == 400, ca_response.text
        ca_payload = ca_response.json()
        assert ca_payload.get("detail") == "U.S. public enrichment applies to U.S. companies"
        assert "error" not in ca_payload

        missing = client.post("/api/intelligence/company/definitely-not-indexed/enrich/us-public")
        assert missing.status_code == 404
        assert missing.json().get("detail") == "Company not found"

        print("Intelligence API regression checks OK")
        return 0
    finally:
        _cleanup(us_id, ca_id)


if __name__ == "__main__":
    raise SystemExit(run())
