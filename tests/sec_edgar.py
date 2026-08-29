from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from intelligence.database import connect, entities, source_records
from intelligence.enrichment.sec_edgar import SECEDGARClient, compact_sec_profile
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_by_slug, upsert_source_record
from main_data import app


client = TestClient(app)
SOURCE = "sec-edgar-regression"


def _cleanup() -> None:
    with connect() as conn:
        entity_ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source == SOURCE)
        ).scalars().all()
        conn.execute(source_records.delete().where(source_records.c.source == SOURCE))
        for entity_id in {int(value) for value in entity_ids}:
            remaining = conn.execute(
                select(source_records.c.id).where(source_records.c.entity_id == entity_id).limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == entity_id))


def _seed(name: str, country: str, source_id: str) -> tuple[int, str]:
    record = SourceRecord(
        source=SOURCE,
        source_record_id=source_id,
        name=name,
        entity_type="company",
        country=country,
        region="DE" if country == "US" else "ON",
        city="Wilmington" if country == "US" else "Toronto",
        attributes={"dataset": SOURCE},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        row = conn.execute(
            select(entities.c.slug).where(entities.c.id == entity_id)
        ).scalar_one()
    return entity_id, str(row)


def run() -> int:
    _cleanup()
    previous_fixture = os.environ.get("SEC_EDGAR_FIXTURE_PATH")
    os.environ["SEC_EDGAR_FIXTURE_PATH"] = str(
        Path(__file__).parent / "fixtures" / "sec_edgar_company.json"
    )
    try:
        sec = SECEDGARClient()
        matches = asyncio.run(sec.search("IntellCluster SEC Test Company Inc."))
        assert len(matches) == 1
        assert matches[0].cik == "0001234567"
        assert matches[0].ticker == "ICST"
        submissions = asyncio.run(sec.submissions(matches[0].cik))
        profile = compact_sec_profile(matches[0], submissions)
        assert profile["latest_filing_form"] == "10-Q"
        assert profile["latest_filing_date"] == "2026-08-15"
        assert profile["recent_filings"][0]["filing_url"].endswith("/icst-20260630.htm")

        us_id, us_slug = _seed(
            "IntellCluster SEC Test Company Inc.",
            "US",
            "SEC-US-1001",
        )
        ca_id, ca_slug = _seed(
            "IntellCluster SEC Test Company Canada Inc.",
            "CA",
            "SEC-CA-1001",
        )
        assert us_id != ca_id

        response = client.post(
            f"/api/intelligence/company/{us_slug}/enrich/sec-edgar"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("paid_sources_called") is False
        assert payload.get("lookup", {}).get("sec_edgar") == "matched"
        assert payload.get("company", {}).get("enrichment", {}).get("sec_edgar", {}).get("cik") == "0001234567"

        cached = client.post(
            f"/api/intelligence/company/{us_slug}/enrich/sec-edgar"
        )
        assert cached.status_code == 200
        assert cached.json().get("lookup", {}).get("sec_edgar") == "cached"

        ca_response = client.post(
            f"/api/intelligence/company/{ca_slug}/enrich/sec-edgar"
        )
        assert ca_response.status_code == 400

        profile_page = client.get(f"/data/company/{us_slug}")
        assert profile_page.status_code == 200
        assert "intellcluster-sec-profile-ui" in profile_page.text
        assert "SEC EDGAR Intelligence" in profile_page.text

        with connect() as conn:
            refreshed = get_entity_by_slug(conn, us_slug)
        assert refreshed is not None
        assert refreshed.get("enrichment", {}).get("sec_edgar", {}).get("ticker") == "ICST"

        print("SEC EDGAR enrichment checks OK")
        return 0
    finally:
        if previous_fixture is None:
            os.environ.pop("SEC_EDGAR_FIXTURE_PATH", None)
        else:
            os.environ["SEC_EDGAR_FIXTURE_PATH"] = previous_fixture
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
