from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import func, insert, update

from intelligence.database import connect, sync_runs
from intelligence.registry import get_source
from intelligence.repository import upsert_source_record


async def sync_source(
    source_key: str,
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
) -> dict[str, int | str]:
    adapter = get_source(source_key)
    seen = 0
    written = 0
    created = 0
    batch = []
    with connect() as conn:
        run_result = conn.execute(insert(sync_runs).values(source=source_key, status="running"))
        run_id = int(run_result.inserted_primary_key[0])

    def flush(records: list) -> tuple[int, int]:
        if not records:
            return 0, 0
        batch_written = 0
        batch_created = 0
        with connect() as conn:
            for record in records:
                _, was_created = upsert_source_record(conn, record)
                batch_written += 1
                batch_created += int(was_created)
        return batch_written, batch_created

    try:
        paths = await adapter.fetch(Path(cache_dir))
        async for record in adapter.iter_records(paths):
            seen += 1
            batch.append(record)
            if len(batch) >= batch_size:
                batch_written, batch_created = flush(batch)
                written += batch_written
                created += batch_created
                batch.clear()
            if limit and seen >= limit:
                break
        batch_written, batch_created = flush(batch)
        written += batch_written
        created += batch_created
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="completed",
                    records_seen=seen,
                    records_written=written,
                    finished_at=func.now(),
                )
            )
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="failed",
                    records_seen=seen,
                    records_written=written,
                    message=str(exc)[:2000],
                    finished_at=func.now(),
                )
            )
        raise
    return {"source": source_key, "seen": seen, "written": written, "entities_created": created}


async def sync_canada(
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
) -> list[dict[str, int | str]]:
    results = []
    # Corporate registry first gives importer matching a stronger canonical base.
    for source in ("corporations_canada", "canadian_importers"):
        results.append(
            await sync_source(source, cache_dir=cache_dir, limit=limit, batch_size=batch_size)
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IntellCluster public intelligence sources")
    parser.add_argument("source", choices=["corporations_canada", "canadian_importers", "canada"])
    parser.add_argument("--cache-dir", default=".cache/intelligence")
    parser.add_argument("--limit", type=int, default=None, help="Useful for staged imports and smoke tests")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.source == "canada":
        result = asyncio.run(
            sync_canada(cache_dir=args.cache_dir, limit=args.limit, batch_size=args.batch_size)
        )
    else:
        result = asyncio.run(
            sync_source(args.source, cache_dir=args.cache_dir, limit=args.limit, batch_size=args.batch_size)
        )
    print(result)


if __name__ == "__main__":
    main()
