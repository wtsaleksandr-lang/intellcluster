from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from intelligence.database import connect, entities, importer_relationships, source_records
from intelligence.models import SourceRecord
from intelligence.repository import upsert_source_record
from main_data import app


client = TestClient(app)
THIN_SOURCE = "evidence-sitemap-thin"
STRONG_SOURCE_ID = "EVIDENCE-SITEMAP-IMPORTER"


def _cleanup() -> None:
    with connect() as conn:
        ids = conn.execute(
            select(source_records.c.entity_id).where(
                (source_records.c.source == THIN_SOURCE)
                | (
                    (source_records.c.source == "canadian_importers")
                    & (source_records.c.source_record_id == STRONG_SOURCE_ID)
                )
            )
        ).scalars().all()
        for entity_id in {int(value) for value in ids}:
            conn.execute(
                importer_relationships.delete().where(
                    importer_relationships.c.entity_id == entity_id
                )
            )
            conn.execute(
                source_records.delete().where(source_records.c.entity_id == entity_id)
            )
            conn.execute(entities.delete().where(entities.c.id == entity_id))


def _seed() -> tuple[str, str]:
    thin = SourceRecord(
        source=THIN_SOURCE,
        source_record_id="THIN-1",
        name="IntellCluster Registry Only Thin Profile Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Toronto",
        attributes={"dataset": THIN_SOURCE},
    )
    strong = SourceRecord(
        source="canadian_importers",
        source_record_id=STRONG_SOURCE_ID,
        name="IntellCluster Evidence Sitemap Importer Inc.",
        entity_type="company",
        country="CA",
        region="ON",
        city="Hamilton",
        attributes={
            "activity_year": 2023,
            "hs6": "870899",
            "origin_country": "Germany",
            "product_description": "Vehicle parts",
            "dataset": "evidence-sitemap-test",
        },
    )
    with connect() as conn:
        thin_id, _ = upsert_source_record(conn, thin)
        strong_id, _ = upsert_source_record(conn, strong)
        thin_slug = conn.execute(
            select(entities.c.slug).where(entities.c.id == thin_id)
        ).scalar_one()
        strong_slug = conn.execute(
            select(entities.c.slug).where(entities.c.id == strong_id)
        ).scalar_one()
    return str(thin_slug), str(strong_slug)


def run() -> int:
    _cleanup()
    thin_slug, strong_slug = _seed()
    try:
        response = client.get("/sitemaps/companies-1.xml")
        assert response.status_code == 200
        assert f"/data/company/{strong_slug}" in response.text
        assert f"/data/company/{thin_slug}" not in response.text

        index = client.get("/sitemap.xml")
        assert index.status_code == 200
        assert "/sitemaps/companies-1.xml" in index.text
        assert "/sitemaps/suppliers.xml" in index.text
        assert "/sitemaps/markets.xml" in index.text

        markets = client.get("/sitemaps/markets.xml")
        assert markets.status_code == 200
        assert "https://intellcluster.com/data/canada" in markets.text
        assert "https://intellcluster.com/data/usa" in markets.text

        canada = client.get("/data/canada")
        assert canada.status_code == 200
        assert "Canada Company &amp; Importer Intelligence" in canada.text
        assert "CollectionPage" in canada.text
        assert 'content="index,follow,max-image-preview:large,max-snippet:-1"' in canada.text

        usa = client.get("/data/usa")
        assert usa.status_code == 200
        assert "U.S. Company, Carrier &amp; Public Intelligence" in usa.text
        assert "FMCSA" in usa.text

        thin_profile = client.get(f"/data/company/{thin_slug}")
        assert thin_profile.status_code == 200
        assert 'content="noindex,follow"' in thin_profile.text
        assert thin_profile.headers.get("x-robots-tag") == "noindex, follow"

        strong_profile = client.get(f"/data/company/{strong_slug}")
        assert strong_profile.status_code == 200
        assert 'content="index,follow,max-image-preview:large,max-snippet:-1"' in strong_profile.text
        assert strong_profile.headers.get("x-robots-tag") is None

        print("Evidence-tier sitemap and market SEO checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
