"""Promote normalized FMCSA evidence onto canonical U.S. company entities.

The bulk FMCSA ingest intentionally stays lean. This second resumable pass turns
stored Company Census source-record attributes into canonical status plus a small
cached fleet summary used by search cards and company profiles.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from sqlalchemy import and_, func, insert, select, update

from intelligence.database import connect, entities, json_safe, source_records, sync_checkpoints, sync_runs


SOURCE_KEY = "fmcsa_company_census"
CHECKPOINT_KEY = "fmcsa_company_census_promote"
STATUS_MAP = {"A": "Active", "P": "Pending", "I": "Inactive"}


def _load_checkpoint() -> int:
    with connect() as conn:
        value = conn.execute(
            select(sync_checkpoints.c.position).where(sync_checkpoints.c.source == CHECKPOINT_KEY)
        ).scalar_one_or_none()
    return int(value or 0)


def _save_checkpoint(position: int, status: str, message: str | None = None) -> None:
    with connect() as conn:
        exists = conn.execute(
            select(sync_checkpoints.c.source).where(sync_checkpoints.c.source == CHECKPOINT_KEY)
        ).scalar_one_or_none()
        values = {
            "position": max(0, int(position)),
            "status": status,
            "message": message,
            "updated_at": func.now(),
        }
        if exists is None:
            conn.execute(insert(sync_checkpoints).values(source=CHECKPOINT_KEY, **values))
        else:
            conn.execute(
                update(sync_checkpoints).where(sync_checkpoints.c.source == CHECKPOINT_KEY).values(**values)
            )


def _fleet_payload(attrs: dict[str, Any]) -> dict[str, Any]:
    code = str(attrs.get("status") or "").strip().upper()
    return {
        "dot_number": str(attrs.get("usdot_number") or "").strip() or None,
        "status_code": code or None,
        "status": STATUS_MAP.get(code, code or None),
        "dba_name": attrs.get("dba_name"),
        "phone": attrs.get("phone"),
        "cell_phone": attrs.get("cell_phone"),
        "power_units": attrs.get("power_units"),
        "total_drivers": attrs.get("total_drivers"),
        "mcs150_date": attrs.get("mcs150_date"),
        "add_date": attrs.get("add_date"),
        "carrier_operation": attrs.get("carrier_operation"),
        "dataset": attrs.get("dataset") or "FMCSA Company Census File",
    }


def promote_fmcsa(*, resume: bool = True, limit: int | None = None, batch_size: int = 5000) -> dict[str, int | str]:
    started = time.monotonic()
    last_id = _load_checkpoint() if resume else 0
    start_id = last_id
    processed = 0
    changed = 0

    with connect() as conn:
        result = conn.execute(
            insert(sync_runs).values(
                source=CHECKPOINT_KEY,
                status="running",
                records_seen=0,
                records_written=0,
                message=f"Promoting FMCSA canonical fleet/status evidence after source-record id {last_id:,}",
            )
        )
        run_id = int(result.inserted_primary_key[0])
    _save_checkpoint(last_id, "running", f"Started promotion run #{run_id}")

    try:
        while True:
            page_limit = max(1, min(int(batch_size), 50000))
            if limit is not None:
                remaining = int(limit) - processed
                if remaining <= 0:
                    break
                page_limit = min(page_limit, remaining)

            with connect() as conn:
                rows = conn.execute(
                    select(
                        source_records.c.id,
                        source_records.c.entity_id,
                        source_records.c.attributes,
                        entities.c.enrichment,
                    )
                    .select_from(source_records.join(entities, entities.c.id == source_records.c.entity_id))
                    .where(
                        and_(
                            source_records.c.source == SOURCE_KEY,
                            source_records.c.id > last_id,
                            entities.c.country == "US",
                        )
                    )
                    .order_by(source_records.c.id.asc())
                    .limit(page_limit)
                ).mappings().all()

                if not rows:
                    break

                for row in rows:
                    attrs = row["attributes"] if isinstance(row["attributes"], dict) else {}
                    fleet = _fleet_payload(attrs)
                    enrichment = dict(row["enrichment"] or {}) if isinstance(row["enrichment"], dict) else {}
                    previous = enrichment.get("fmcsa") if isinstance(enrichment.get("fmcsa"), dict) else None
                    status = fleet.get("status")
                    values: dict[str, Any] = {"updated_at": func.now()}
                    if status:
                        values["corporate_status"] = status
                    if previous != fleet:
                        enrichment["fmcsa"] = json_safe(fleet)
                        values["enrichment"] = enrichment
                        changed += 1
                    conn.execute(update(entities).where(entities.c.id == int(row["entity_id"])).values(**values))
                    last_id = int(row["id"])

            processed += len(rows)
            _save_checkpoint(last_id, "running", f"Run #{run_id} committed through source-record id {last_id:,}")
            print(f"[fmcsa-promote] {processed:,} processed · {changed:,} changed · source id {last_id:,}", flush=True)
            if len(rows) < page_limit:
                break

        status = "completed" if limit is None else "paused"
        elapsed = time.monotonic() - started
        _save_checkpoint(last_id, status, f"Run #{run_id} {status}; {processed:,} processed, {changed:,} changed")
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status=status,
                    records_seen=processed,
                    records_written=changed,
                    message=f"source id {start_id:,}->{last_id:,}; elapsed {elapsed:.1f}s",
                    finished_at=func.now(),
                )
            )
    except (Exception, KeyboardInterrupt) as exc:
        _save_checkpoint(last_id, "interrupted", f"Run #{run_id} interrupted: {str(exc)[:500]}")
        with connect() as conn:
            conn.execute(
                update(sync_runs)
                .where(sync_runs.c.id == run_id)
                .values(
                    status="failed",
                    records_seen=processed,
                    records_written=changed,
                    message=str(exc)[:1500],
                    finished_at=func.now(),
                )
            )
        raise

    return {
        "source": CHECKPOINT_KEY,
        "start_source_record_id": start_id,
        "end_source_record_id": last_id,
        "processed": processed,
        "changed": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote FMCSA source records into canonical status/fleet intelligence")
    parser.add_argument("--fresh", action="store_true", help="Ignore the saved promotion checkpoint")
    parser.add_argument("--limit", type=int, default=None, help="Maximum FMCSA source rows to promote")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    print(promote_fmcsa(resume=not args.fresh, limit=args.limit, batch_size=args.batch_size))


if __name__ == "__main__":
    main()
