from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from sqlalchemy import func, insert, select, update

from intelligence.database import connect, source_records, sync_checkpoints, sync_runs
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


def _load_resume_position(source_key: str) -> tuple[int, str]:
    """Return the best persisted resume position for a source.

    Existing installations predate checkpoints, so the first resumable run may
    safely bootstrap from the number of unique source records already stored.
    Subsequent interrupted runs always use the explicit checkpoint instead.
    """
    with connect() as conn:
        checkpoint = conn.execute(
            select(sync_checkpoints.c.position, sync_checkpoints.c.status).where(
                sync_checkpoints.c.source == source_key
            )
        ).mappings().first()
        if checkpoint and int(checkpoint["position"] or 0) > 0 and checkpoint["status"] != "completed":
            return int(checkpoint["position"]), "checkpoint"
        stored = conn.execute(
            select(func.count()).select_from(source_records).where(source_records.c.source == source_key)
        ).scalar_one()
    return int(stored or 0), "stored source-record count"


def _save_checkpoint(source_key: str, position: int, status: str, message: str | None = None) -> None:
    with connect() as conn:
        existing = conn.execute(
            select(sync_checkpoints.c.source).where(sync_checkpoints.c.source == source_key)
        ).scalar_one_or_none()
        values = {
            "position": max(0, int(position)),
            "status": status,
            "message": message,
            "updated_at": func.now(),
        }
        if existing is None:
            conn.execute(insert(sync_checkpoints).values(source=source_key, **values))
        else:
            conn.execute(update(sync_checkpoints).where(sync_checkpoints.c.source == source_key).values(**values))


def print_status() -> None:
    """Print concise persisted sync state without contacting external sources."""
    with connect() as conn:
        stored_rows = conn.execute(
            select(source_records.c.source, func.count().label("count"))
            .group_by(source_records.c.source)
            .order_by(source_records.c.source)
        ).all()
        checkpoints = {
            row["source"]: row
            for row in conn.execute(select(sync_checkpoints)).mappings().all()
        }
        latest_runs = conn.execute(
            select(sync_runs).order_by(sync_runs.c.id.desc()).limit(20)
        ).mappings().all()

    print("IntellCluster sync status")
    print("=" * 72)
    for source, count in stored_rows:
        checkpoint = checkpoints.get(source)
        checkpoint_text = ""
        if checkpoint:
            checkpoint_text = (
                f" | checkpoint {int(checkpoint['position'] or 0):,} "
                f"({checkpoint['status']})"
            )
        print(f"{source:24} stored {int(count):,}{checkpoint_text}")

    print("\nRecent sync runs")
    print("-" * 72)
    for row in latest_runs:
        finished = row["finished_at"] or "—"
        print(
            f"#{row['id']:>3} {row['source']:<24} {row['status']:<10} "
            f"seen={int(row['records_seen'] or 0):>9,} written={int(row['records_written'] or 0):>9,} "
            f"finished={finished}"
        )
        if row["message"]:
            print(f"    {str(row['message'])[:180]}")


async def sync_source(
    source_key: str,
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
    progress_every: int = 5000,
    resume: bool = False,
) -> dict[str, int | str]:
    adapter = get_source(source_key)
    seen = 0
    written = 0
    created = 0
    batch = []
    started = time.monotonic()
    resume_from = 0
    resume_basis = ""

    if resume:
        resume_from, resume_basis = _load_resume_position(source_key)
        print(
            f"[{source_key}] Resume enabled: skipping first {resume_from:,} source records "
            f"using {resume_basis}.",
            flush=True,
        )

    print(f"[{source_key}] Starting sync...", flush=True)
    with connect() as conn:
        run_result = conn.execute(
            insert(sync_runs).values(
                source=source_key,
                status="running",
                records_seen=resume_from if resume else 0,
                records_written=0,
                message=f"Resume from {resume_from:,} via {resume_basis}" if resume else None,
            )
        )
        run_id = int(run_result.inserted_primary_key[0])

    if resume:
        _save_checkpoint(source_key, resume_from, "running", f"Started/resumed run #{run_id}")

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
            if resume and seen <= resume_from:
                continue

            batch.append(record)
            if len(batch) >= batch_size:
                batch_written, batch_created = flush(batch)
                written += batch_written
                created += batch_created
                batch.clear()

                if resume:
                    _save_checkpoint(source_key, seen, "running", f"Run #{run_id} committed through source position {seen:,}")

                if progress_every > 0 and written % progress_every < batch_size:
                    elapsed = time.monotonic() - started
                    rate = written / elapsed if elapsed > 0 else 0
                    print(
                        f"[{source_key}] source position {seen:,} · {written:,} written this run · "
                        f"{created:,} new entities · {rate:,.0f} writes/s · elapsed {_fmt_elapsed(elapsed)}",
                        flush=True,
                    )
            if limit and written >= limit:
                break

        batch_written, batch_created = flush(batch)
        written += batch_written
        created += batch_created
        if resume and batch_written:
            _save_checkpoint(source_key, seen, "running", f"Run #{run_id} committed through source position {seen:,}")
        elapsed = time.monotonic() - started

        completed_full_source = limit is None
        if resume:
            checkpoint_status = "completed" if completed_full_source else "paused"
            _save_checkpoint(
                source_key,
                seen,
                checkpoint_status,
                f"Run #{run_id} {'completed source' if completed_full_source else 'stopped at limit'}",
            )

        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="completed" if completed_full_source else "paused",
                    records_seen=seen,
                    records_written=written,
                    message=(
                        f"Completed source in {_fmt_elapsed(elapsed)}"
                        if completed_full_source
                        else f"Stopped at limit after {_fmt_elapsed(elapsed)}"
                    ),
                    finished_at=func.now(),
                )
            )

        print(
            f"[{source_key}] {'Completed' if completed_full_source else 'Paused'}: "
            f"source position {seen:,} · {written:,} written this run · {created:,} new entities · "
            f"elapsed {_fmt_elapsed(elapsed)}",
            flush=True,
        )
    except Exception as exc:
        elapsed = time.monotonic() - started
        if resume:
            _save_checkpoint(
                source_key,
                max(resume_from, seen - len(batch)),
                "interrupted",
                f"Run #{run_id} failed/interrupted: {str(exc)[:500]}",
            )
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
        "resume_from": resume_from,
        "elapsed": _fmt_elapsed(elapsed),
    }


async def sync_canada(
    *,
    cache_dir: str = ".cache/intelligence",
    limit: int | None = None,
    batch_size: int = 500,
    progress_every: int = 5000,
    resume: bool = False,
) -> list[dict[str, int | str]]:
    results = []
    for source in ("corporations_canada", "canadian_importers"):
        results.append(
            await sync_source(
                source,
                cache_dir=cache_dir,
                limit=limit,
                batch_size=batch_size,
                progress_every=progress_every,
                resume=resume,
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IntellCluster public intelligence sources")
    parser.add_argument("source", choices=["corporations_canada", "canadian_importers", "canada", "status"])
    parser.add_argument("--cache-dir", default=".cache/intelligence")
    parser.add_argument("--limit", type=int, default=None, help="Maximum new records to write in this run")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--progress-every",
        type=int,
        default=5000,
        help="Print a progress line after roughly this many committed records; 0 disables progress output",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from a persistent checkpoint; first use bootstraps from stored source-record count",
    )
    args = parser.parse_args()

    if args.source == "status":
        print_status()
        return

    if args.source == "canada":
        result = asyncio.run(
            sync_canada(
                cache_dir=args.cache_dir,
                limit=args.limit,
                batch_size=args.batch_size,
                progress_every=args.progress_every,
                resume=args.resume,
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
                resume=args.resume,
            )
        )
    print(result)


if __name__ == "__main__":
    main()
