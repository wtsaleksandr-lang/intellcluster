from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

from intelligence.database import connect, entities, normalize_name
from intelligence.repository import set_entity_enrichment

SOURCE_KEY = "canadabuys_contracts"
SOURCE_NAME = "CanadaBuys Contract History"
SOURCE_URL = "https://open.canada.ca/data/en/dataset/4fe645a1-ffcd-40c1-9385-2c771be956a4"
DOWNLOAD_URL = "https://canadabuys.canada.ca/opendata/pub/contractHistoryComplete-contratsOctroyesComplet.csv"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "supplier_name": (
        "supplierLegalName-nomLegalFournisseur-eng",
        "supplierLegalName",
        "supplier_name",
        "supplier",
    ),
    "contract_number": (
        "contractNumber-numeroContrat",
        "contractNumber",
        "contract_number",
    ),
    "reference_number": (
        "referenceNumber-numeroReference",
        "referenceNumber",
        "reference_number",
    ),
    "title": ("title-titre-eng", "title", "contract_title"),
    "award_description": (
        "awardDescription-descriptionAttribution-eng",
        "awardDescription",
        "description",
    ),
    "award_date": (
        "contractAwardDate-dateAttributionContrat",
        "contractAwardDate",
        "award_date",
    ),
    "publication_date": (
        "publicationDate-datePublication",
        "publicationDate",
        "publication_date",
    ),
    "amendment_date": (
        "amendmentDate-dateModification",
        "amendmentDate",
        "amendment_date",
    ),
    "start_date": (
        "contractStartDate-contratDateDebut",
        "contractStartDate",
        "start_date",
    ),
    "end_date": (
        "contractEndDate-dateFinContrat",
        "contractEndDate",
        "end_date",
    ),
    "contract_amount": (
        "contractAmount-montantContrat",
        "contractAmount",
        "contract_amount",
    ),
    "total_contract_value": (
        "totalContractValue-valeurTotaleContrat",
        "totalContractValue",
        "total_contract_value",
    ),
    "currency": (
        "contractCurrency-contratMonnaie",
        "contractCurrency",
        "currency",
    ),
    "contracting_entity": (
        "contractingEntityName-nomEntitContractante-eng",
        "contractingEntityName",
        "organization",
        "contracting_entity",
    ),
    "status": (
        "awardStatus-attributionStatut-eng",
        "awardStatus",
        "status",
    ),
    "instrument_type": (
        "instrumentType-typeInstrument-eng",
        "instrumentType",
        "instrument_type",
    ),
    "amendment_number": (
        "amendmentNumber-numeroModification",
        "amendmentNumber",
        "amendment_number",
    ),
    "amendment_type": (
        "amendmentType-typeModification-eng",
        "amendmentType",
        "amendment_type",
    ),
    "unspsc": ("unspsc", "UNSPSC"),
    "unspsc_description": (
        "unspscDescription-eng",
        "unspscDescription",
        "unspsc_description",
    ),
    "notice_type": (
        "noticeType-avisType-eng",
        "noticeType",
        "notice_type",
    ),
}


def _header_key(value: str) -> str:
    return "".join(ch.casefold() for ch in value.strip() if ch.isalnum())


def _field_map(headers: Iterable[str]) -> dict[str, str]:
    normalized = {_header_key(header): header for header in headers if header}
    mapping: dict[str, str] = {}
    for target, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            found = normalized.get(_header_key(alias))
            if found:
                mapping[target] = found
                break
    missing = [key for key in ("supplier_name", "contract_amount") if key not in mapping]
    if missing:
        raise ValueError(
            "CanadaBuys CSV is missing required fields: "
            + ", ".join(missing)
            + ". Expected current CanadaBuys contract-history columns."
        )
    if "contract_number" not in mapping and "reference_number" not in mapping:
        raise ValueError("CanadaBuys CSV requires a contract or reference number field")
    return mapping


def _text(row: dict[str, Any], mapping: dict[str, str], key: str) -> str:
    column = mapping.get(key)
    return str(row.get(column) or "").strip() if column else ""


def _money(value: str) -> Decimal | None:
    text = str(value or "").strip().replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _record(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    value = _money(_text(row, mapping, "total_contract_value"))
    value_basis = "total_contract_value"
    if value is None:
        value = _money(_text(row, mapping, "contract_amount"))
        value_basis = "contract_amount"
    currency = _text(row, mapping, "currency").upper() or "CAD"
    return {
        "supplier_name": _text(row, mapping, "supplier_name"),
        "contract_number": _text(row, mapping, "contract_number"),
        "reference_number": _text(row, mapping, "reference_number"),
        "title": _text(row, mapping, "title"),
        "award_description": _text(row, mapping, "award_description"),
        "award_date": _text(row, mapping, "award_date"),
        "publication_date": _text(row, mapping, "publication_date"),
        "amendment_date": _text(row, mapping, "amendment_date"),
        "start_date": _text(row, mapping, "start_date"),
        "end_date": _text(row, mapping, "end_date"),
        "value": str(value) if value is not None else "",
        "value_basis": value_basis if value is not None else "",
        "currency": currency,
        "contracting_entity": _text(row, mapping, "contracting_entity"),
        "status": _text(row, mapping, "status"),
        "instrument_type": _text(row, mapping, "instrument_type"),
        "notice_type": _text(row, mapping, "notice_type"),
        "amendment_number": _text(row, mapping, "amendment_number"),
        "amendment_type": _text(row, mapping, "amendment_type"),
        "unspsc": _text(row, mapping, "unspsc"),
        "unspsc_description": _text(row, mapping, "unspsc_description"),
    }


def read_canadabuys_csv(path: str | Path) -> list[dict[str, Any]]:
    """Read an official CanadaBuys contract-history CSV from local disk."""
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CanadaBuys CSV has no header row")
        mapping = _field_map(reader.fieldnames)
        rows: list[dict[str, Any]] = []
        for raw in reader:
            record = _record(raw, mapping)
            if record["supplier_name"] and (record["contract_number"] or record["reference_number"]):
                rows.append(record)
    return rows


def _contract_key(row: dict[str, Any]) -> str:
    return str(row.get("contract_number") or row.get("reference_number") or "").strip()


def _sort_date(row: dict[str, Any]) -> str:
    return str(
        row.get("amendment_date")
        or row.get("publication_date")
        or row.get("award_date")
        or ""
    )


def _latest_contracts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_contract: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _contract_key(row)
        if not key:
            continue
        current = by_contract.get(key)
        if current is None or (_sort_date(row), str(row.get("amendment_number") or "")) >= (
            _sort_date(current),
            str(current.get("amendment_number") or ""),
        ):
            by_contract[key] = row
    result = list(by_contract.values())
    result.sort(key=lambda row: (_sort_date(row), _contract_key(row)), reverse=True)
    return result


def _candidate(conn, supplier_name: str) -> dict[str, Any] | None:
    normalized = normalize_name(supplier_name)
    if not normalized:
        return None
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
            .where(entities.c.name_normalized == normalized)
            .limit(25)
        ).mappings().all()
    ]
    # Exact normalized-name evidence is acceptable only when it identifies one
    # canonical entity. Duplicate legal names are intentionally left unmatched.
    return candidates[0] if len(candidates) == 1 else None


def _payload(
    rows: list[dict[str, Any]],
    *,
    snapshot_file: str,
    max_contracts: int,
) -> dict[str, Any]:
    latest = _latest_contracts(rows)
    departments = Counter(str(row.get("contracting_entity") or "") for row in latest if row.get("contracting_entity"))
    categories = Counter()
    currencies = Counter(str(row.get("currency") or "CAD") for row in latest)
    for row in latest:
        raw = str(row.get("unspsc") or "").replace("*", "")
        for part in raw.replace("\r", "\n").split("\n"):
            code = "".join(ch for ch in part if ch.isdigit())
            if code:
                categories[code[:8]] += 1

    cad_total = Decimal("0")
    cad_valued_contracts = 0
    for row in latest:
        value = _money(str(row.get("value") or ""))
        if value is not None and str(row.get("currency") or "CAD").upper() == "CAD":
            cad_total += value
            cad_valued_contracts += 1

    supplier_names = Counter(str(row.get("supplier_name") or "") for row in rows if row.get("supplier_name"))
    return {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "download_url": DOWNLOAD_URL,
        "snapshot_file": snapshot_file,
        "matched_supplier": supplier_names.most_common(1)[0][0] if supplier_names else "",
        "contract_count": len(latest),
        "history_row_count": len(rows),
        "cad_value_shown": float(cad_total),
        "cad_valued_contract_count": cad_valued_contracts,
        "currencies": [{"code": code, "count": count} for code, count in currencies.most_common()],
        "top_departments": [{"name": name, "count": count} for name, count in departments.most_common(10)],
        "top_unspsc": [{"code": code, "count": count} for code, count in categories.most_common(12)],
        "contracts": latest[: max(1, max_contracts)],
        "value_note": (
            "Value shown sums the latest disclosed value retained for each unique contract in CAD. "
            "CanadaBuys contract history includes amendments; this is analytical context, not an audited spend total."
        ),
        "_cachedAt": datetime.now(timezone.utc).isoformat(),
        "network_calls": False,
    }


def ingest_canadabuys_csv(
    path: str | Path,
    *,
    dry_run: bool = False,
    limit_suppliers: int | None = None,
    max_contracts_per_company: int = 40,
) -> dict[str, int]:
    """Attach official CanadaBuys contract evidence to existing companies only."""
    csv_path = Path(path)
    rows = read_canadabuys_csv(csv_path)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = normalize_name(str(row.get("supplier_name") or ""))
        if key:
            groups[key].append(row)

    stats = {
        "rows_read": len(rows),
        "suppliers_seen": 0,
        "entities_matched": 0,
        "entities_updated": 0,
        "ambiguous_or_unmatched": 0,
    }
    with connect() as conn:
        for key in sorted(groups):
            if limit_suppliers is not None and stats["suppliers_seen"] >= limit_suppliers:
                break
            stats["suppliers_seen"] += 1
            group = groups[key]
            candidate = _candidate(conn, str(group[0].get("supplier_name") or ""))
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
                    max_contracts=max_contracts_per_company,
                ),
            )
            stats["entities_updated"] += 1
    return stats


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach local official CanadaBuys contract-history CSV evidence to IntellCluster companies."
    )
    parser.add_argument("--csv", required=True, dest="csv_path", help="Path to the official CanadaBuys contract-history CSV")
    parser.add_argument("--dry-run", action="store_true", help="Match and report without writing enrichment")
    parser.add_argument("--limit-suppliers", type=int, default=None)
    parser.add_argument("--max-contracts-per-company", type=int, default=40)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stats = ingest_canadabuys_csv(
        args.csv_path,
        dry_run=args.dry_run,
        limit_suppliers=args.limit_suppliers,
        max_contracts_per_company=args.max_contracts_per_company,
    )
    print("CanadaBuys bulk sync: " + ", ".join(f"{key}={value}" for key, value in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
