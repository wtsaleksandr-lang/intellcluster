from __future__ import annotations

import argparse
import asyncio
from typing import Any

import httpx
from sqlalchemy import Column, DateTime, Integer, String, Table, Text, and_, func, insert, select, update

from intelligence.database import connect, metadata
from intelligence.registry import get_source

source_file_state = Table(
    "intel_source_file_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", String(80), nullable=False),
    Column("file_key", String(160), nullable=False),
    Column("url", Text, nullable=False),
    Column("etag", String(500)),
    Column("last_modified", String(500)),
    Column("content_length", String(80)),
    Column("checked_at", DateTime(timezone=True), server_default=func.now()),
    Column("changed_at", DateTime(timezone=True)),
)


def _signature(headers: httpx.Headers) -> tuple[str, str, str]:
    return (
        str(headers.get("etag") or "").strip(),
        str(headers.get("last-modified") or "").strip(),
        str(headers.get("content-length") or "").strip(),
    )


async def check_source_files(source_key: str, *, persist: bool = True) -> list[dict[str, Any]]:
    """Cheaply check whether a source's published files changed.

    This performs HEAD requests only. It does not download or parse the datasets.
    A first check establishes a baseline and reports `baseline=True` rather than
    claiming every file is a newly changed dataset.
    """
    adapter = get_source(source_key)
    datasets = getattr(adapter, "DATASETS", None)
    if not isinstance(datasets, dict) or not datasets:
        return []

    with connect() as conn:
        previous = {
            row["file_key"]: row
            for row in conn.execute(
                select(source_file_state).where(source_file_state.c.source == source_key)
            ).mappings().all()
        }

    results: list[dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0 IntellCluster/1.0", "Accept": "*/*"}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True, headers=headers) as client:
        for file_key, url in datasets.items():
            response = await client.head(url)
            response.raise_for_status()
            etag, last_modified, content_length = _signature(response.headers)
            old = previous.get(file_key)
            baseline = old is None
            old_signature = (
                str(old.get("etag") or "") if old else "",
                str(old.get("last_modified") or "") if old else "",
                str(old.get("content_length") or "") if old else "",
            )
            new_signature = (etag, last_modified, content_length)
            # Some publishers omit one or more validators. Compare all validators
            # that are available rather than treating a missing header as a change.
            comparable = any(new_signature) and any(old_signature)
            changed = bool(not baseline and comparable and new_signature != old_signature)
            results.append(
                {
                    "source": source_key,
                    "file_key": file_key,
                    "url": url,
                    "baseline": baseline,
                    "changed": changed,
                    "etag": etag,
                    "last_modified": last_modified,
                    "content_length": content_length,
                }
            )

            if persist:
                with connect() as conn:
                    current = conn.execute(
                        select(source_file_state.c.id).where(
                            and_(
                                source_file_state.c.source == source_key,
                                source_file_state.c.file_key == file_key,
                            )
                        )
                    ).scalar_one_or_none()
                    values = {
                        "url": url,
                        "etag": etag or None,
                        "last_modified": last_modified or None,
                        "content_length": content_length or None,
                        "checked_at": func.now(),
                    }
                    if changed or baseline:
                        values["changed_at"] = func.now()
                    if current is None:
                        conn.execute(
                            insert(source_file_state).values(
                                source=source_key,
                                file_key=file_key,
                                **values,
                            )
                        )
                    else:
                        conn.execute(
                            update(source_file_state)
                            .where(source_file_state.c.id == current)
                            .values(**values)
                        )
    return results


async def check_canada_sources() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in ("corporations_canada", "canadian_importers"):
        rows.extend(await check_source_files(source))
    return rows


def _print(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No file-level source metadata available.")
        return
    print("IntellCluster source watch")
    print("=" * 72)
    for row in rows:
        if row["baseline"]:
            state = "BASELINE"
        elif row["changed"]:
            state = "CHANGED"
        else:
            state = "unchanged"
        size = row.get("content_length") or "?"
        modified = row.get("last_modified") or "unknown"
        print(f"{row['source']:<22} {row['file_key']:<28} {state:<9} size={size} modified={modified}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check public source files for changes without downloading them")
    parser.add_argument("source", nargs="?", default="canada", choices=["canada", "corporations_canada", "canadian_importers"])
    args = parser.parse_args()
    if args.source == "canada":
        rows = asyncio.run(check_canada_sources())
    else:
        rows = asyncio.run(check_source_files(args.source))
    _print(rows)


if __name__ == "__main__":
    main()
