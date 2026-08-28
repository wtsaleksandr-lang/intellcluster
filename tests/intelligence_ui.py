from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, importer_relationships, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_by_slug, search_entities, upsert_source_record
from main_data import app

client = TestClient(app)


def _seed_ui_company() -> tuple[int, str]:
    corporation = SourceRecord(
        source="corporations_canada",
        source_record_id="UI-TEST-1001",
        name="IntellCluster UI Test Importer Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Hamilton",
        postal_code="L8P 1A1",
        attributes={"corporation_number": "UI-TEST-1001", "status": "active"},
    )
    importer = SourceRecord(
        source="canadian_importers",
        source_record_id="ui-test|IntellCluster UI Test Importer Inc.|870892|China|Hamilton",
        name="IntellCluster UI Test Importer Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Hamilton",
        attributes={
            "activity_year": 2023,
            "hs6": "870892",
            "origin_country": "China",
            "product_description": "Motor vehicle exhaust parts",
            "dataset": "ui-test",
        },
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, corporation)
        importer_id, _ = upsert_source_record(conn, importer)
        assert entity_id == importer_id
        rows = search_entities(conn, q="IntellCluster UI Test Importer")
        assert rows
        slug = rows[0]["slug"]
        assert get_entity_by_slug(conn, slug)
        return entity_id, slug


def _cleanup(entity_id: int) -> None:
    with connect() as conn:
        conn.execute(importer_relationships.delete().where(importer_relationships.c.entity_id == entity_id))
        conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
        conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    entity_id, slug = _seed_ui_company()
    try:
        checks = [
            ("/data", 200),
            ("/data/search", 200),
            ("/data/search?type=Importer&province=ON&sort=buyer_score", 200),
            ("/data/search?city=Hamilton&incorporated_from=2010&incorporated_to=2026&website=no", 200),
            ("/data/search?hs=8708&origin=China&page=2", 200),
            ("/data/search?sort=newest", 200),
            ("/data/suggest?q=IntellCluster", 200),
            ("/data/hs/87", 200),
            ("/data/hs/8708", 200),
            ("/data/hs/870892", 200),
            ("/data/origin/China", 200),
            ("/data/location/ON", 200),
            ("/data/location/ON/Hamilton", 200),
            (f"/data/company/{slug}", 200),
            (f"/data/company/{slug}/export.csv", 200),
            ("/api/intelligence/health", 200),
            ("/api/intelligence/sources", 200),
        ]
        failed = []
        for path, expected in checks:
            response = client.get(path, follow_redirects=False)
            if response.status_code != expected:
                failed.append(f"{path}: {response.status_code} != {expected}")
        if failed:
            print("Intelligence UI smoke FAILED")
            print("\n".join(failed))
            return 1
        print(f"Intelligence UI smoke OK: {len(checks)} checks")
        return 0
    finally:
        _cleanup(entity_id)


if __name__ == "__main__":
    raise SystemExit(run())
