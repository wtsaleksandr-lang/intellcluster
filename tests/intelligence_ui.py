from __future__ import annotations

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, importer_relationships, source_records, supplier_relationships
from intelligence.models import SourceRecord
from intelligence.repository import (
    get_entity_by_slug,
    search_entities,
    set_entity_enrichment,
    upsert_source_record,
)
from intelligence.supplier_explorer import sync_supplier_relationships
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
    cached_profile = {
        "title": "IntellCluster UI Test Importer Inc.",
        "total_shipments": 96,
        "_cachedAt": "2026-08-27T00:00:00+00:00",
        "suppliers_table": [
            {
                "supplier_name": "Cached Supplier One",
                "country": "China",
                "total_shipments_company": 42,
                "product_descriptions": ["automotive parts"],
            }
        ],
        "recent_bols": [
            {
                "date_formatted": "01/03/2026",
                "Bill_of_Lading": "UITESTBOL0001",
                "Shipper_Name": "Cached Supplier One",
                "supplier_address_country": "China",
                "Product_Description": "automotive parts",
                "HS_Code": "870892",
                "Weight_in_KG": 18000,
                "Quantity": 1200,
                "Quantity_Unit": "PCS",
            }
        ],
    }
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, corporation)
        importer_id, _ = upsert_source_record(conn, importer)
        assert entity_id == importer_id
        set_entity_enrichment(conn, entity_id, "importyeti", cached_profile)
        assert sync_supplier_relationships(conn, entity_id, cached_profile) == 1
        rows = search_entities(conn, q="IntellCluster UI Test Importer")
        assert rows
        slug = rows[0]["slug"]
        assert get_entity_by_slug(conn, slug)
        return entity_id, slug


def _cleanup(entity_id: int) -> None:
    with connect() as conn:
        conn.execute(supplier_relationships.delete().where(supplier_relationships.c.importer_entity_id == entity_id))
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
            ("/data/suppliers", 200),
            ("/data/suppliers?q=Cached&country=China&sort=importers", 200),
            ("/data/supplier/Cached%20Supplier%20One", 200),
            (f"/data/company/{slug}", 200),
            (f"/data/company/{slug}/export.csv", 200),
            ("/api/intelligence/health", 200),
            ("/api/intelligence/freshness", 200),
            ("/api/intelligence/sources", 200),
        ]
        failed = []
        for path, expected in checks:
            response = client.get(path, follow_redirects=False)
            if response.status_code != expected:
                failed.append(f"{path}: {response.status_code} != {expected}")
        hs_response = client.get("/data/hs/870892")
        hs_text = hs_response.text
        if "Cached Supplier One" not in hs_text or "Cached Suppliers Linked to HS 870892" not in hs_text:
            failed.append("/data/hs/870892: cached supplier ranking missing")
        if "/data/supplier/Cached%20Supplier%20One" not in hs_text:
            failed.append("/data/hs/870892: supplier drilldown link missing")
        if "expectedKind=()=>box.dataset.view==='companies'?'company':'supplier'" not in hs_text:
            failed.append("/data/hs/870892: company-tab regression fix missing")
        company_response = client.get(f"/data/company/{slug}")
        company_text = company_response.text
        if "relationship-evidence-enhancer" not in company_text or "Top 10 relationships" not in company_text:
            failed.append(f"/data/company/{slug}: relationship evidence drilldown enhancer missing")
        freshness = client.get("/api/intelligence/freshness").json()
        if freshness.get("company_count", 0) < 1 or "delta_available" not in freshness:
            failed.append("/api/intelligence/freshness: invalid payload")
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
