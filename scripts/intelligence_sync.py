from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from intelligence.registry import get_source, list_sources


async def sync_source(source_key: str, cache_dir: Path, sample: int) -> None:
    source = get_source(source_key)
    print(f"Syncing {source.display_name} ({source.key})")
    paths = await source.fetch(cache_dir)
    print(f"Downloaded {len(paths)} artifact(s) to {cache_dir / source.key}")

    count = 0
    examples: list[dict] = []
    async for record in source.iter_records(paths):
        count += 1
        if len(examples) < sample:
            examples.append(record.model_dump(mode="json"))

    print(f"Parsed {count:,} normalized record(s)")
    if examples:
        print(json.dumps(examples, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync an IntellCluster open-data source")
    parser.add_argument("source", nargs="?", help="Source key to sync")
    parser.add_argument("--cache-dir", default="data/intelligence", help="Download/cache directory")
    parser.add_argument("--sample", type=int, default=3, help="Print N normalized sample records")
    parser.add_argument("--list", action="store_true", help="List registered sources")
    args = parser.parse_args()

    if args.list:
        print(json.dumps(list_sources(), indent=2))
        return
    if not args.source:
        parser.error("source is required unless --list is used")

    asyncio.run(sync_source(args.source, Path(args.cache_dir), max(0, args.sample)))


if __name__ == "__main__":
    main()
