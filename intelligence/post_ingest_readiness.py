from __future__ import annotations

import argparse
import json
import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from intelligence.database import connect, entities, source_records, sync_checkpoints
from intelligence.fmcsa_fast_seed import fast_seed_readiness
from intelligence.search_indexing import search_index_status
from intelligence.sync_observability import sync_status_snapshot
from shared.admin import require_admin

router = APIRouter(prefix="/api/intelligence/admin", tags=["intelligence-admin"])

EXPECTED_CANADA = {
    "corporations_canada": 1_562_095,
    "canadian_importers": 485_934,
}


def _source_count(source: str) -> int:
    with connect() as conn:
        return int(
            conn.execute(
                select(func.count()).select_from(source_records).where(source_records.c.source == source)
            ).scalar_one()
            or 0
        )


def _checkpoint_status(source: str) -> tuple[str | None, int]:
    with connect() as conn:
        row = conn.execute(
            select(sync_checkpoints.c.status, sync_checkpoints.c.position).where(
                sync_checkpoints.c.source == source
            )
        ).mappings().first()
    if not row:
        return None, 0
    return str(row["status"] or "") or None, int(row["position"] or 0)


def _is_expected_complete(source: str, stored: int, checkpoint_status: str | None) -> bool:
    expected = EXPECTED_CANADA[source]
    if checkpoint_status == "completed":
        return True
    # Older successful syncs may predate checkpoints. Accept near-total stored
    # source rows as complete while keeping the threshold conservative.
    return stored >= int(expected * 0.995)


def post_ingest_readiness() -> dict[str, Any]:
    """Return a no-network deployment and U.S.-bootstrap readiness report."""

    sync = sync_status_snapshot()
    by_source = {str(row["source"]): row for row in sync["sources"]}
    canada: dict[str, Any] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    for source in ("corporations_canada", "canadian_importers"):
        stored = _source_count(source)
        checkpoint_status, checkpoint_position = _checkpoint_status(source)
        complete = _is_expected_complete(source, stored, checkpoint_status)
        canada[source] = {
            "stored_source_records": stored,
            "expected_total_hint": EXPECTED_CANADA[source],
            "checkpoint_status": checkpoint_status,
            "checkpoint_position": checkpoint_position,
            "complete": complete,
            "progress_percent_hint": round(
                min(100.0, stored * 100.0 / EXPECTED_CANADA[source]), 2
            ),
        }
        current = by_source.get(source) or {}
        if current.get("status") == "running":
            blockers.append(f"{source} ingestion is still running")
        elif not complete:
            blockers.append(f"{source} ingestion is not yet complete")

    with connect() as conn:
        entity_count = int(conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0)
        fmcsa = fast_seed_readiness(conn)

    supplier_index = sync["supplier_index"]
    supplier_backfill = by_source.get("supplier_cache_backfill") or {}
    supplier_backfill_status = supplier_backfill.get("status")
    supplier_backfill_needed = int(supplier_index.get("relationships") or 0) == 0
    if supplier_backfill_needed:
        warnings.append(
            "Supplier index is empty; run the cached-only supplier backfill after Canada ingestion completes."
        )

    search_indexes = search_index_status()
    if search_indexes.get("supported") and not search_indexes.get("all_installed"):
        warnings.append(
            "Optional PostgreSQL trigram search indexes are not fully installed. Build them after planned bulk ingestion is complete, not while Canada/FMFCSA ingestion is running."
        )

    importyeti_live = os.environ.get("IMPORTYETI_ALLOW_LIVE", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if importyeti_live:
        warnings.append(
            "IMPORTYETI_ALLOW_LIVE is enabled. Keep it disabled unless an admin intentionally performs a paid acquisition."
        )

    return {
        "deployment_safe": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "entity_count": entity_count,
        "canada": canada,
        "supplier_index": {
            **supplier_index,
            "backfill_needed": supplier_backfill_needed,
            "backfill_status": supplier_backfill_status,
            "recommended_command": "python -m intelligence.supplier_backfill",
        },
        "fmcsa_fast_seed": fmcsa,
        "search_indexes": search_indexes,
        "recommended_sequence": [
            "Wait until Canada ingestion reports complete and no sync is running.",
            "Pull/deploy the latest main branch.",
            "Run python -m intelligence.post_ingest_readiness --strict.",
            "Run python -m intelligence.data_quality --strict and investigate any blocking integrity findings.",
            "Run python -m intelligence.supplier_backfill to index existing cached suppliers.",
            "Run python -m intelligence.fmcsa_ingest --validate-fast-seed.",
            "If safe, validate with python -m intelligence.fmcsa_ingest --fast-seed --limit 1000.",
            "Review the 1,000-row validation before starting a full FMCSA bootstrap.",
            "After all planned bulk ingestion is finished, run python -m intelligence.search_indexing to inspect search acceleration status.",
            "On PostgreSQL, install missing optional text indexes with python -m intelligence.search_indexing --apply --confirm while no sync is running.",
        ],
        "network_calls": 0,
        "paid_sources_called": False,
    }


@router.get("/post-ingest-readiness")
async def admin_post_ingest_readiness(
    _admin: bool = Depends(require_admin),
) -> dict[str, Any]:
    return post_ingest_readiness()


def main() -> None:
    parser = argparse.ArgumentParser(description="No-network IntellCluster post-ingestion preflight")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with status 2 when deployment blockers remain",
    )
    args = parser.parse_args()
    result = post_ingest_readiness()
    print(json.dumps(result, indent=2, default=str))
    if args.strict and not result["deployment_safe"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
