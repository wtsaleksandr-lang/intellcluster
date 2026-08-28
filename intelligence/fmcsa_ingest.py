from __future__ import annotations

import argparse
import asyncio
import time

import httpx
from sqlalchemy import func, insert, select, update

from intelligence.database import connect, sync_checkpoints, sync_runs
from intelligence.enrichment.fmcsa import RESOURCE_URL, SELECT_FIELDS, _company
from intelligence.incremental import upsert_source_record_incremental


SOURCE_KEY = "fmcsa_company_census"


def _fmt_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _load_checkpoint() -> int:
    with connect() as conn:
        row = conn.execute(
            select(sync_checkpoints.c.position).where(sync_checkpoints.c.source == SOURCE_KEY)
        ).scalar_one_or_none()
    return int(row or 0)


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
                update(sync_checkpoints).where(sync_checkpoints.c.source == SOURCE_KEY).values(**values)
            )


async def _page(after_dot: int, *, page_size: int, active_only: bool) -> list[dict]:
    conditions = ["phy_country='US'", f"dot_number>{max(0, int(after_dot))}"]
    if active_only:
        conditions.append("status_code='A'")
    params = {
        "$select": SELECT_FIELDS,
        "$where": " AND ".join(conditions),
        "$order": "dot_number ASC",
        "$limit": str(max(1, min(int(page_size), 50000))),
    }
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(RESOURCE_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    return [row for row in payload if isinstance(row, dict)]


async def sync_fmcsa(
    *,
    resume: bool = True,
    active_only: bool = True,
    limit: int | None = None,
    page_size: int = 5000,
) -> dict[str, int | str]:
    started = time.monotonic()
    last_dot = _load_checkpoint() if resume else 0
    initial_dot = last_dot
    seen = 0
    new = 0
    updated = 0
    unchanged = 0
    created = 0

    with connect() as conn:
        result = conn.execute(
            insert(sync_runs).values(
                source=SOURCE_KEY,
                status="running",
                records_seen=0,
                records_written=0,
                message=(
                    f"FMCSA keyset sync after USDOT {last_dot:,}; "
                    f"{'active US entities only' if active_only else 'all US statuses'}"
                ),
            )
        )
        run_id = int(result.inserted_primary_key[0])
    _save_checkpoint(last_dot, "running", f"Started FMCSA run #{run_id}")

    try:
        while True:
            rows = await _page(last_dot, page_size=page_size, active_only=active_only)
            if not rows:
                break

            records = []
            page_last_dot = last_dot
            for row in rows:
                company = _company(row)
                if company is None:
                    continue
                try:
                    dot_number = int(company.dot_number)
                except ValueError:
                    continue
                page_last_dot = max(page_last_dot, dot_number)
                records.append(company.to_source_record())

            if not records:
                # Advance across malformed/non-US rows so a bad page cannot loop forever.
                raw_dots = [int(str(row.get("dot_number"))) for row in rows if str(row.get("dot_number") or "").isdigit()]
                if not raw_dots:
                    break
                last_dot = max(raw_dots)
                _save_checkpoint(last_dot, "running", f"Run #{run_id} skipped a page with no usable records")
                continue

            if limit is not None:
                remaining = max(0, int(limit) - seen)
                records = records[:remaining]
                if not records:
                    break
                page_last_dot = int(records[-1].source_record_id)

            with connect() as conn:
                for record in records:
                    _, entity_created, state = upsert_source_record_incremental(conn, record)
                    created += int(entity_created)
                    if state == "new":
                        new += 1
                    elif state == "updated":
                        updated += 1
                    else:
                        unchanged += 1

            seen += len(records)
            last_dot = page_last_dot
            _save_checkpoint(last_dot, "running", f"Run #{run_id} committed through USDOT {last_dot:,}")
            elapsed = time.monotonic() - started
            print(
                f"[fmcsa] USDOT {last_dot:,} · {seen:,} processed · {new:,} new · "
                f"{updated:,} updated · {unchanged:,} unchanged · {created:,} new entities · "
                f"elapsed {_fmt_elapsed(elapsed)}",
                flush=True,
            )

            if limit is not None and seen >= limit:
                break
            if len(rows) < page_size:
                break

        completed = limit is None
        status = "completed" if completed else "paused"
        elapsed = time.monotonic() - started
        _save_checkpoint(
            last_dot,
            status,
            f"Run #{run_id} {'completed current query' if completed else 'paused at requested limit'}",
        )
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status=status,
                    records_seen=seen,
                    records_written=new + updated,
                    message=(
                        f"USDOT {initial_dot:,}->{last_dot:,}; {new:,} new, {updated:,} updated, "
                        f"{unchanged:,} unchanged; elapsed {_fmt_elapsed(elapsed)}"
                    ),
                    finished_at=func.now(),
                )
            )
    except (Exception, KeyboardInterrupt) as exc:
        elapsed = time.monotonic() - started
        _save_checkpoint(last_dot, "interrupted", f"Run #{run_id} interrupted: {str(exc)[:500]}")
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="failed",
                    records_seen=seen,
                    records_written=new + updated,
                    message=f"{str(exc)[:1500]} | elapsed {_fmt_elapsed(elapsed)}",
                    finished_at=func.now(),
                )
            )
        raise

    return {
        "source": SOURCE_KEY,
        "start_usdot": initial_dot,
        "end_usdot": last_dot,
        "processed": seen,
        "new": new,
        "updated": updated,
        "unchanged": unchanged,
        "entities_created": created,
        "elapsed": _fmt_elapsed(time.monotonic() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable FMCSA Company Census ingestion")
    parser.add_argument("--fresh", action="store_true", help="Ignore the saved USDOT checkpoint and start from zero")
    parser.add_argument("--all-statuses", action="store_true", help="Include inactive and pending U.S. entities")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records to process in this run")
    parser.add_argument("--page-size", type=int, default=5000)
    args = parser.parse_args()
    result = asyncio.run(
        sync_fmcsa(
            resume=not args.fresh,
            active_only=not args.all_statuses,
            limit=args.limit,
            page_size=args.page_size,
        )
    )
    print(result)


if __name__ == "__main__":
    main()
