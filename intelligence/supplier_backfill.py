from __future__ import annotations

import argparse
import time
from typing import Any

from sqlalchemy import func, insert, select, update

from intelligence.database import connect, entities, sync_checkpoints, sync_runs
from intelligence.supplier_explorer import sync_supplier_relationships

SOURCE_KEY = "supplier_cache_backfill"


def _fmt_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _load_checkpoint() -> int:
    with connect() as conn:
        value = conn.execute(
            select(sync_checkpoints.c.position).where(sync_checkpoints.c.source == SOURCE_KEY)
        ).scalar_one_or_none()
    return int(value or 0)


def _save_checkpoint(position: int, status: str, message: str | None = None) -> None:
    with connect() as conn:
        existing = conn.execute(
            select(sync_checkpoints.c.source).where(sync_checkpoints.c.source == SOURCE_KEY)
        ).scalar_one_or_none()
        values = {
            "position": max(0, int(position)),
            "status": status,
            "message": message,
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


def run_supplier_backfill(
    *,
    resume: bool = True,
    batch_size: int = 1000,
    limit_entities: int | None = None,
) -> dict[str, int | str]:
    """Index named suppliers from already-cached ImportYeti company profiles.

    This job performs database-only work. It never creates an ImportYeti client,
    never makes a network request and therefore cannot consume paid API credits.
    The checkpoint is the last canonical entity ID scanned, making the job safe to
    stop and resume across a million-plus entity graph.
    """

    batch_size = max(50, min(int(batch_size), 5000))
    started = time.monotonic()
    last_id = _load_checkpoint() if resume else 0
    start_id = last_id
    scanned = 0
    cached_profiles = 0
    relationships_written = 0

    with connect() as conn:
        result = conn.execute(
            insert(sync_runs).values(
                source=SOURCE_KEY,
                status="running",
                records_seen=0,
                records_written=0,
                message=f"Resume after entity ID {last_id:,}; cached data only; zero network calls",
            )
        )
        run_id = int(result.inserted_primary_key[0])
    _save_checkpoint(last_id, "running", f"Started supplier cache backfill run #{run_id}")

    completed = False
    try:
        while True:
            remaining = None if limit_entities is None else max(0, int(limit_entities) - scanned)
            if remaining == 0:
                break
            page_limit = batch_size if remaining is None else min(batch_size, remaining)

            with connect() as conn:
                rows = conn.execute(
                    select(entities.c.id, entities.c.enrichment)
                    .where(entities.c.id > last_id)
                    .order_by(entities.c.id.asc())
                    .limit(page_limit)
                ).mappings().all()
                if not rows:
                    completed = True
                    break

                for row in rows:
                    entity_id = int(row["id"])
                    last_id = entity_id
                    scanned += 1
                    enrichment = row["enrichment"] if isinstance(row["enrichment"], dict) else {}
                    profile = enrichment.get("importyeti")
                    if not isinstance(profile, dict) or not profile.get("suppliers_table"):
                        continue
                    cached_profiles += 1
                    relationships_written += sync_supplier_relationships(conn, entity_id, profile)

            _save_checkpoint(
                last_id,
                "running",
                f"Run #{run_id} committed through entity ID {last_id:,}",
            )
            elapsed = time.monotonic() - started
            rate = scanned / elapsed if elapsed > 0 else 0
            print(
                f"[supplier-backfill] entity {last_id:,} · {scanned:,} scanned · "
                f"{cached_profiles:,} cached ImportYeti profiles · {relationships_written:,} relationships · "
                f"{rate:,.0f} entities/s · elapsed {_fmt_elapsed(elapsed)}",
                flush=True,
            )

            if len(rows) < page_limit:
                completed = True
                break

        status = "completed" if completed else "paused"
        elapsed = time.monotonic() - started
        _save_checkpoint(
            last_id,
            status,
            (
                f"Run #{run_id} completed cached supplier scan"
                if completed
                else f"Run #{run_id} paused at requested entity limit"
            ),
        )
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status=status,
                    records_seen=scanned,
                    records_written=relationships_written,
                    message=(
                        f"Entity ID {start_id:,}->{last_id:,}; {cached_profiles:,} cached profiles; "
                        f"{relationships_written:,} supplier relationships; zero network calls; "
                        f"elapsed {_fmt_elapsed(elapsed)}"
                    ),
                    finished_at=func.now(),
                )
            )
    except (Exception, KeyboardInterrupt) as exc:
        elapsed = time.monotonic() - started
        _save_checkpoint(last_id, "interrupted", f"Run #{run_id} interrupted: {str(exc)[:500]}")
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="failed",
                    records_seen=scanned,
                    records_written=relationships_written,
                    message=f"{str(exc)[:1500]} | zero network calls | elapsed {_fmt_elapsed(elapsed)}",
                    finished_at=func.now(),
                )
            )
        raise

    return {
        "source": SOURCE_KEY,
        "status": "completed" if completed else "paused",
        "start_entity_id": start_id,
        "end_entity_id": last_id,
        "entities_scanned": scanned,
        "cached_profiles": cached_profiles,
        "supplier_relationships_written": relationships_written,
        "network_calls": 0,
        "elapsed": _fmt_elapsed(time.monotonic() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resumable cached-only supplier relationship backfill"
    )
    parser.add_argument("--fresh", action="store_true", help="Ignore the saved entity-ID checkpoint")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--limit-entities",
        type=int,
        default=None,
        help="Optional number of canonical entities to scan before pausing",
    )
    args = parser.parse_args()
    result: dict[str, Any] = run_supplier_backfill(
        resume=not args.fresh,
        batch_size=args.batch_size,
        limit_entities=args.limit_entities,
    )
    print(result)


if __name__ == "__main__":
    main()
