from __future__ import annotations

from sqlalchemy import insert, select, update

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    source_records,
    supplier_relationships,
)
from intelligence.materialize import materialize_rows
from intelligence.models import SourceRecord
from intelligence.repository import search_entities, upsert_source_record

SOURCE_A = "materialization-test-a"
SOURCE_B = "materialization-test-b"


def _cleanup() -> None:
    with connect() as conn:
        ids = conn.execute(
            select(source_records.c.entity_id).where(source_records.c.source.in_([SOURCE_A, SOURCE_B]))
        ).scalars().all()
        unique_ids = {int(entity_id) for entity_id in ids}
        if unique_ids:
            conn.execute(
                supplier_relationships.delete().where(
                    supplier_relationships.c.importer_entity_id.in_(unique_ids)
                )
            )
            conn.execute(
                importer_relationships.delete().where(
                    importer_relationships.c.entity_id.in_(unique_ids)
                )
            )
        conn.execute(source_records.delete().where(source_records.c.source.in_([SOURCE_A, SOURCE_B])))
        for entity_id in unique_ids:
            remaining = conn.execute(
                select(source_records.c.id).where(source_records.c.entity_id == entity_id).limit(1)
            ).scalar_one_or_none()
            if remaining is None:
                conn.execute(entities.delete().where(entities.c.id == entity_id))


def run() -> int:
    _cleanup()
    try:
        base = SourceRecord(
            source=SOURCE_A,
            source_record_id="MAT-1",
            name="Materialization Example Industries Inc",
            country="US",
            region="CA",
            city="Oakland",
            postal_code="94607",
            website="https://materialization-example.test",
            attributes={"dataset": "test"},
        )
        corroborating = SourceRecord(
            source=SOURCE_B,
            source_record_id="MAT-2",
            name="Materialization Example Industries",
            country="US",
            region="CA",
            city="Oakland",
            postal_code="94607",
            attributes={"dataset": "test-secondary"},
        )
        with connect() as conn:
            entity_id, created = upsert_source_record(conn, base)
            assert created is True
            matched_id, created_again = upsert_source_record(conn, corroborating)
            assert created_again is False
            assert matched_id == entity_id
            conn.execute(
                update(entities)
                .where(entities.c.id == entity_id)
                .values(is_importer=True, corporation_number="MAT-CORP-1", enrichment={"usaspending": {"awards_shown": 3}})
            )
            conn.execute(
                insert(importer_relationships).values(
                    entity_id=entity_id,
                    activity_year=2026,
                    hs6="841391",
                    hs10="8413910000",
                    product_description="Industrial pump parts",
                    origin_country="China",
                    dataset="materialization-test",
                )
            )
            conn.execute(
                insert(supplier_relationships).values(
                    importer_entity_id=entity_id,
                    supplier_name="Example Pump Components Ltd",
                    supplier_normalized="example pump components",
                    supplier_country="CN",
                    supplier_address="Shanghai, China",
                    total_shipments=18,
                    product_descriptions=["Industrial pump parts"],
                    recent_bols=[],
                    source="materialization-test",
                )
            )

        with connect() as conn:
            row = conn.execute(select(entities).where(entities.c.id == entity_id)).mappings().one()
            written = materialize_rows(conn, [dict(row)])
            assert written == 1

        with connect() as conn:
            for query in (
                "Materialization Example",
                "Industrial pump parts",
                "8413910000",
                "Example Pump Components",
                "MAT-CORP-1",
            ):
                matches = search_entities(conn, q=query, limit=10)
                assert any(int(match["id"]) == entity_id for match in matches), query
            entity = conn.execute(select(entities).where(entities.c.id == entity_id)).mappings().one()

        enrichment = entity["enrichment"]
        assert isinstance(enrichment, dict)
        intelligence = enrichment.get("intelligence")
        assert isinstance(intelligence, dict)
        assert intelligence["source_count"] == 2
        assert intelligence["source_record_count"] == 2
        assert intelligence["importer_relationship_count"] == 1
        assert intelligence["hs_code_count"] == 1
        assert intelligence["origin_country_count"] == 1
        assert intelligence["supplier_count"] == 1
        assert intelligence["supplier_shipments"] == 18
        assert intelligence["top_hs_codes"][0]["code"] == "8413910000"
        assert intelligence["top_origins"][0]["country"] == "China"
        assert intelligence["top_suppliers"][0]["name"] == "Example Pump Components Ltd"
        assert intelligence["network_calls"] == 0
        assert intelligence["paid_sources_called"] is False
        assert int(entity["buyer_score"] or 0) > 0
        assert "observed import" in str(entity["summary"]).casefold()
        assert "evidence from 2 source datasets" in str(entity["summary"]).casefold()

        print("Intelligence materialization and unified search checks OK")
        return 0
    finally:
        _cleanup()


if __name__ == "__main__":
    raise SystemExit(run())
