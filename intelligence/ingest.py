from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import insert, update

from intelligence.database import connect, sync_runs
from intelligence.registry import get_source
from intelligence.repository import upsert_source_record


async def sync_source(source_key: str, *, cache_dir: str = ".cache/intelligence", limit: int | None = None) -> dict[str, int | str]:
    adapter = get_source(source_key)
    seen = 0
    written = 0
    created = 0
    with connect() as conn:
        run_result = conn.execute(insert(sync_runs).values(source=source_key, status="running"))
        run_id = int(run_result.inserted_primary_key[0])

    try:
        paths = await adapter.fetch(Path(cache_dir))
        async for record in adapter.iter_records(paths):
            seen += 1
            with connect() as conn:
                _, was_created = upsert_source_record(conn, record)
                written += 1
                created += int(was_created)
            if limit and seen >= limit:
                break
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(status="completed", records_seen=seen, records_written=written, finished_at=__import__("sqlalchemy").func.now())
            )
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(status="failed", records_seen=seen, records_written=written, message=str(exc)[:2000], finished_at=__import__("sqlalchemy").func.now())
            )
        raise
    return {"source": source_key, "seen": seen, "written": written, "entities_created": created}


async def sync_canada(*, cache_dir: str = ".cache/intelligence", limit: int | None = None) -> list[dict[str, int | str]]:
    results = []
    # Corporate registry first gives importer matching a stronger canonical base.
    for source in ("corporations_canada", "canadian_importers"):
        results.append(await sync_source(source, cache_dir=cache_dir, limit=limit))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IntellCluster public intelligence sources")
    parser.add_argument("source", choices=["corporations_canada", "canadian_importers", "canada"])
    parser.add_argument("--cache-dir", default=".cache/intelligence")
    parser.add_argument("--limit", type=int, default=None, help="Useful for local smoke tests")
    args = parser.parse_args()
    if args.source == "canada":
        result = asyncio.run(sync_canada(cache_dir=args.cache_dir, limit=args.limit))
    else:
        result = asyncio.run(sync_source(args.source, cache_dir=args.cache_dir, limit=args.limit))
    print(result)


if __name__ == "__main__":
    main()
