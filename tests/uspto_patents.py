from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from intelligence.country_intelligence import profile_capabilities
from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_enrichment, upsert_source_record
from intelligence.uspto_bulk import ingest_patentsview_csv, read_patentsview_csv
from main_data import app

client = TestClient(app)


def _seed_company() -> tuple[int, str]:
    record = SourceRecord(
        source="uspto-patent-test",
        source_record_id="USPTO-PATENT-COMPANY-1",
        name="Patent Signal Labs Inc",
        entity_type="company",
        country="US",
        region="TX",
        city="Austin",
        postal_code="78701",
        attributes={"dataset": "uspto-patent-test"},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = str(
            conn.execute(entities.select().where(entities.c.id == entity_id))
            .mappings()
            .one()["slug"]
        )
    return int(entity_id), slug


def _write_fixture(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "patent_id",
                "patent_title",
                "patent_date",
                "assignee_id",
                "assignee_organization",
                "assignee_city",
                "assignee_state",
                "assignee_country",
                "cpc_section",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "patent_id": "12345678",
                "patent_title": "Adaptive freight sensing platform",
                "patent_date": "2025-11-04",
                "assignee_id": "org_test_1",
                "assignee_organization": "Patent Signal Labs, Inc.",
                "assignee_city": "Austin",
                "assignee_state": "TX",
                "assignee_country": "US",
                "cpc_section": "G",
            }
        )
        writer.writerow(
            {
                "patent_id": "11987654",
                "patent_title": "Distributed cargo routing system",
                "patent_date": "2024-08-13",
                "assignee_id": "org_test_1",
                "assignee_organization": "Patent Signal Labs Inc",
                "assignee_city": "Austin",
                "assignee_state": "TX",
                "assignee_country": "United States",
                "cpc_section": "G",
            }
        )


def _cleanup(entity_id: int) -> None:
    with connect() as conn:
        conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
        conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    entity_id, slug = _seed_company()
    try:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "pvannual-test.csv"
            _write_fixture(fixture)

            rows = read_patentsview_csv(fixture)
            assert len(rows) == 2
            assert rows[0]["assignee_name"] == "Patent Signal Labs, Inc."
            assert rows[1]["assignee_country"] == "US"

            dry = ingest_patentsview_csv(fixture, dry_run=True)
            assert dry["entities_matched"] == 1
            assert dry["entities_updated"] == 0
            with connect() as conn:
                assert "uspto_patents" not in get_entity_enrichment(conn, entity_id)

            stats = ingest_patentsview_csv(fixture)
            assert stats == {
                "rows_read": 2,
                "assignees_seen": 1,
                "entities_matched": 1,
                "entities_updated": 1,
                "ambiguous_or_unmatched": 0,
            }

        with connect() as conn:
            enrichment = get_entity_enrichment(conn, entity_id)
        patents = enrichment["uspto_patents"]
        assert patents["network_calls"] is False
        assert patents["source"].startswith("USPTO PatentsView")
        assert patents["total_patents"] == 2
        assert patents["latest_grant_date"] == "2025-11-04"
        assert patents["technology_sections"] == [{"code": "G", "count": 2}]
        assert patents["patents"][0]["patent_id"] == "12345678"

        capabilities = profile_capabilities(
            {"country": "US", "enrichment": enrichment}, country="US"
        )
        assert capabilities["sections"]["patents"]["status"] == "cached"
        assert "USPTO PatentsView" in str(capabilities["sections"]["patents"]["source"])

        export = client.get(f"/data/company/{slug}/uspto-patents.csv")
        assert export.status_code == 200, export.text
        assert "12345678" in export.text
        assert "Adaptive freight sensing platform" in export.text
        assert "total_patents=2" in export.text

        profile = client.get(f"/data/company/{slug}")
        assert profile.status_code == 200, profile.text
        assert "intellcluster-uspto-profile-ui" in profile.text
        assert "/uspto-patents.csv" in profile.text

        print("USPTO PatentsView bulk-cache checks OK")
        return 0
    finally:
        _cleanup(entity_id)


if __name__ == "__main__":
    raise SystemExit(run())
