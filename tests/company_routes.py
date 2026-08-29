from __future__ import annotations

import os

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import set_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)


def _seed() -> tuple[int, str]:
    record = SourceRecord(
        source="company-route-test",
        source_record_id="COMPANY-ROUTE-1",
        name="Cached Route Logistics LLC",
        entity_type="company",
        country="US",
        region="TX",
        city="Houston",
        postal_code="77001",
        attributes={"dataset": "company-route-test"},
    )
    with connect() as conn:
        entity_id, _ = upsert_source_record(conn, record)
        slug = str(
            conn.execute(entities.select().where(entities.c.id == entity_id))
            .mappings()
            .one()["slug"]
        )
        set_entity_enrichment(
            conn,
            entity_id,
            "importyeti",
            {
                "title": "Cached Route Logistics LLC",
                "_cachedAt": "2026-08-29T12:00:00Z",
                "total_shipments": 9,
                "recent_bols": [
                    {
                        "Bill_of_Lading": "CACHEBOL1234",
                        "date_formatted": "08/21/2026",
                        "Shipper_Name": "Cached Supplier Co",
                        "supplier_address_country": "China",
                        "Product_Description": "Machine components",
                        "HS_Code": "848390",
                        "Weight_in_KG": 12500,
                        "Quantity": 22,
                        "Quantity_Unit": "PCS",
                    }
                ],
            },
        )
    return int(entity_id), slug


def _cleanup(entity_id: int) -> None:
    with connect() as conn:
        conn.execute(source_records.delete().where(source_records.c.entity_id == entity_id))
        conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    entity_id, slug = _seed()
    old_live = os.environ.get("IMPORTYETI_ALLOW_LIVE")
    old_key = os.environ.get("IMPORTYETI_API_KEY")
    old_demo = os.environ.get("INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE")
    os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
    os.environ["IMPORTYETI_API_KEY"] = "should-never-be-used-by-page-routes"
    os.environ["INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE"] = "1"
    try:
        profile = client.get(f"/data/company/{slug}")
        assert profile.status_code == 200, profile.text
        assert "Cached Route Logistics LLC" in profile.text

        bol = client.get(f"/data/company/{slug}/bol/CACHEBOL1234")
        assert bol.status_code == 200, bol.text
        assert "CACHEBOL1234" in bol.text
        assert "Cached Supplier Co" in bol.text
        assert "Machine components" in bol.text
        assert "12,500 kg" in bol.text

        missing_bol = client.get(f"/data/company/{slug}/bol/NOTCACHED9999")
        assert missing_bol.status_code == 200, missing_bol.text
        assert "never triggers a paid data request" in missing_bol.text

        demo = client.get("/data/company/maple-auto-supply-inc")
        assert demo.status_code == 200, demo.text
        assert "Maple Auto Supply Inc." in demo.text

        missing_company = client.get("/data/company/company-route-definitely-missing")
        assert missing_company.status_code == 404, missing_company.text
        assert "Company profile not found" in missing_company.text

        print("Cached-only company route checks OK")
        return 0
    finally:
        if old_live is None:
            os.environ.pop("IMPORTYETI_ALLOW_LIVE", None)
        else:
            os.environ["IMPORTYETI_ALLOW_LIVE"] = old_live
        if old_key is None:
            os.environ.pop("IMPORTYETI_API_KEY", None)
        else:
            os.environ["IMPORTYETI_API_KEY"] = old_key
        if old_demo is None:
            os.environ.pop("INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE", None)
        else:
            os.environ["INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE"] = old_demo
        _cleanup(entity_id)


if __name__ == "__main__":
    raise SystemExit(run())
