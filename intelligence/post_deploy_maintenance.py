from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, insert, select, text, update

from intelligence.database import connect, entities, get_engine, sync_checkpoints
from intelligence.materialize import SOURCE_KEY as MATERIALIZE_SOURCE, materialization_status, run_intelligence_materialization
from intelligence.search_indexing import apply_search_indexes, search_index_status
from intelligence.supplier_backfill import SOURCE_KEY as SUPPLIER_SOURCE, run_supplier_backfill
from shared.admin import require_admin

router = APIRouter(prefix="/api/intelligence/admin", tags=["intelligence-admin"])

SOURCE_KEY = "post_deploy_maintenance"
LOCK_KEY = 731_908_421_117
REQUIRED_BASE_SOURCES = ("corporations_canada", "canadian_importers")


def _is_replit_production() -> bool:
    return os.getenv("REPLIT_DEPLOYMENT", "").strip() == "1"


def _checkpoint(source: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            select(
                sync_checkpoints.c.position,
                sync_checkpoints.c.status,
                sync_checkpoints.c.message,
                sync_checkpoints.c.updated_at,
            ).where(sync_checkpoints.c.source == source)
        ).mappings().first()
    return dict(row) if row else None


def _save_status(status: str, message: str, *, position: int = 0) -> None:
    with connect() as conn:
        existing = conn.execute(
            select(sync_checkpoints.c.source).where(sync_checkpoints.c.source == SOURCE_KEY)
        ).scalar_one_or_none()
        values = {
            "position": max(0, int(position)),
            "status": status,
            "message": message[:1500],
            "updated_at": func.now(),
        }
        if existing is None:
            conn.execute(insert(sync_checkpoints).values(source=SOURCE_KEY, **values))
        else:
            conn.execute(
                update(sync_checkpoints)
                .where(sync_checkpoints.c.source == SOURCE_KEY)
                .values(**values)
            )


def _base_ingestion_ready() -> tuple[bool, str]:
    with connect() as conn:
        entity_count = int(conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0)
        rows = conn.execute(
            select(sync_checkpoints.c.source, sync_checkpoints.c.status).where(
                sync_checkpoints.c.source.in_(REQUIRED_BASE_SOURCES)
            )
        ).mappings().all()
    if entity_count <= 0:
        return False, "canonical entity table is empty"
    statuses = {str(row["source"]): str(row["status"] or "") for row in rows}
    incomplete = [source for source in REQUIRED_BASE_SOURCES if statuses.get(source) != "completed"]
    if incomplete:
        return False, "base ingestion not completed: " + ", ".join(incomplete)
    return True, f"{entity_count:,} canonical entities available"


def _has_cached_importyeti_profiles() -> bool:
    engine = get_engine()
    if str(engine.dialect.name).lower() != "postgresql":
        return False
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM intel_entities "
                    "WHERE enrichment ? 'importyeti' LIMIT 1"
                    ")"
                )
            ).scalar_one()
        )


def maintenance_status() -> dict[str, Any]:
    ready, reason = _base_ingestion_ready()
    own = _checkpoint(SOURCE_KEY)
    supplier = _checkpoint(SUPPLIER_SOURCE)
    materialized = materialization_status()
    indexes = search_index_status()
    return {
        "production_runtime": _is_replit_production(),
        "base_ingestion_ready": ready,
        "base_ingestion_reason": reason,
        "status": str(own.get("status") or "not_started") if own else "not_started",
        "message": str(own.get("message") or "") if own else "",
        "updated_at": own.get("updated_at") if own else None,
        "supplier_backfill": {
            "status": str(supplier.get("status") or "not_started") if supplier else "not_started",
            "position": int(supplier.get("position") or 0) if supplier else 0,
        },
        "materialization": materialized,
        "search_indexes": indexes,
        "network_calls": 0,
        "paid_sources_called": False,
    }


def run_post_deploy_maintenance() -> dict[str, Any]:
    ready, reason = _base_ingestion_ready()
    if not ready:
        _save_status("waiting", reason)
        return {"status": "waiting", "reason": reason}

    engine = get_engine()
    if str(engine.dialect.name).lower() != "postgresql":
        _save_status("skipped", "post-deploy automation requires PostgreSQL")
        return {"status": "skipped", "reason": "postgresql_required"}

    lock_conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    acquired = bool(
        lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar_one()
    )
    if not acquired:
        lock_conn.close()
        return {"status": "already_running"}

    try:
        _save_status("running", "Post-deploy maintenance started")

        # Existing cached ImportYeti profiles need supplier rows before company
        # intelligence is materialized. If there are no cached profiles yet,
        # avoid a pointless 1.6M-row scan; future ImportYeti acquisition writes
        # supplier relationships directly and can run the backfill explicitly.
        if _has_cached_importyeti_profiles():
            supplier = _checkpoint(SUPPLIER_SOURCE)
            if not supplier or str(supplier.get("status") or "") != "completed":
                run_supplier_backfill(resume=True, batch_size=5000)

        materialized = materialization_status()
        if not materialized.get("complete"):
            run_intelligence_materialization(resume=True, batch_size=5000)

        index_status = search_index_status()
        if index_status.get("supported") and not index_status.get("all_installed"):
            apply_search_indexes(confirm=True)

        final = maintenance_status()
        _save_status(
            "completed",
            "Post-deploy maintenance completed: materialization and search acceleration are ready",
            position=int(final.get("materialization", {}).get("position") or 0),
        )
        return {"status": "completed", "finished_at": datetime.now(UTC).isoformat()}
    except Exception as exc:  # noqa: BLE001 - failure must never crash the web app
        _save_status("failed", f"Post-deploy maintenance failed: {str(exc)[:1200]}")
        print(f"[post-deploy-maintenance] failed: {exc}", flush=True)
        return {"status": "failed", "error": str(exc)[:500]}
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
        finally:
            lock_conn.close()


def install_post_deploy_maintenance(app) -> None:
    if getattr(app.state, "post_deploy_maintenance_installed", False):
        return
    app.state.post_deploy_maintenance_installed = True

    @app.on_event("startup")
    async def _start_post_deploy_maintenance() -> None:
        if not _is_replit_production():
            return
        thread = threading.Thread(
            target=run_post_deploy_maintenance,
            name="intellcluster-post-deploy-maintenance",
            daemon=True,
        )
        thread.start()


@router.get("/post-deploy-maintenance")
async def admin_post_deploy_maintenance(
    _admin: bool = Depends(require_admin),
) -> dict[str, Any]:
    return maintenance_status()
