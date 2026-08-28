from __future__ import annotations

import asyncio
import os
from pathlib import Path

from intelligence.country_intelligence import normalize_country, profile_capabilities
from intelligence.enrichment.epa_echo import EPAEchoClient, compact_echo_profile
from intelligence.enrichment.fmcsa import FMCSAClient
from intelligence.enrichment.importyeti import ImportYetiClient, live_importyeti_enabled
from intelligence.enrichment.usaspending import USAspendingClient
from intelligence.entity_resolution import normalize_company_name, score_company_match
from intelligence.models import SourceRecord
from intelligence.registry import list_sources


def run() -> int:
    sources = {row["key"] for row in list_sources()}
    assert "corporations_canada" in sources
    assert "canadian_importers" in sources

    assert normalize_company_name("ABC Automotive Inc.") == "abc automotive"
    assert normalize_company_name("ABC AUTOMOTIVE CORPORATION") == "abc automotive"

    registry = SourceRecord(
        source="corporations_canada",
        source_record_id="123",
        name="ABC Automotive Inc.",
        country="CA",
        region="ON",
        city="Mississauga",
        postal_code="L5T 1A1",
    )
    importer = SourceRecord(
        source="canadian_importers",
        source_record_id="abc|870892",
        name="ABC AUTOMOTIVE LTD",
        country="CA",
        region="ON",
        city="Mississauga",
        postal_code="L5T1A1",
    )
    result = score_company_match(registry, importer)
    assert result.is_likely_match, result
    assert "exact_normalized_name" in result.reasons
    assert "postal_match" in result.reasons

    unrelated = SourceRecord(
        source="canadian_importers",
        source_record_id="other",
        name="Northern Foods Limited",
        country="CA",
        city="Toronto",
    )
    assert not score_company_match(registry, unrelated).is_likely_match

    assert normalize_country("Canada") == "CA"
    assert normalize_country("USA") == "US"
    ca = profile_capabilities(
        {"country": "CA", "is_importer": True, "hs_codes": ["870892"], "origins": ["China"], "relationship_count": 4}
    )
    assert ca["sections"]["trade"]["status"] == "market_context"
    assert ca["sections"]["suppliers"]["status"] == "not_available"
    assert ca["sections"]["relationships"]["status"] == "available"
    us = profile_capabilities({"country": "US", "importyeti": {"total_shipments": 248, "suppliers_table": [{"supplier_name": "A"}]}})
    assert us["sections"]["trade"]["status"] == "cached"
    assert us["sections"]["suppliers"]["status"] == "cached"
    assert us["sections"]["relationships"]["status"] == "cached"
    us_uncached = profile_capabilities({"country": "US"})
    assert us_uncached["sections"]["trade"]["status"] == "unlockable"
    assert us_uncached["sections"]["contracts"]["status"] == "on_demand"
    us_contracts = profile_capabilities({"country": "US", "enrichment": {"usaspending": {"contract_awards_shown": 2}}})
    assert us_contracts["sections"]["contracts"]["status"] == "cached"
    us_fleet = profile_capabilities({"country": "US", "enrichment": {"fmcsa": {"dot_number": "1234567", "power_units": 42}}})
    assert us_fleet["sections"]["fleet"]["status"] == "cached"
    us_epa = profile_capabilities({"country": "US", "enrichment": {"epa_echo": {"facility_count": 2}}})
    assert us_epa["sections"]["facilities"]["status"] == "cached"
    assert us_epa["sections"]["compliance"]["status"] == "cached"
    us_contacts = profile_capabilities({"country": "US", "enrichment": {"web": {"website": "https://example.com"}}})
    assert us_contacts["sections"]["contacts"]["status"] == "cached"

    previous_fixture = os.environ.get("IMPORTYETI_FIXTURE_PATH")
    previous_live = os.environ.pop("IMPORTYETI_ALLOW_LIVE", None)
    try:
        fixture = Path(__file__).parent / "fixtures" / "importyeti_cached_company.json"
        os.environ["IMPORTYETI_FIXTURE_PATH"] = str(fixture)
        assert not live_importyeti_enabled()
        client = ImportYetiClient()
        assert not client.allow_live
        matches = asyncio.run(client.search_company("Anything Inc."))
        assert len(matches) == 1
        assert matches[0].title == "Cached ImportYeti Test Company"
        profile = asyncio.run(client.company_profile(matches[0].slug))
        assert profile["total_shipments"] == 248
        assert profile["_fixture"] is True
    finally:
        if previous_fixture is None:
            os.environ.pop("IMPORTYETI_FIXTURE_PATH", None)
        else:
            os.environ["IMPORTYETI_FIXTURE_PATH"] = previous_fixture
        if previous_live is not None:
            os.environ["IMPORTYETI_ALLOW_LIVE"] = previous_live

    previous_usaspending_fixture = os.environ.get("USASPENDING_FIXTURE_PATH")
    try:
        fixture = Path(__file__).parent / "fixtures" / "usaspending_company.json"
        os.environ["USASPENDING_FIXTURE_PATH"] = str(fixture)
        client = USAspendingClient()
        profile = asyncio.run(client.company_profile("IntellCluster USA Test Company"))
        assert profile is not None
        assert profile["uei"] == "FIXTUREUEI123"
        assert profile["contract_awards_shown"] == 2
        assert profile["contract_award_value_shown"] == 2700000.0
        assert profile["locations"][0]["state"] == "TX"
        assert "Department of Defense" in profile["awarding_agencies"]
    finally:
        if previous_usaspending_fixture is None:
            os.environ.pop("USASPENDING_FIXTURE_PATH", None)
        else:
            os.environ["USASPENDING_FIXTURE_PATH"] = previous_usaspending_fixture

    previous_fmcsa_fixture = os.environ.get("FMCSA_FIXTURE_PATH")
    try:
        fixture = Path(__file__).parent / "fixtures" / "fmcsa_company.json"
        os.environ["FMCSA_FIXTURE_PATH"] = str(fixture)
        client = FMCSAClient()
        companies = asyncio.run(client.search("IntellCluster Logistics"))
        assert len(companies) == 1
        company = companies[0]
        assert company.dot_number == "1234567"
        assert company.country == "US"
        assert company.power_units == 42
        assert company.total_drivers == 48
        source_record = company.to_source_record()
        assert source_record.source == "fmcsa_company_census"
        assert source_record.country == "US"
        assert source_record.region == "TX"
        assert source_record.attributes["usdot_number"] == "1234567"
    finally:
        if previous_fmcsa_fixture is None:
            os.environ.pop("FMCSA_FIXTURE_PATH", None)
        else:
            os.environ["FMCSA_FIXTURE_PATH"] = previous_fmcsa_fixture

    previous_echo_fixture = os.environ.get("EPA_ECHO_FIXTURE_PATH")
    try:
        fixture = Path(__file__).parent / "fixtures" / "epa_echo_company.json"
        os.environ["EPA_ECHO_FIXTURE_PATH"] = str(fixture)
        facilities = asyncio.run(EPAEchoClient().search_facilities("IntellCluster Industries", state="TX"))
        assert len(facilities) == 2
        assert facilities[0].registry_id == "110000000001"
        assert facilities[0].inspections_5y == 7
        assert facilities[0].formal_actions_5y == 1
        profile = compact_echo_profile(facilities)
        assert profile["facility_count"] == 2
        assert profile["major_facility_count"] == 1
        assert profile["inspections_5y"] == 10
        assert profile["formal_actions_5y"] == 1
        assert profile["total_penalties"] == 12500.0
    finally:
        if previous_echo_fixture is None:
            os.environ.pop("EPA_ECHO_FIXTURE_PATH", None)
        else:
            os.environ["EPA_ECHO_FIXTURE_PATH"] = previous_echo_fixture

    print("INTELLIGENCE UNIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
