from __future__ import annotations

import argparse
import json
import os
from typing import Any

from sqlalchemy import func, select, text

from intelligence.database import connect, get_engine, sync_checkpoints

TRIGRAM_EXTENSION = "pg_trgm"
TRIGRAM_ENABLE_ENV = "INTELLCLUSTER_ENABLE_TRIGRAM_INDEXES"
SEARCH_INDEXES = (
    {
        "name": "ix_intel_entities_canonical_name_trgm",
        "table": "intel_entities",
        "sql": (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_intel_entities_canonical_name_trgm ON intel_entities "
            "USING gin (lower(canonical_name) gin_trgm_ops)"
        ),
        "purpose": "Accelerates case-insensitive company-name substring search across the entity graph.",
    },
    {
        "name": "ix_intel_importer_product_trgm",
        "table": "intel_importer_relationships",
        "sql": (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_intel_importer_product_trgm ON intel_importer_relationships "
            "USING gin (lower(COALESCE(product_description, '')) gin_trgm_ops)"
        ),
        "purpose": "Accelerates product-description text search used by company discovery.",
    },
    {
        "name": "ix_intel_importer_origin_trgm",
        "table": "intel_importer_relationships",
        "sql": (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_intel_importer_origin_trgm ON intel_importer_relationships "
            "USING gin (lower(COALESCE(origin_country, '')) gin_trgm_ops)"
        ),
        "purpose": "Accelerates partial origin-country filters without changing current search semantics.",
    },
    {
        "name": "ix_intel_supplier_name_trgm",
        "table": "intel_supplier_relationships",
        "sql": (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_intel_supplier_name_trgm ON intel_supplier_relationships "
            "USING gin (lower(supplier_name) gin_trgm_ops)"
        ),
        "purpose": "Accelerates supplier-name discovery across cached trade relationships.",
    },
)


def _trigram_enabled() -> bool:
    return os.getenv(TRIGRAM_ENABLE_ENV, "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _running_sync_count() -> int:
    with connect() as conn:
        return int(
            conn.execute(
                select(func.count())
                .select_from(sync_checkpoints)
                .where(func.lower(sync_checkpoints.c.status) == "running")
            ).scalar_one()
            or 0
        )


def search_index_status() -> dict[str, Any]:
    """Inspect optional text-search acceleration without changing the database."""
    running_syncs = _running_sync_count()
    engine = get_engine()
    dialect = str(engine.dialect.name or "").lower()
    enabled = _trigram_enabled()
    postgres = dialect == "postgresql"
    result: dict[str, Any] = {
        "dialect": dialect,
        "enabled": enabled,
        "supported": postgres and enabled,
        "running_sync_checkpoints": running_syncs,
        "safe_to_apply": postgres and enabled and running_syncs == 0,
        "extension": {"name": TRIGRAM_EXTENSION, "installed": False},
        "indexes": [
            {
                "name": row["name"],
                "table": row["table"],
                "purpose": row["purpose"],
                "installed": False,
            }
            for row in SEARCH_INDEXES
        ],
        "network_calls": 0,
        "paid_sources_called": False,
    }
    if not postgres:
        result["reason"] = (
            "Trigram acceleration is PostgreSQL-specific; SQLite/local preview keeps existing indexes."
        )
        return result

    with engine.connect() as conn:
        extension_installed = bool(
            conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = :name)"),
                {"name": TRIGRAM_EXTENSION},
            ).scalar_one()
        )
        existing = {
            str(value)
            for value in conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = ANY (current_schemas(false))"
                )
            ).scalars()
        }
    result["extension"]["installed"] = extension_installed
    for row in result["indexes"]:
        row["installed"] = row["name"] in existing
    result["all_installed"] = extension_installed and all(
        bool(row["installed"]) for row in result["indexes"]
    )

    if not enabled:
        result["reason"] = (
            "Optional pg_trgm acceleration is disabled by default because managed Replit "
            "production schema validation does not reliably provision PostgreSQL extensions. "
            "Current autocomplete uses B-tree prefix indexes and does not require pg_trgm."
        )
    elif running_syncs:
        result["reason"] = (
            "A resumable intelligence sync is still marked running. Wait for ingestion/processing to finish before building large text indexes."
        )
    elif not result["all_installed"]:
        result["reason"] = (
            "Optional PostgreSQL trigram indexes are not fully installed. Enable and apply them only in an environment that explicitly supports pg_trgm."
        )
    else:
        result["reason"] = "Optional PostgreSQL text-search acceleration is installed."
    return result


def apply_search_indexes(*, confirm: bool = False) -> dict[str, Any]:
    """Install optional PostgreSQL trigram indexes only when explicitly enabled."""
    if not confirm:
        raise RuntimeError("Search-index creation requires explicit confirmation.")

    before = search_index_status()
    if not before.get("enabled"):
        return {**before, "applied": False, "disabled": True}
    if not before["supported"]:
        return {**before, "applied": False}
    if before["running_sync_checkpoints"]:
        raise RuntimeError(
            "Refusing to build search indexes while an intelligence sync is running."
        )
    if before.get("all_installed"):
        return {**before, "applied": False, "already_complete": True}

    engine = get_engine()
    created: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {TRIGRAM_EXTENSION}"))
        for definition in SEARCH_INDEXES:
            conn.execute(text(str(definition["sql"])))
            created.append(str(definition["name"]))

    after = search_index_status()
    return {
        **after,
        "applied": True,
        "indexes_requested": created,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or install optional PostgreSQL search acceleration"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Install pg_trgm and the optional GIN search indexes when explicitly enabled.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required together with --apply because index builds consume database CPU/I/O.",
    )
    args = parser.parse_args()
    if args.apply:
        result = apply_search_indexes(confirm=args.confirm)
    else:
        result = search_index_status()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
