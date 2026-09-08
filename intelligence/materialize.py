from __future__ import annotations

import argparse
import math
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection

from intelligence.database import (
    connect,
    entities,
    importer_relationships,
    json_safe,
    source_records,
    supplier_relationships,
    sync_checkpoints,
    sync_runs,
)

SOURCE_KEY = "entity_intelligence_materialization"
MATERIALIZATION_VERSION = 1

_PROVIDER_LABELS = {
    "importyeti": "trade shipments",
    "fmcsa": "fleet/carrier",
    "usaspending": "U.S. contracts",
    "epa_echo": "EPA compliance",
    "osha": "OSHA compliance",
    "sec": "SEC filings",
    "sec_edgar": "SEC filings",
    "uspto": "U.S. patents",
    "patentsview": "U.S. patents",
    "canadabuys": "Canada contracts",
    "canada_buys": "Canada contracts",
}


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


def materialization_status() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            select(
                sync_checkpoints.c.position,
                sync_checkpoints.c.status,
                sync_checkpoints.c.message,
                sync_checkpoints.c.updated_at,
            ).where(sync_checkpoints.c.source == SOURCE_KEY)
        ).mappings().first()
        entity_count = int(
            conn.execute(select(func.count()).select_from(entities)).scalar_one() or 0
        )
    return {
        "source": SOURCE_KEY,
        "status": str(row["status"] or "not_started") if row else "not_started",
        "position": int(row["position"] or 0) if row else 0,
        "message": str(row["message"] or "") if row else "",
        "updated_at": row["updated_at"] if row else None,
        "entity_count": entity_count,
        "complete": bool(row and str(row["status"] or "") == "completed"),
        "version": MATERIALIZATION_VERSION,
        "network_calls": 0,
        "paid_sources_called": False,
    }


def _provider_keys(enrichment: dict[str, Any]) -> list[str]:
    providers: list[str] = []
    for key, payload in enrichment.items():
        if key in {"intelligence", "us_public_lookup", "us_compliance_lookup"}:
            continue
        if key.startswith("importyeti_bol:"):
            continue
        if payload in (None, {}, []):
            continue
        providers.append(str(key))
    return sorted(set(providers))


def _bounded_log_points(value: int, maximum: int, *, scale: float) -> int:
    if value <= 0:
        return 0
    return min(maximum, int(round(maximum * math.log1p(value) / math.log1p(scale))))


def _buyer_score(
    *,
    is_importer: bool,
    source_count: int,
    importer_relationship_count: int,
    hs_count: int,
    origin_count: int,
    supplier_count: int,
    supplier_shipments: int,
    provider_count: int,
    has_website: bool,
    has_corporation_number: bool,
) -> int:
    score = 0
    score += min(18, source_count * 6)
    score += _bounded_log_points(importer_relationship_count, 20, scale=80)
    score += min(8, hs_count * 2)
    score += min(6, origin_count * 2)
    score += _bounded_log_points(supplier_count, 12, scale=25)
    score += _bounded_log_points(supplier_shipments, 12, scale=500)
    score += min(10, provider_count * 2)
    score += 3 if has_website else 0
    score += 3 if has_corporation_number else 0
    score += 8 if is_importer else 0
    return max(0, min(100, int(score)))


def _evidence_score(
    *,
    source_count: int,
    source_record_count: int,
    provider_count: int,
    relationship_count: int,
) -> int:
    score = min(36, source_count * 12)
    score += _bounded_log_points(source_record_count, 24, scale=100)
    score += min(24, provider_count * 6)
    score += _bounded_log_points(relationship_count, 16, scale=100)
    return max(0, min(100, int(score)))


def _summary(
    row: dict[str, Any],
    *,
    source_count: int,
    relationship_count: int,
    hs_count: int,
    origin_count: int,
    supplier_count: int,
    provider_labels: list[str],
) -> str:
    name = str(row.get("canonical_name") or "This company")
    country = str(row.get("country") or "").upper()
    geography = "Canadian" if country == "CA" else "U.S." if country == "US" else ""
    role = "importer" if row.get("is_importer") else "company"
    lead = f"{name} is a {geography + ' ' if geography else ''}{role}"
    facts: list[str] = []
    if relationship_count:
        detail = f"{relationship_count:,} observed import record{'s' if relationship_count != 1 else ''}"
        if hs_count:
            detail += f" across {hs_count:,} HS code{'s' if hs_count != 1 else ''}"
        if origin_count:
            detail += f" and {origin_count:,} origin countr{'ies' if origin_count != 1 else 'y'}"
        facts.append(detail)
    if supplier_count:
        facts.append(f"{supplier_count:,} linked supplier{'s' if supplier_count != 1 else ''}")
    if source_count:
        facts.append(f"evidence from {source_count:,} source dataset{'s' if source_count != 1 else ''}")
    if provider_labels:
        facts.append("additional " + ", ".join(provider_labels[:3]) + " intelligence")
    return lead + (" with " + "; ".join(facts) if facts else "") + "."


def _page_source_stats(conn: Connection, ids: list[int]) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = defaultdict(dict)
    rows = conn.execute(
        select(
            source_records.c.entity_id,
            source_records.c.source,
            func.count(source_records.c.id).label("records"),
        )
        .where(source_records.c.entity_id.in_(ids))
        .group_by(source_records.c.entity_id, source_records.c.source)
    ).mappings().all()
    for row in rows:
        result[int(row["entity_id"])][str(row["source"])] = int(row["records"] or 0)
    return result


def _page_import_stats(conn: Connection, ids: list[int]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "hs": Counter(),
            "origins": Counter(),
            "products": Counter(),
            "years": Counter(),
        }
    )
    rows = conn.execute(
        select(
            importer_relationships.c.entity_id,
            importer_relationships.c.activity_year,
            importer_relationships.c.hs6,
            importer_relationships.c.hs10,
            importer_relationships.c.product_description,
            importer_relationships.c.origin_country,
        ).where(importer_relationships.c.entity_id.in_(ids))
    ).mappings().all()
    for row in rows:
        stat = result[int(row["entity_id"])]
        stat["count"] += 1
        code = str(row["hs10"] or row["hs6"] or "").strip()
        if code:
            stat["hs"][code] += 1
        origin = str(row["origin_country"] or "").strip()
        if origin:
            stat["origins"][origin] += 1
        product = str(row["product_description"] or "").strip()
        if product:
            stat["products"][product] += 1
        year = row["activity_year"]
        if year:
            stat["years"][str(year)] += 1
    return result


def _page_supplier_stats(conn: Connection, ids: list[int]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "shipments": 0, "top": []}
    )
    rows = conn.execute(
        select(
            supplier_relationships.c.importer_entity_id,
            supplier_relationships.c.supplier_name,
            supplier_relationships.c.supplier_country,
            supplier_relationships.c.total_shipments,
        ).where(supplier_relationships.c.importer_entity_id.in_(ids))
    ).mappings().all()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["importer_entity_id"])].append(dict(row))
    for entity_id, suppliers in grouped.items():
        suppliers.sort(key=lambda item: int(item.get("total_shipments") or 0), reverse=True)
        result[entity_id] = {
            "count": len(suppliers),
            "shipments": sum(int(item.get("total_shipments") or 0) for item in suppliers),
            "top": [
                {
                    "name": str(item.get("supplier_name") or ""),
                    "country": str(item.get("supplier_country") or ""),
                    "shipments": int(item.get("total_shipments") or 0),
                }
                for item in suppliers[:10]
                if item.get("supplier_name")
            ],
        }
    return result


def materialize_rows(conn: Connection, rows: list[dict[str, Any]]) -> int:
    """Materialize one entity page using only already-ingested database evidence."""
    if not rows:
        return 0
    ids = [int(row["id"]) for row in rows]
    source_stats = _page_source_stats(conn, ids)
    import_stats = _page_import_stats(conn, ids)
    supplier_stats = _page_supplier_stats(conn, ids)
    processed_at = datetime.now(UTC).isoformat()

    written = 0
    for row in rows:
        entity_id = int(row["id"])
        sources = source_stats.get(entity_id, {})
        source_count = len(sources)
        source_record_count = sum(sources.values())

        imports = import_stats.get(entity_id) or {
            "count": 0,
            "hs": Counter(),
            "origins": Counter(),
            "products": Counter(),
            "years": Counter(),
        }
        relationships = int(imports["count"])
        hs_count = len(imports["hs"])
        origin_count = len(imports["origins"])

        suppliers = supplier_stats.get(entity_id) or {"count": 0, "shipments": 0, "top": []}
        supplier_count = int(suppliers["count"])
        supplier_shipments = int(suppliers["shipments"])

        enrichment = row.get("enrichment") if isinstance(row.get("enrichment"), dict) else {}
        enrichment = dict(enrichment)
        providers = _provider_keys(enrichment)
        provider_labels = sorted({_PROVIDER_LABELS.get(key, key.replace("_", " ")) for key in providers})

        buyer_score = _buyer_score(
            is_importer=bool(row.get("is_importer")),
            source_count=source_count,
            importer_relationship_count=relationships,
            hs_count=hs_count,
            origin_count=origin_count,
            supplier_count=supplier_count,
            supplier_shipments=supplier_shipments,
            provider_count=len(providers),
            has_website=bool(str(row.get("website") or "").strip()),
            has_corporation_number=bool(str(row.get("corporation_number") or "").strip()),
        )
        evidence_score = _evidence_score(
            source_count=source_count,
            source_record_count=source_record_count,
            provider_count=len(providers),
            relationship_count=relationships + supplier_count,
        )

        signals: list[str] = []
        if row.get("is_importer"):
            signals.append("observed_importer")
        if relationships:
            signals.append("import_history")
        if supplier_count:
            signals.append("supplier_network")
        if len(providers) >= 2:
            signals.append("multi_source_enrichment")
        if source_count >= 2:
            signals.append("cross_source_identity")

        intelligence = {
            "version": MATERIALIZATION_VERSION,
            "processed_at": processed_at,
            "source_coverage": [
                {"source": source, "records": count}
                for source, count in sorted(sources.items())
            ],
            "source_count": source_count,
            "source_record_count": source_record_count,
            "importer_relationship_count": relationships,
            "hs_code_count": hs_count,
            "origin_country_count": origin_count,
            "product_count": len(imports["products"]),
            "supplier_count": supplier_count,
            "supplier_shipments": supplier_shipments,
            "enrichment_sources": providers,
            "evidence_score": evidence_score,
            "buyer_score": buyer_score,
            "buyer_score_method": "deterministic_evidence_v1",
            "signals": signals,
            "top_hs_codes": [
                {"code": code, "records": count}
                for code, count in imports["hs"].most_common(12)
            ],
            "top_origins": [
                {"country": country, "records": count}
                for country, count in imports["origins"].most_common(12)
            ],
            "top_products": [
                {"description": description, "records": count}
                for description, count in imports["products"].most_common(12)
            ],
            "activity_years": [
                {"year": year, "records": count}
                for year, count in sorted(imports["years"].items(), reverse=True)[:12]
            ],
            "top_suppliers": suppliers["top"],
            "network_calls": 0,
            "paid_sources_called": False,
        }
        summary = _summary(
            row,
            source_count=source_count,
            relationship_count=relationships,
            hs_count=hs_count,
            origin_count=origin_count,
            supplier_count=supplier_count,
            provider_labels=provider_labels,
        )
        enrichment["intelligence"] = intelligence
        conn.execute(
            update(entities)
            .where(entities.c.id == entity_id)
            .values(
                summary=summary,
                buyer_score=buyer_score,
                enrichment=json_safe(enrichment),
                updated_at=func.now(),
            )
        )
        written += 1
    return written


def run_intelligence_materialization(
    *,
    resume: bool = True,
    batch_size: int = 1000,
    limit_entities: int | None = None,
    start_after_id: int | None = None,
) -> dict[str, Any]:
    """Build combined company intelligence from already-ingested data.

    The job is database-only: it does not instantiate external clients and cannot
    consume paid API credits. Progress is checkpointed by canonical entity ID.
    """
    batch_size = max(50, min(int(batch_size), 5000))
    started = time.monotonic()
    if start_after_id is not None:
        last_id = max(0, int(start_after_id))
    else:
        last_id = _load_checkpoint() if resume else 0
    start_id = last_id
    scanned = 0
    written = 0

    with connect() as conn:
        result = conn.execute(
            insert(sync_runs).values(
                source=SOURCE_KEY,
                status="running",
                records_seen=0,
                records_written=0,
                message=f"Resume after entity ID {last_id:,}; database-only materialization",
            )
        )
        run_id = int(result.inserted_primary_key[0])
    _save_checkpoint(last_id, "running", f"Started intelligence materialization run #{run_id}")

    completed = False
    try:
        while True:
            remaining = None if limit_entities is None else max(0, int(limit_entities) - scanned)
            if remaining == 0:
                break
            page_limit = batch_size if remaining is None else min(batch_size, remaining)
            with connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        select(
                            entities.c.id,
                            entities.c.canonical_name,
                            entities.c.country,
                            entities.c.region,
                            entities.c.city,
                            entities.c.website,
                            entities.c.corporation_number,
                            entities.c.is_importer,
                            entities.c.enrichment,
                        )
                        .where(entities.c.id > last_id)
                        .order_by(entities.c.id.asc())
                        .limit(page_limit)
                    ).mappings().all()
                ]
                if not rows:
                    completed = True
                    break
                written += materialize_rows(conn, rows)
                scanned += len(rows)
                last_id = int(rows[-1]["id"])

            _save_checkpoint(
                last_id,
                "running",
                f"Run #{run_id} committed through entity ID {last_id:,}",
            )
            elapsed = time.monotonic() - started
            rate = scanned / elapsed if elapsed > 0 else 0
            print(
                f"[intelligence-materialize] entity {last_id:,} · {scanned:,} scanned · "
                f"{written:,} materialized · {rate:,.0f} entities/s · elapsed {_fmt_elapsed(elapsed)}",
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
                f"Run #{run_id} completed entity intelligence materialization"
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
                    records_written=written,
                    message=(
                        f"Entity ID {start_id:,}->{last_id:,}; {written:,} materialized; "
                        f"zero network calls; elapsed {_fmt_elapsed(elapsed)}"
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
                    records_written=written,
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
        "entities_materialized": written,
        "version": MATERIALIZATION_VERSION,
        "network_calls": 0,
        "paid_sources_called": False,
        "elapsed": _fmt_elapsed(time.monotonic() - started),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resumable database-only IntellCluster post-ingestion materialization"
    )
    parser.add_argument("--fresh", action="store_true", help="Ignore the saved entity-ID checkpoint")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--limit-entities",
        type=int,
        default=None,
        help="Optional number of canonical entities to process before pausing",
    )
    args = parser.parse_args()
    result = run_intelligence_materialization(
        resume=not args.fresh,
        batch_size=args.batch_size,
        limit_entities=args.limit_entities,
    )
    print(result)


if __name__ == "__main__":
    main()
