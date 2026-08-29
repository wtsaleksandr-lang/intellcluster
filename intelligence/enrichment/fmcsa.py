from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from intelligence.models import SourceRecord


DATASET_ID = "az4n-8mr2"
RESOURCE_URL = f"https://data.transportation.gov/resource/{DATASET_ID}.json"
SELECT_FIELDS = (
    "dot_number,status_code,legal_name,dba_name,phy_street,phy_city,phy_state,"
    "phy_zip,phy_country,phone,cell_phone,power_units,total_drivers,mcs150_date,add_date,carrier_operation"
)


@dataclass(frozen=True)
class FMCSACompany:
    dot_number: str
    legal_name: str
    dba_name: str | None
    status_code: str | None
    street: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    phone: str | None
    cell_phone: str | None
    power_units: int | None
    total_drivers: int | None
    mcs150_date: str | None
    add_date: str | None
    carrier_operation: str | None

    @property
    def display_name(self) -> str:
        return self.legal_name or self.dba_name or f"USDOT {self.dot_number}"

    def to_source_record(self) -> SourceRecord:
        address = ", ".join(value for value in [self.street, self.city, self.state, self.postal_code] if value)
        return SourceRecord(
            source="fmcsa_company_census",
            source_record_id=self.dot_number,
            name=self.display_name,
            entity_type="company",
            country=self.country,
            region=self.state,
            city=self.city,
            postal_code=self.postal_code,
            address=address or None,
            source_url=f"https://safer.fmcsa.dot.gov/query.asp?searchtype=ANY&query_type=queryCarrierSnapshot&query_param=USDOT&query_string={self.dot_number}",
            attributes={
                "usdot_number": self.dot_number,
                "dba_name": self.dba_name,
                "status": self.status_code,
                "phone": self.phone,
                "cell_phone": self.cell_phone,
                "power_units": self.power_units,
                "total_drivers": self.total_drivers,
                "mcs150_date": self.mcs150_date,
                "add_date": self.add_date,
                "carrier_operation": self.carrier_operation,
                "dataset": "FMCSA Company Census File",
            },
        )


def _fixture() -> list[dict[str, Any]] | None:
    path = os.getenv("FMCSA_FIXTURE_PATH", "").strip()
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else payload.get("results") or []


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _company(row: dict[str, Any]) -> FMCSACompany | None:
    dot_number = str(row.get("dot_number") or "").strip()
    legal_name = str(row.get("legal_name") or "").strip()
    country = str(row.get("phy_country") or "").strip().upper()
    if not dot_number or not legal_name or country != "US":
        return None
    return FMCSACompany(
        dot_number=dot_number,
        legal_name=legal_name,
        dba_name=str(row.get("dba_name") or "").strip() or None,
        status_code=str(row.get("status_code") or "").strip() or None,
        street=str(row.get("phy_street") or "").strip() or None,
        city=str(row.get("phy_city") or "").strip() or None,
        state=str(row.get("phy_state") or "").strip() or None,
        postal_code=str(row.get("phy_zip") or "").strip() or None,
        country="US",
        phone=str(row.get("phone") or "").strip() or None,
        cell_phone=str(row.get("cell_phone") or "").strip() or None,
        power_units=_int_or_none(row.get("power_units")),
        total_drivers=_int_or_none(row.get("total_drivers")),
        mcs150_date=str(row.get("mcs150_date") or "").strip() or None,
        add_date=str(row.get("add_date") or "").strip() or None,
        carrier_operation=str(row.get("carrier_operation") or "").strip() or None,
    )


class FMCSAClient:
    """Free Company Census lookup used for U.S. identity/fleet evidence.

    Bulk ingestion is intentionally separate from this client so normal searches
    can validate mappings without triggering a multi-million-row download.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    async def search(self, query: str, *, limit: int = 20, active_only: bool = False) -> list[FMCSACompany]:
        fixture = _fixture()
        if fixture is not None:
            rows = fixture
        else:
            term = query.strip().upper().replace("'", "''")
            conditions = ["phy_country='US'"]
            if active_only:
                conditions.append("status_code='A'")
            if term:
                conditions.append(f"(upper(legal_name) like '%{term}%' OR upper(dba_name) like '%{term}%')")
            params = {
                "$select": SELECT_FIELDS,
                "$where": " AND ".join(conditions),
                "$order": "status_code ASC, legal_name ASC",
                "$limit": str(max(1, min(int(limit), 100))),
            }
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(RESOURCE_URL, params=params)
                response.raise_for_status()
                rows = response.json()

        results: list[FMCSACompany] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            company = _company(row)
            if company is not None:
                results.append(company)
            if len(results) >= limit:
                break
        return results

    async def by_usdot(self, dot_number: str) -> FMCSACompany | None:
        fixture = _fixture()
        if fixture is not None:
            rows = fixture
        else:
            digits = "".join(ch for ch in str(dot_number) if ch.isdigit())
            if not digits:
                return None
            params = {
                "$select": SELECT_FIELDS,
                "$where": f"dot_number={digits} AND phy_country='US'",
                "$limit": "1",
            }
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(RESOURCE_URL, params=params)
                response.raise_for_status()
                rows = response.json()
        for row in rows:
            if str(row.get("dot_number") or "") == str(dot_number):
                return _company(row)
        return None
