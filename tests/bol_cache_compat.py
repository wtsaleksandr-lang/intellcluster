from __future__ import annotations

import os

from fastapi.testclient import TestClient

from intelligence.database import connect, entities, source_records
from intelligence.models import SourceRecord
from intelligence.repository import get_entity_enrichment, set_entity_enrichment, upsert_source_record
from main_data import app

client = TestClient(app)


def _seed() -> tuple[int, str]:
    record = SourceRecord(
        source="bol-cache-compat-test",
        source_record_id="BOL-COMPAT-1",
        name="Cached BOL Compatibility LLC",
        entity_type="company",
        country="US",
        region="TX",
        city="Houston",
        postal_code="77001",
        attributes={"dataset": "bol-cache-compat-test"},
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
                "title": "Cached BOL Compatibility LLC",
                "_cachedAt": "2026-08-29T12:00:00Z",
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
    os.environ["IMPORTYETI_ALLOW_LIVE"] = "true"
    os.environ["IMPORTYETI_API_KEY"] = "must-not-be-used-by-bol-page"
    try:
        with connect() as conn:
            before = get_entity_enrichment(conn, entity_id)
        assert "importyeti_bol:CACHEBOL1234" not in before

        response = client.get(f"/data/company/{slug}/bol/CACHEBOL1234")
        assert response.status_code == 200, response.text
        assert "CACHEBOL1234" in response.text
        assert "Cached Supplier Co" in response.text
        assert "Machine components" in response.text
        assert "12,500 kg" in response.text

        with connect() as conn:
            after = get_entity_enrichment(conn, entity_id)
        promoted = after.get("importyeti_bol:CACHEBOL1234")
        assert isinstance(promoted, dict), after
        assert promoted.get("supplier_name") == "Cached Supplier Co", promoted
        assert promoted.get("weight") == 12500, promoted
        assert promoted.get("_cache_source") == "stored_importyeti_evidence", promoted

        missing = client.get(f"/data/company/{slug}/bol/NOTCACHED9999")
        assert missing.status_code == 200, missing.text
        assert "This bill of lading is not cached" in missing.text
        with connect() as conn:
            final = get_entity_enrichment(conn, entity_id)
        assert "importyeti_bol:NOTCACHED9999" not in final

        print("Cached BOL compatibility checks OK")
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
        _cleanup(entity_id)


if __name__ == "__main__":
    raise SystemExit(run())
