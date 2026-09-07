from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import and_, select

from intelligence.database import connect, entities, normalize_name
from intelligence.repository import set_entity_enrichment

SOURCE_KEY = "uspto_patents"
SOURCE_NAME = "USPTO PatentsView Annualized Patent Data"
SOURCE_URL = "https://data.uspto.gov/bulkdata/datasets/pvannual"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "patent_id": ("patent_id", "patent_number", "patent_num", "patent"),
    "title": ("patent_title", "title", "invention_title"),
    "grant_date": ("patent_date", "grant_date", "date", "grant_dt"),
    "assignee_name": (
        "assignee_organization",
        "assignee_name",
        "organization",
        "company",
        "assignee",
    ),
    "assignee_id": ("assignee_id", "organization_id", "org_id"),
    "assignee_city": ("assignee_city", "city"),
    "assignee_state": ("assignee_state", "state", "region"),
    "assignee_country": ("assignee_country", "country"),
    "cpc_section": (
        "cpc_section",
        "cpc_section_id",
        "technology_field",
        "technology_category",
    ),
}


def _header_key(value: str) -> str:
    return "_".join(part for part in "".join(ch.lower() if ch.isalnum() else " " for ch in value).split() if part)


def _field_map(headers: Iterable[str]) -> dict[str, str]:
    normalized = {_header_key(header): header for header in headers if header}
    mapping: dict[str, str] = {}
    for target, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                mapping[target] = normalized[alias]
                break
    missing = [key for key in ("patent_id", "assignee_name") if key not in mapping]
    if missing:
        raise ValueError(
            "USPTO CSV is missing required fields: "
            + ", ".join(missing)
            + ". Expected PatentsView-style patent and assignee columns."
        )
    return mapping


def _text(row: dict[str, Any], mapping: dict[str, str], key: str) -> str:
    column = mapping.get(key)
    return str(row.get(column) or "").strip() if column else ""


def _country_code(value: str) -> str:
    text = value.strip().upper()
    aliases = {
        "USA": "US",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
        "CANADA": "CA",
        "CAN": "CA",
    }
    return aliases.get(text, text)


def _patent_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, str]:
    return {
        "patent_id": _text(row, mapping, "patent_id"),
        "title": _text(row, mapping, "title"),
        "grant_date": _text(row, mapping, "grant_date"),
        "assignee_name": _text(row, mapping, "assignee_name"),
        "assignee_id": _text(row, mapping, "assignee_id"),
        "assignee_city": _text(row, mapping, "assignee_city"),
        "assignee_state": _text(row, mapping, "assignee_state").upper(),
        "assignee_country": _country_code(_text(row, mapping, "assignee_country")),
        "cpc_section": _text(row, mapping, "cpc_section").upper(),
    }


def read_patentsview_csv(path: str | Path) -> list[dict[str, str]]:
    """Read a PatentsView-style CSV without making any network request."""
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("USPTO CSV has no header row")
        mapping = _field_map(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = _patent_row(raw, mapping)
            if row["patent_id"] and row["assignee_name"]:
                rows.append(row)
    return rows


def _candidate_for_assignee(conn, group: list[dict[str, str]]) -> dict[str, Any] | None:
    names = [row["assignee_name"] for row in group if row["assignee_name"]]
    if not names:
        return None
    normalized = normalize_name(names[0])
    if not normalized:
        return None

    countries = {row["assignee_country"] for row in group if row["assignee_country"] in {"US", "CA"}}
    conditions = [entities.c.name_normalized == normalized]
    if len(countries) == 1:
        conditions.append(entities.c.country == next(iter(countries)))
    candidates = [
        dict(row)
        for row in conn.execute(
            select(
                entities.c.id,
                entities.c.country,
                entities.c.region,
                entities.c.city,
                entities.c.canonical_name,
            )
            .where(and_(*conditions))
            .limit(25)
        ).mappings().all()
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None

    states = {row["assignee_state"].casefold() for row in group if row["assignee_state"]}
    cities = {row["assignee_city"].casefold() for row in group if row["assignee_city"]}
    ranked: list[tuple[int, dict[str, Any]]] = []
    for candidate in candidates:
        score = 0
        region = str(candidate.get("region") or "").strip().casefold()
        city = str(candidate.get("city") or "").strip().casefold()
        if region and region in states:
            score += 2
        if city and city in cities:
            score += 1
        ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 2:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def _payload(
    group: list[dict[str, str]],
    *,
    snapshot_file: str,
    max_patents: int,
) -> dict[str, Any]:
    unique: dict[str, dict[str, str]] = {}
    for row in group:
        unique.setdefault(row["patent_id"], row)
    patents = list(unique.values())
    patents.sort(key=lambda row: (row.get("grant_date") or "", row.get("patent_id") or ""), reverse=True)
    dates = sorted(row["grant_date"] for row in patents if row["grant_date"])
    sections = Counter(row["cpc_section"] for row in patents if row["cpc_section"])
    names = Counter(row["assignee_name"] for row in group if row["assignee_name"])
    assignee_ids = sorted({row["assignee_id"] for row in group if row["assignee_id"]})
    return {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "dataset": "pvannual",
        "snapshot_file": snapshot_file,
        "matched_assignee": names.most_common(1)[0][0] if names else "",
        "assignee_ids": assignee_ids[:20],
        "total_patents": len(patents),
        "latest_grant_date": dates[-1] if dates else None,
        "earliest_grant_date": dates[0] if dates else None,
        "technology_sections": [
            {"code": code, "count": count} for code, count in sections.most_common(12)
        ],
        "patents": [
            {
                "patent_id": row["patent_id"],
                "title": row["title"],
                "grant_date": row["grant_date"],
                "cpc_section": row["cpc_section"],
            }
            for row in patents[:max(1, max_patents)]
        ],
        "_cachedAt": datetime.now(timezone.utc).isoformat(),
        "network_calls": False,
    }


def ingest_patentsview_csv(
    path: str | Path,
    *,
    dry_run: bool = False,
    limit_assignees: int | None = None,
    max_patents_per_company: int = 30,
) -> dict[str, int]:
    """Attach official PatentsView bulk evidence to existing canonical entities.

    This intentionally does not create new companies. Matching is exact on the
    normalized assignee name and conservative on country/location when duplicate
    canonical names exist. The function only reads a local CSV and the database.
    """
    csv_path = Path(path)
    rows = read_patentsview_csv(csv_path)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = normalize_name(row["assignee_name"])
        if key:
            groups[key].append(row)

    stats = {
        "rows_read": len(rows),
        "assignees_seen": 0,
        "entities_matched": 0,
        "entities_updated": 0,
        "ambiguous_or_unmatched": 0,
    }
    with connect() as conn:
        for key in sorted(groups):
            if limit_assignees is not None and stats["assignees_seen"] >= limit_assignees:
                break
            stats["assignees_seen"] += 1
            group = groups[key]
            candidate = _candidate_for_assignee(conn, group)
            if not candidate:
                stats["ambiguous_or_unmatched"] += 1
                continue
            stats["entities_matched"] += 1
            if dry_run:
                continue
            set_entity_enrichment(
                conn,
                int(candidate["id"]),
                SOURCE_KEY,
                _payload(
                    group,
                    snapshot_file=csv_path.name,
                    max_patents=max_patents_per_company,
                ),
            )
            stats["entities_updated"] += 1
    return stats


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach local USPTO PatentsView annualized CSV evidence to IntellCluster companies."
    )
    parser.add_argument("--csv", required=True, dest="csv_path", help="Path to an official PatentsView CSV")
    parser.add_argument("--dry-run", action="store_true", help="Match and report without writing enrichment")
    parser.add_argument("--limit-assignees", type=int, default=None)
    parser.add_argument("--max-patents-per-company", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stats = ingest_patentsview_csv(
        args.csv_path,
        dry_run=args.dry_run,
        limit_assignees=args.limit_assignees,
        max_patents_per_company=args.max_patents_per_company,
    )
    print(
        "USPTO PatentsView bulk sync: "
        + ", ".join(f"{key}={value}" for key, value in stats.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
