from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import func, select, text

from intelligence.database import get_engine, sync_checkpoints

TRIGRAM_EXTENSION = "pg_trgm"
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
)


def _running_sync_count() -> int:
    engine = get_engine()
    with engine.connect() as conn:
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
    engine = get_engine()
    dialect = str(engine.dialect.name or "").lower()
    running_syncs = _running_sync_count()
    result: dict[str, Any] = {
        "dialect": dialect,
        "supported": dialect == "postgresql",
        "running_sync_checkpoints": running_syncs,
        "safe_to_apply": dialect == "postgresql" and running_syncs == 0,
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
    if dialect != "postgresql":
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
    if running_syncs:
        result["reason"] = (
            "A resumable intelligence sync is still marked running. Wait for ingestion to finish before building large text indexes."
        )
    elif not result["all_installed"]:
        result["reason"] = (
            "Optional PostgreSQL trigram indexes are not fully installed. Apply them after bulk ingestion to improve million-row search latency."
        )
    else:
        result["reason"] = "Optional PostgreSQL text-search acceleration is installed."
    return result


def apply_search_indexes(*, confirm: bool = False) -> dict[str, Any]:
    """Install optional PostgreSQL trigram indexes after bulk ingestion.

    This is deliberately never called at application startup. ``CREATE INDEX
    CONCURRENTLY`` keeps PostgreSQL writable while indexes build, but creating a
    million-row GIN index still consumes CPU/I/O, so the command refuses to run
    while any intelligence checkpoint is marked ``running``.
    """
    if not confirm:
        raise RuntimeError("Search-index creation requires explicit confirmation.")

    before = search_index_status()
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
    # CREATE EXTENSION / CREATE INDEX CONCURRENTLY cannot be wrapped in the
    # ordinary transaction used by ``connect()``, so use an explicit autocommit
    # connection for this operator-only maintenance action.
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
        help="Install pg_trgm and the optional GIN search indexes.",
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
