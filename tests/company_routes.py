from __future__ import annotations

import os

from fastapi.testclient import TestClient

from intelligence.company_routes import _cached_bol
from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import (
    get_entity_by_slug,
    get_entity_enrichment,
    set_entity_enrichment,
    upsert_source_record,
)
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


def _load_cached(entity_id: int, slug: str):
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
        assert company is not None
        enrichment = get_entity_enrichment(conn, entity_id)
    return company, enrichment, _cached_bol(company, enrichment, "CACHEBOL1234")


def run() -> int:
    entity_id, slug = _seed()
    old_live = os.environ.get("IMPORTYETI_ALLOW_LIVE")
    old_key = os.environ.get("IMPORTYETI_API_KEY")
    old_demo = os.environ.get("INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE")
    os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
    os.environ["IMPORTYETI_API_KEY"] = "should-never-be-used-by-page-routes"
    os.environ["INTELLIGENCE_ALLOW_LEGACY_DEMO_PROFILE"] = "1"
    try:
        company, enrichment, cached = _load_cached(entity_id, slug)
        assert cached is not None, {"company_importyeti": company.get("importyeti"), "enrichment": enrichment}
        assert cached.get("supplier_name") == "Cached Supplier Co", cached

        profile = client.get(f"/data/company/{slug}")
        assert profile.status_code == 200, profile.text
        assert "Cached Route Logistics LLC" in profile.text

        # A normal profile view must not consume or erase the BOL cache.
        company_after, enrichment_after, cached_after = _load_cached(entity_id, slug)
        assert cached_after is not None, {
            "company_importyeti": company_after.get("importyeti"),
            "enrichment": enrichment_after,
        }
        assert cached_after.get("supplier_name") == "Cached Supplier Co", cached_after

        bol = client.get(f"/data/company/{slug}/bol/CACHEBOL1234")
        assert bol.status_code == 200, bol.text
        assert "CACHEBOL1234" in bol.text, bol.text[:1500]
        assert "Cached Supplier Co" in bol.text, bol.text[:3000]
        assert "Machine components" in bol.text, bol.text[:3000]
        assert "12,500 kg" in bol.text, bol.text[:3000]

        missing_bol = client.get(f"/data/company/{slug}/bol/NOTCACHED9999")
        assert missing_bol.status_code == 200, missing_bol.text
        assert "never triggers a paid data request" in missing_bol.text, missing_bol.text[:3000]

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
