from __future__ import annotations

import asyncio
import os
from pathlib import Path

from intelligence.enrichment.importyeti import ImportYetiClient, live_importyeti_enabled
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

    # ImportYeti development/tests are cached-only. Reuse one fixture and prove
    # no live opt-in is present before exercising profile/search helpers.
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

    print("INTELLIGENCE UNIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
