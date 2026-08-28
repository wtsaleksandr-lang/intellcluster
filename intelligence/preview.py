"""Seed a small, isolated database for visual/UI development.

Run this only with INTELLIGENCE_PREVIEW=1. The preview entrypoint forces a
separate SQLite database before importing the normal intelligence application,
so it cannot touch the long-running Replit/PostgreSQL ingestion database.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import delete

from intelligence.database import connect, entities, importer_relationships, source_records


PREVIEW_COMPANIES = [
    {
        "slug": "northstar-industrial-supply",
        "canonical_name": "Northstar Industrial Supply Inc.",
        "name_normalized": "northstar industrial supply",
        "country": "CA",
        "region": "ON",
        "city": "Mississauga",
        "postal_code": "L5T 2J7",
        "address": "Mississauga, Ontario, Canada",
        "website": "https://example.com",
        "corporation_number": "1234567",
        "corporate_status": "Active",
        "incorporated_year": 2012,
        "is_importer": True,
        "buyer_score": 94,
        "summary": "Canadian industrial importer with diversified automotive and machinery sourcing evidence.",
        "enrichment": {},
    },
    {
        "slug": "atlas-mobility-systems",
        "canonical_name": "Atlas Mobility Systems LLC",
        "name_normalized": "atlas mobility systems",
        "country": "US",
        "region": "TX",
        "city": "Houston",
        "postal_code": "77029",
        "address": "Houston, Texas, United States",
        "website": "https://example.com",
        "corporate_status": "Active",
        "is_importer": False,
        "buyer_score": 97,
        "summary": "U.S. transportation equipment company with cached trade, supplier, fleet and federal-contract intelligence.",
        "enrichment": {
            "importyeti": {
                "total_shipments": 2387,
                "most_recent_shipment": "2026-08-21",
                "total_shipping_cost": 6840000,
                "suppliers_table": [
                    {"supplier_name": "Qingdao Precision Components", "total_shipments_company": 418, "country": "China"},
                    {"supplier_name": "Taichung Mobility Works", "total_shipments_company": 227, "country": "Taiwan"},
                    {"supplier_name": "Rhein Industrial GmbH", "total_shipments_company": 94, "country": "Germany"},
                ],
            },
            "usaspending": {
                "contract_awards_shown": 8,
                "contract_award_value_shown": 4820000,
                "awarding_agencies": ["Department of Defense", "Department of Transportation"],
                "uei": "PREVIEWUEI123",
            },
            "fmcsa": {
                "dot_number": "1844221",
                "status": "Active",
                "power_units": 74,
                "drivers": 86,
                "carrier_operation": "Interstate",
            },
        },
    },
]


def seed_preview() -> Path:
    if os.environ.get("INTELLIGENCE_PREVIEW") != "1":
        raise RuntimeError("Refusing to seed preview data unless INTELLIGENCE_PREVIEW=1")

    path = Path(os.environ.get("INTELLIGENCE_DB_PATH", "data/intelligence-preview.db"))
    with connect() as conn:
        conn.execute(delete(importer_relationships))
        conn.execute(delete(source_records))
        conn.execute(delete(entities))

        ids: dict[str, int] = {}
        for company in PREVIEW_COMPANIES:
            result = conn.execute(entities.insert().values(entity_type="company", **company))
            ids[company["slug"]] = int(result.inserted_primary_key[0])

        ca_id = ids["northstar-industrial-supply"]
        for row in [
            ("870899", "8708999900", "Motor vehicle parts and accessories", "China"),
            ("848340", "8483400090", "Gears and transmission components", "Germany"),
            ("851220", "8512200000", "Automotive lighting equipment", "Taiwan"),
            ("870892", "8708920000", "Exhaust system components", "Mexico"),
        ]:
            hs6, hs10, description, origin = row
            conn.execute(
                importer_relationships.insert().values(
                    entity_id=ca_id,
                    activity_year=2023,
                    hs6=hs6,
                    hs10=hs10,
                    product_description=description,
                    origin_country=origin,
                    dataset="preview_canadian_importers",
                )
            )
        conn.execute(
            source_records.insert().values(
                entity_id=ca_id,
                source="corporations_canada",
                source_record_id="preview-ca-registry",
                source_url="https://ised-isde.canada.ca/",
                attributes={"status": "Active", "corporation_number": "1234567"},
            )
        )
        conn.execute(
            source_records.insert().values(
                entity_id=ca_id,
                source="canadian_importers",
                source_record_id="preview-ca-importer",
                source_url="https://ised-isde.canada.ca/",
                attributes={"dataset": "preview"},
            )
        )

        us_id = ids["atlas-mobility-systems"]
        conn.execute(
            source_records.insert().values(
                entity_id=us_id,
                source="fmcsa_company_census",
                source_record_id="1844221",
                source_url="https://data.transportation.gov/",
                attributes={"status": "Active", "dot_number": "1844221", "power_units": 74, "drivers": 86},
            )
        )
    return path


if __name__ == "__main__":
    print(seed_preview())
