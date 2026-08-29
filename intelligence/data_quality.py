from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import and_, func, select

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    source_records,
    supplier_relationships,
)


def _count(conn, stmt) -> int:
    return int(conn.execute(stmt).scalar_one() or 0)


def data_quality_report() -> dict[str, Any]:
    """Run database-only integrity checks across the canonical intelligence graph."""
    with connect() as conn:
        counts = {
            "entities": _count(conn, select(func.count()).select_from(entities)),
            "source_records": _count(conn, select(func.count()).select_from(source_records)),
            "importer_relationships": _count(
                conn, select(func.count()).select_from(importer_relationships)
            ),
            "supplier_relationships": _count(
                conn, select(func.count()).select_from(supplier_relationships)
            ),
        }

        orphan_sources = _count(
            conn,
            select(func.count())
            .select_from(
                source_records.outerjoin(entities, source_records.c.entity_id == entities.c.id)
            )
            .where(entities.c.id.is_(None)),
        )
        orphan_importers = _count(
            conn,
            select(func.count())
            .select_from(
                importer_relationships.outerjoin(
                    entities, importer_relationships.c.entity_id == entities.c.id
                )
            )
            .where(entities.c.id.is_(None)),
        )
        orphan_suppliers = _count(
            conn,
            select(func.count())
            .select_from(
                supplier_relationships.outerjoin(
                    entities,
                    supplier_relationships.c.importer_entity_id == entities.c.id,
                )
            )
            .where(entities.c.id.is_(None)),
        )

        duplicate_source_groups = source_records.alias("duplicate_source_groups")
        duplicate_source_subquery = (
            select(
                duplicate_source_groups.c.source,
                duplicate_source_groups.c.source_record_id,
            )
            .group_by(
                duplicate_source_groups.c.source,
                duplicate_source_groups.c.source_record_id,
            )
            .having(func.count() > 1)
            .subquery()
        )
        duplicate_source_ids = _count(
            conn, select(func.count()).select_from(duplicate_source_subquery)
        )

        duplicate_corp_subquery = (
            select(entities.c.corporation_number)
            .where(
                entities.c.corporation_number.is_not(None),
                entities.c.corporation_number != "",
            )
            .group_by(entities.c.corporation_number)
            .having(func.count() > 1)
            .subquery()
        )
        duplicate_corporation_numbers = _count(
            conn, select(func.count()).select_from(duplicate_corp_subquery)
        )

        entities_without_source = _count(
            conn,
            select(func.count())
            .select_from(
                entities.outerjoin(source_records, entities.c.id == source_records.c.entity_id)
            )
            .where(source_records.c.id.is_(None)),
        )

        corporations_wrong_country = _count(
            conn,
            select(func.count(func.distinct(source_records.c.entity_id)))
            .select_from(source_records.join(entities, source_records.c.entity_id == entities.c.id))
            .where(
                source_records.c.source == "corporations_canada",
                func.upper(func.coalesce(entities.c.country, "")) != "CA",
            ),
        )
        importers_not_flagged = _count(
            conn,
            select(func.count(func.distinct(source_records.c.entity_id)))
            .select_from(source_records.join(entities, source_records.c.entity_id == entities.c.id))
            .where(
                source_records.c.source == "canadian_importers",
                entities.c.is_importer.is_(False),
            ),
        )
        importer_relationships_on_non_importers = _count(
            conn,
            select(func.count(func.distinct(importer_relationships.c.entity_id)))
            .select_from(
                importer_relationships.join(
                    entities, importer_relationships.c.entity_id == entities.c.id
                )
            )
            .where(entities.c.is_importer.is_(False)),
        )

        invalid_country_codes = _count(
            conn,
            select(func.count())
            .select_from(entities)
            .where(
                entities.c.country.is_not(None),
                ~func.upper(entities.c.country).in_(["CA", "US"]),
            ),
        )

        active_sync_conflict = _count(
            conn,
            select(func.count())
            .select_from(source_records)
            .where(and_(source_records.c.entity_id <= 0, source_records.c.id > 0)),
        )

    checks = {
        "orphan_source_records": orphan_sources,
        "orphan_importer_relationships": orphan_importers,
        "orphan_supplier_relationships": orphan_suppliers,
        "duplicate_source_identity_groups": duplicate_source_ids,
        "duplicate_corporation_numbers": duplicate_corporation_numbers,
        "entities_without_source_records": entities_without_source,
        "corporations_canada_entities_wrong_country": corporations_wrong_country,
        "canadian_importer_entities_not_flagged": importers_not_flagged,
        "importer_relationships_on_non_importers": importer_relationships_on_non_importers,
        "unexpected_country_codes": invalid_country_codes,
        # Always expected to be zero; kept as a cheap structural sanity check so
        # the report format can flag impossible invalid FK-like IDs consistently.
        "invalid_nonpositive_source_entity_ids": active_sync_conflict,
    }

    blocking_keys = {
        "orphan_source_records",
        "orphan_importer_relationships",
        "orphan_supplier_relationships",
        "duplicate_source_identity_groups",
        "corporations_canada_entities_wrong_country",
        "canadian_importer_entities_not_flagged",
        "importer_relationships_on_non_importers",
        "invalid_nonpositive_source_entity_ids",
    }
    blockers = [key for key in blocking_keys if checks.get(key, 0) > 0]
    warnings = [
        key
        for key in ("duplicate_corporation_numbers", "entities_without_source_records", "unexpected_country_codes")
        if checks.get(key, 0) > 0
    ]
    return {
        "healthy": not blockers,
        "counts": counts,
        "checks": checks,
        "blockers": sorted(blockers),
        "warnings": warnings,
        "network_calls": 0,
        "paid_sources_called": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="No-network IntellCluster data-quality audit")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 2 when blocking integrity problems are found",
    )
    args = parser.parse_args()
    report = data_quality_report()
    print(json.dumps(report, indent=2, default=str))
    if args.strict and not report["healthy"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
