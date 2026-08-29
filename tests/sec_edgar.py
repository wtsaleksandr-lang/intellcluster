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
        companyfacts = asyncio.run(sec.companyfacts(matches[0].cik))
        profile = compact_sec_profile(matches[0], submissions, companyfacts)
        assert profile["latest_filing_form"] == "10-Q"
        assert profile["latest_filing_date"] == "2026-08-15"
        assert profile["recent_filings"][0]["filing_url"].endswith("/icst-20260630.htm")
        assert profile["financials"]["revenue"]["value"] == 875000000
        assert profile["financials"]["net_income"]["value"] == 62000000
        assert profile["financials"]["assets"]["value"] == 4200000000
        assert profile["financials"]["revenue"]["form"] == "10-Q"

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
        unmatched_id, unmatched_slug = _seed(
            "IntellCluster Unlisted Private Logistics LLC",
            "US",
            "SEC-US-UNMATCHED",
        )
        assert len({us_id, ca_id, unmatched_id}) == 3

        response = client.post(
            f"/api/intelligence/company/{us_slug}/enrich/sec-edgar"
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("paid_sources_called") is False
        assert payload.get("lookup", {}).get("sec_edgar") == "matched"
        sec_payload = payload.get("company", {}).get("enrichment", {}).get("sec_edgar", {})
        assert sec_payload.get("cik") == "0001234567"
        assert sec_payload.get("financials", {}).get("cash", {}).get("value") == 510000000

        cached = client.post(
            f"/api/intelligence/company/{us_slug}/enrich/sec-edgar"
        )
        assert cached.status_code == 200
        assert cached.json().get("lookup", {}).get("sec_edgar") == "cached"

        no_match = client.post(
            f"/api/intelligence/company/{unmatched_slug}/enrich/sec-edgar"
        )
        assert no_match.status_code == 200
        assert no_match.json().get("lookup", {}).get("sec_edgar") == "no_confident_match"
        repeated_no_match = client.post(
            f"/api/intelligence/company/{unmatched_slug}/enrich/sec-edgar"
        )
        assert repeated_no_match.status_code == 200
        repeated_payload = repeated_no_match.json()
        assert repeated_payload.get("lookup", {}).get("sec_edgar") == "no_confident_match"
        assert repeated_payload.get("lookup", {}).get("recently_checked") is True

        ca_response = client.post(
            f"/api/intelligence/company/{ca_slug}/enrich/sec-edgar"
        )
        assert ca_response.status_code == 400

        profile_page = client.get(f"/data/company/{us_slug}")
        assert profile_page.status_code == 200
        assert "intellcluster-sec-profile-ui" in profile_page.text
        assert "SEC EDGAR Intelligence" in profile_page.text
        assert "Latest Revenue" in profile_page.text
        assert "Export SEC CSV" in profile_page.text
        assert "sec_edgar_lookup" in payload.get("company", {}).get("enrichment", {})

        export = client.get(f"/data/company/{us_slug}/sec-edgar.csv")
        assert export.status_code == 200
        assert "text/csv" in export.headers.get("content-type", "")
        assert "sec_summary,cik,0001234567" in export.text
        assert "sec_financial_fact,revenue,875000000" in export.text
        assert "concept=RevenueFromContractWithCustomerExcludingAssessedTax" in export.text
        assert "sec_filing,10-Q,2026-08-15" in export.text
        assert "icst-20260630.htm" in export.text

        unmatched_export = client.get(
            f"/data/company/{unmatched_slug}/sec-edgar.csv"
        )
        assert unmatched_export.status_code == 200
        assert "sec_lookup,status,no_confident_match" in unmatched_export.text

        with connect() as conn:
            refreshed = get_entity_by_slug(conn, us_slug)
            unmatched = get_entity_by_slug(conn, unmatched_slug)
        assert refreshed is not None
        assert refreshed.get("enrichment", {}).get("sec_edgar", {}).get("ticker") == "ICST"
        assert unmatched is not None
        assert unmatched.get("enrichment", {}).get("sec_edgar_lookup", {}).get("status") == "no_confident_match"

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
