from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from sqlalchemy import func, insert, update

from intelligence.database import connect, sync_runs
from intelligence.registry import get_source
from intelligence.repository import upsert_source_record


def _fmt_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


async def sync_source(
    source_key: str,
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
    progress_every: int = 5000,
) -> dict[str, int | str]:
    adapter = get_source(source_key)
    seen = 0
    written = 0
    created = 0
    batch = []
    started = time.monotonic()

    print(f"[{source_key}] Starting sync...", flush=True)
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
        print(f"[{source_key}] Source files ready: {len(paths)}", flush=True)
        async for record in adapter.iter_records(paths):
            seen += 1
            batch.append(record)
            if len(batch) >= batch_size:
                batch_written, batch_created = flush(batch)
                written += batch_written
                created += batch_created
                batch.clear()

                if progress_every > 0 and written % progress_every < batch_size:
                    elapsed = time.monotonic() - started
                    rate = written / elapsed if elapsed > 0 else 0
                    print(
                        f"[{source_key}] {written:,} written · {created:,} new entities · "
                        f"{rate:,.0f} records/s · elapsed {_fmt_elapsed(elapsed)}",
                        flush=True,
                    )
            if limit and seen >= limit:
                break

        batch_written, batch_created = flush(batch)
        written += batch_written
        created += batch_created
        elapsed = time.monotonic() - started

        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="completed",
                    records_seen=seen,
                    records_written=written,
                    message=f"Completed in {_fmt_elapsed(elapsed)}",
                    finished_at=func.now(),
                )
            )

        print(
            f"[{source_key}] Completed: {written:,} written · {created:,} new entities · "
            f"elapsed {_fmt_elapsed(elapsed)}",
            flush=True,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="failed",
                    records_seen=seen,
                    records_written=written,
                    message=f"{str(exc)[:1800]} | elapsed {_fmt_elapsed(elapsed)}",
                    finished_at=func.now(),
                )
            )
        print(
            f"[{source_key}] FAILED after {written:,} writes and {_fmt_elapsed(elapsed)}: {exc}",
            flush=True,
        )
        raise

    return {
        "source": source_key,
        "seen": seen,
        "written": written,
        "entities_created": created,
        "elapsed": _fmt_elapsed(elapsed),
    }


async def sync_canada(
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
    progress_every: int = 5000,
) -> list[dict[str, int | str]]:
    results = []
    # Corporate registry first gives importer matching a stronger canonical base.
    for source in ("corporations_canada", "canadian_importers"):
        results.append(
            await sync_source(
                source,
                cache_dir=cache_dir,
                limit=limit,
                batch_size=batch_size,
                progress_every=progress_every,
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IntellCluster public intelligence sources")
    parser.add_argument("source", choices=["corporations_canada", "canadian_importers", "canada"])
    parser.add_argument("--cache-dir", default=".cache/intelligence")
    parser.add_argument("--limit", type=int, default=None, help="Useful for staged imports and smoke tests")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5000,
        help="Print a progress line after roughly this many committed records; 0 disables progress output",
    )
    args = parser.parse_args()
    if args.source == "canada":
        result = asyncio.run(
            sync_canada(
                cache_dir=args.cache_dir,
                limit=args.limit,
                batch_size=args.batch_size,
                progress_every=args.progress_every,
            )
        )
    else:
        result = asyncio.run(
            sync_source(
                args.source,
                cache_dir=args.cache_dir,
                limit=args.limit,
                batch_size=args.batch_size,
                progress_every=args.progress_every,
            )
        )
    print(result)


if __name__ == "__main__":
    main()
