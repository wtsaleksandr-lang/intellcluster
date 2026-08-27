from __future__ import annotations

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

    print("INTELLIGENCE UNIT OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
