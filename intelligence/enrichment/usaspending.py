from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


BASE_URL = "https://api.usaspending.gov"
CONTRACT_AWARD_TYPES = ["A", "B", "C", "D"]


@dataclass(frozen=True)
class USARecipientMatch:
    recipient_id: str
    name: str
    uei: str | None = None
    duns: str | None = None
    amount: float = 0.0
    recipient_level: str | None = None


def _fixture() -> dict[str, Any] | None:
    path = os.getenv("USASPENDING_FIXTURE_PATH", "").strip()
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    return json.loads(candidate.read_text(encoding="utf-8"))


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _recipient_location(row: dict[str, Any]) -> dict[str, str]:
    raw = row.get("Recipient Location") or row.get("recipient_location") or {}
    if isinstance(raw, str):
        return {"display": raw}
    if not isinstance(raw, dict):
        return {}

    def first(*keys: str) -> str:
        for key in keys:
            value = raw.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    return {
        "address": first("address_line1", "address_line_1", "street_address", "address"),
        "city": first("city_name", "city"),
        "state": first("state_code", "state"),
        "postal_code": first("zip4", "zip5", "postal_code", "zip"),
        "country": first("country_code", "country_name", "country"),
    }


class USAspendingClient:
    """Free, on-demand federal recipient/contract intelligence.

    This client is intentionally not a bulk directory crawler. It is used after
    an entity is being researched, and its normalized result can be persisted in
    the entity enrichment cache.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    async def search_recipients(self, query: str, *, limit: int = 10) -> list[USARecipientMatch]:
        fixture = _fixture()
        if fixture is not None:
            rows = fixture.get("recipient_search") or []
        else:
            payload = {
                "order": "desc",
                "sort": "amount",
                "page": 1,
                "limit": max(1, min(int(limit), 100)),
                "award_type": "contracts",
                "keyword": query,
            }
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.post(f"{BASE_URL}/api/v2/recipient/", json=payload)
                response.raise_for_status()
                rows = response.json().get("results") or []

        matches: list[USARecipientMatch] = []
        for row in rows[:limit]:
            if not isinstance(row, dict) or not row.get("id") or not row.get("name"):
                continue
            matches.append(
                USARecipientMatch(
                    recipient_id=str(row["id"]),
                    name=str(row["name"]),
                    uei=str(row["uei"]) if row.get("uei") else None,
                    duns=str(row["duns"]) if row.get("duns") else None,
                    amount=_money(row.get("amount")),
                    recipient_level=str(row["recipient_level"]) if row.get("recipient_level") else None,
                )
            )
        return matches

    async def contract_awards(self, recipient_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        fixture = _fixture()
        if fixture is not None:
            rows = fixture.get("awards") or []
        else:
            payload = {
                "subawards": False,
                "limit": max(1, min(int(limit), 100)),
                "page": 1,
                "filters": {
                    "award_type_codes": CONTRACT_AWARD_TYPES,
                    "recipient_id": recipient_id,
                    "recipient_scope": "domestic",
                },
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Recipient UEI",
                    "Recipient Location",
                    "Award Amount",
                    "Start Date",
                    "End Date",
                    "Awarding Agency",
                    "Awarding Sub Agency",
                    "Funding Agency",
                    "NAICS",
                    "PSC",
                    "Description",
                    "Last Modified Date",
                ],
                "sort": "Award Amount",
                "order": "desc",
            }
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.post(f"{BASE_URL}/api/v2/search/spending_by_award/", json=payload)
                response.raise_for_status()
                rows = response.json().get("results") or []
        return [dict(row) for row in rows[:limit] if isinstance(row, dict)]

    async def company_profile(self, query: str, *, award_limit: int = 25) -> dict[str, Any] | None:
        matches = await self.search_recipients(query, limit=5)
        if not matches:
            return None
        match = matches[0]
        awards = await self.contract_awards(match.recipient_id, limit=award_limit)
        return compact_usaspending_profile(match, awards)


def compact_usaspending_profile(match: USARecipientMatch, awards: list[dict[str, Any]]) -> dict[str, Any]:
    agencies: set[str] = set()
    naics: set[str] = set()
    psc: set[str] = set()
    locations: list[dict[str, str]] = []
    total_award_value = 0.0
    latest_modified = ""
    compact_awards: list[dict[str, Any]] = []

    for row in awards:
        amount = _money(row.get("Award Amount"))
        total_award_value += amount
        agency = str(row.get("Awarding Agency") or "").strip()
        if agency:
            agencies.add(agency)
        naics_value = str(row.get("NAICS") or "").strip()
        if naics_value:
            naics.add(naics_value)
        psc_value = str(row.get("PSC") or "").strip()
        if psc_value:
            psc.add(psc_value)
        location = _recipient_location(row)
        if location and location not in locations:
            locations.append(location)
        modified = str(row.get("Last Modified Date") or "")
        if modified > latest_modified:
            latest_modified = modified
        compact_awards.append(
            {
                "award_id": row.get("Award ID"),
                "amount": amount,
                "start_date": row.get("Start Date"),
                "end_date": row.get("End Date"),
                "awarding_agency": row.get("Awarding Agency"),
                "awarding_subagency": row.get("Awarding Sub Agency"),
                "funding_agency": row.get("Funding Agency"),
                "naics": row.get("NAICS"),
                "psc": row.get("PSC"),
                "description": row.get("Description"),
            }
        )

    return {
        "recipient_id": match.recipient_id,
        "name": match.name,
        "uei": match.uei,
        "duns": match.duns,
        "recipient_level": match.recipient_level,
        "trailing_12m_recipient_amount": match.amount,
        "contract_awards_shown": len(compact_awards),
        "contract_award_value_shown": total_award_value,
        "awarding_agencies": sorted(agencies),
        "naics": sorted(naics),
        "psc": sorted(psc),
        "locations": locations[:5],
        "latest_modified": latest_modified,
        "awards": compact_awards,
        "source": "USAspending.gov",
    }
