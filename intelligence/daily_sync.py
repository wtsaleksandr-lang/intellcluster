from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Integer, String, Table, Text, and_, delete, func, insert, select

from intelligence.database import connect, metadata, source_records
from intelligence.freshness import sync_delta_stats
from intelligence.incremental import upsert_source_record_incremental
from intelligence.registry import get_source
from intelligence.source_watch import check_source_files

source_retirements = Table(
    "intel_source_retirements",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(80), nullable=False),
    Column("source_record_id", String(700), nullable=False),
    Column("dataset", String(160)),
    Column("reason", Text),
    Column("retired_at", DateTime(timezone=True), server_default=func.now()),
)


def _write_stats(
    source: str,
    *,
    status: str,
    files_changed: int,
    added: int = 0,
    updated: int = 0,
    unchanged: int = 0,
    retired: int = 0,
    message: str = "",
) -> None:
    with connect() as conn:
        conn.execute(
            insert(sync_delta_stats).values(
                source=source,
                status=status,
                files_changed=files_changed,
                records_added=added,
                records_updated=updated,
                records_unchanged=unchanged,
                records_retired=retired,
                message=message or None,
            )
        )


def _existing_ids_for_dataset(source: str, dataset: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            select(source_records.c.source_record_id, source_records.c.attributes).where(source_records.c.source == source)
        ).mappings().all()
    return {
        str(row["source_record_id"])
        for row in rows
        if isinstance(row["attributes"], dict) and str(row["attributes"].get("dataset") or "") == dataset
    }


def _mark_retired(source: str, dataset: str, record_ids: set[str]) -> int:
    if not record_ids:
        return 0
    written = 0
    with connect() as conn:
        for record_id in record_ids:
            exists = conn.execute(
                select(source_retirements.c.id).where(
                    and_(
                        source_retirements.c.source == source,
                        source_retirements.c.source_record_id == record_id,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                conn.execute(
                    insert(source_retirements).values(
                        source=source,
                        source_record_id=record_id,
                        dataset=dataset,
                        reason="No longer present in latest official source snapshot",
                    )
                )
                written += 1
    return written


def _clear_retirement(source: str, record_id: str) -> None:
    with connect() as conn:
        conn.execute(
            delete(source_retirements).where(
                and_(
                    source_retirements.c.source == source,
                    source_retirements.c.source_record_id == record_id,
                )
            )
        )


async def daily_sync_corporations(
    *,
    cache_dir: str = ".cache/intelligence",
    batch_size: int = 500,
) -> dict[str, Any]:
    source = "corporations_canada"
    watch = await check_source_files(source)
    if any(row["baseline"] for row in watch):
        _write_stats(
            source,
            status="baseline",
            files_changed=0,
            message="Source file metadata baseline established; no data replay performed.",
        )
        return {"source": source, "status": "baseline", "files_changed": 0}

    changed = [row for row in watch if row["changed"]]
    if not changed:
        _write_stats(source, status="completed", files_changed=0, message="Source checked; no published files changed.")
        return {"source": source, "status": "completed", "files_changed": 0, "added": 0, "updated": 0, "retired": 0}

    adapter = get_source(source)
    target_dir = Path(cache_dir) / source
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[tuple[str, Path]] = []
    headers = {"User-Agent": "Mozilla/5.0 IntellCluster/1.0", "Accept": "text/csv,text/plain,*/*;q=0.8"}
    async with httpx.AsyncClient(timeout=180, follow_redirects=True, headers=headers) as client:
        for row in changed:
            response = await client.get(row["url"])
            response.raise_for_status()
            if not response.content:
                raise RuntimeError(f"Empty Corporations Canada CSV: {row['file_key']}")
            path = target_dir / f"{row['file_key']}.csv"
            path.write_bytes(response.content)
            downloaded.append((str(row["file_key"]), path))

    added = updated = unchanged = retired = 0
    for file_key, path in downloaded:
        dataset = path.stem
        previous_ids = _existing_ids_for_dataset(source, dataset)
        seen_ids: set[str] = set()
        batch = []

        async def flush(records: list) -> None:
            nonlocal added, updated, unchanged
            if not records:
                return
            with connect() as conn:
                for record in records:
                    _entity_id, entity_created, state = upsert_source_record_incremental(conn, record)
                    seen_ids.add(record.source_record_id)
                    if entity_created:
                        added += 1
                    elif state == "updated":
                        updated += 1
                    elif state == "unchanged":
                        unchanged += 1
                    if state in {"new", "updated"}:
                        conn.execute(
                            delete(source_retirements).where(
                                and_(
                                    source_retirements.c.source == source,
                                    source_retirements.c.source_record_id == record.source_record_id,
                                )
                            )
                        )

        async for record in adapter.iter_records([path]):
            batch.append(record)
            if len(batch) >= batch_size:
                await flush(batch)
                batch.clear()
        await flush(batch)
        retired += _mark_retired(source, dataset, previous_ids - seen_ids)

    _write_stats(
        source,
        status="completed",
        files_changed=len(changed),
        added=added,
        updated=updated,
        unchanged=unchanged,
        retired=retired,
        message="Incremental Corporations Canada refresh completed.",
    )
    return {
        "source": source,
        "status": "completed",
        "files_changed": len(changed),
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "retired": retired,
    }


async def daily_sync_canada() -> list[dict[str, Any]]:
    # Corporations Canada is daily-updated and now uses true changed-file sync.
    # CID has a different publication cadence; source_watch still checks it
    # cheaply, while incremental workbook ingestion is added separately.
    corporate = await daily_sync_corporations()
    importer_watch = await check_source_files("canadian_importers")
    importer_changed = [row for row in importer_watch if row["changed"]]
    if any(row["baseline"] for row in importer_watch):
        _write_stats(
            "canadian_importers",
            status="baseline",
            files_changed=0,
            message="Canadian Importers source metadata baseline established.",
        )
        importer = {"source": "canadian_importers", "status": "baseline", "files_changed": 0}
    elif not importer_changed:
        _write_stats(
            "canadian_importers",
            status="completed",
            files_changed=0,
            message="Canadian Importers source checked; no published files changed.",
        )
        importer = {"source": "canadian_importers", "status": "completed", "files_changed": 0}
    else:
        _write_stats(
            "canadian_importers",
            status="attention",
            files_changed=len(importer_changed),
            message="Canadian Importers workbook change detected; incremental workbook refresh pending.",
        )
        importer = {
            "source": "canadian_importers",
            "status": "attention",
            "files_changed": len(importer_changed),
        }
    return [corporate, importer]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cheap incremental maintenance for public intelligence sources")
    parser.add_argument("source", nargs="?", default="canada", choices=["canada", "corporations_canada"])
    parser.add_argument("--cache-dir", default=".cache/intelligence")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.source == "corporations_canada":
        result = asyncio.run(daily_sync_corporations(cache_dir=args.cache_dir, batch_size=args.batch_size))
    else:
        result = asyncio.run(daily_sync_canada())
    print(result)


if __name__ == "__main__":
    main()
