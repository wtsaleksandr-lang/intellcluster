from __future__ import annotations

from intelligence.database import connect, entities, importer_relationships, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_by_slug, search_entities, upsert_source_record


def run() -> int:
    corporation = SourceRecord(
        source="corporations_canada",
        source_record_id="TEST-987654",
        name="Persistence Test Auto Parts Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Hamilton",
        postal_code="L8P 1A1",
        attributes={"corporation_number": "TEST-987654", "status": "active"},
    )
    importer = SourceRecord(
        source="canadian_importers",
        source_record_id="test-importer|Persistence Test Auto Parts Inc.|870892|China|Hamilton",
        name="Persistence Test Auto Parts Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Hamilton",
        attributes={"activity_year": 2023, "hs6": "870892", "origin_country": "China", "dataset": "test"},
    )
    with connect() as conn:
        entity_id, created = upsert_source_record(conn, corporation)
        importer_id, _ = upsert_source_record(conn, importer)
        assert created
        assert entity_id == importer_id
        rows = search_entities(conn, q="Persistence Test", province="ON", origin="China", hs="870892")
        assert rows and rows[0]["is_importer"] is True
        slug = rows[0]["slug"]
        company = get_entity_by_slug(conn, slug)
        assert company and "870892" in company["hs_codes"] and "China" in company["origins"]
        conn.execute(importer_relationships.delete().where(importer_relationships.c.entity_id == entity_id))
        conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
        conn.execute(entities.delete().where(entities.c.id == entity_id))
    print("INTELLIGENCE PERSISTENCE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
