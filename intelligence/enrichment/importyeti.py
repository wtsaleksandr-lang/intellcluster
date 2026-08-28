from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


@dataclass(slots=True)
class ImportYetiMatch:
    slug: str
    title: str
    address: str | None
    total_shipments: int | None
    most_recent_shipment: str | None


class ImportYetiClient:
    """Async client for lazy, persistent ImportYeti enrichment."""

    BASE_URL = "https://data.importyeti.com/v1.0"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("IMPORTYETI_API_KEY")
        if not self.api_key:
            raise RuntimeError("IMPORTYETI_API_KEY is not configured")

    @property
    def headers(self) -> dict[str, str]:
        return {"IYApiKey": self.api_key, "Accept": "application/json"}

    async def _get(
        self,
        path: str,
        *,
        timeout: int = 45,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout, headers=self.headers) as client:
            response = await client.get(f"{self.BASE_URL}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
        data = dict(payload.get("data") or {})
        data["_requestCost"] = payload.get("requestCost")
        data["_creditsRemaining"] = payload.get("creditsRemaining")
        data["_cachedAt"] = datetime.now(UTC).isoformat()
        return data

    async def search_company(self, name: str, page_size: int = 5) -> list[ImportYetiMatch]:
        async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
            response = await client.get(
                f"{self.BASE_URL}/company/search",
                params={"name": name, "page_size": max(1, min(page_size, 10)), "offset": 0},
            )
            response.raise_for_status()
            payload = response.json()
        matches: list[ImportYetiMatch] = []
        for item in payload.get("data", []) or []:
            key = str(item.get("key") or "")
            if not key.startswith("company/"):
                continue
            matches.append(
                ImportYetiMatch(
                    slug=key.split("company/", 1)[1],
                    title=str(item.get("title") or ""),
                    address=item.get("address"),
                    total_shipments=item.get("totalShipments"),
                    most_recent_shipment=item.get("mostRecentShipment"),
                )
            )
        return matches

    async def company_profile(self, slug: str) -> dict[str, Any]:
        return await self._get(f"/company/{slug}")

    async def bol_detail(self, bol_number: str) -> dict[str, Any]:
        clean = "".join(ch for ch in bol_number if ch.isalnum() or ch in {"-", "_"})
        if not clean:
            raise ValueError("Invalid BOL number")
        return await self._get(f"/bol/{clean}")


def cache_is_fresh(cache: dict[str, Any] | None, max_age_days: int = 30) -> bool:
    """Stale data remains usable; false only means it is eligible for refresh."""
    if not cache:
        return False
    cached_at = cache.get("_cachedAt")
    if not cached_at:
        return False
    try:
        parsed = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) - parsed <= timedelta(days=max_age_days)


def compact_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Preserve fields used by interactive company-profile analytics."""
    keep = {
        "title",
        "also_known_names",
        "address",
        "address_plain",
        "other_addresses_contact_info",
        "website",
        "other_websites",
        "phone_number",
        "total_shipments",
        "country",
        "country_code",
        "carriers_per_country",
        "container_types",
        "containers",
        "containers_load",
        "map_table",
        "lane_permutations",
        "date_range",
        "time_series",
        "hs_codes",
        "bill_type_shipments",
        "suppliers_table",
        "notify_party_shipments",
        "notify_party_shipments_perc",
        "internal_notify_party_shipments",
        "internal_notify_party_shipments_perc",
        "notify_party_table",
        "recent_bols",
        "total_shipping_cost",
        "avg_teu_per_shipment",
        "avg_teu_per_month",
        "_requestCost",
        "_creditsRemaining",
        "_cachedAt",
    }
    result = {key: value for key, value in data.items() if key in keep}
    if isinstance(result.get("suppliers_table"), list):
        result["suppliers_table"] = result["suppliers_table"][:60]
    if isinstance(result.get("recent_bols"), list):
        result["recent_bols"] = result["recent_bols"][:150]
    if isinstance(result.get("lane_permutations"), list):
        result["lane_permutations"] = result["lane_permutations"][:60]
    if isinstance(result.get("notify_party_table"), list):
        result["notify_party_table"] = result["notify_party_table"][:40]
    if isinstance(result.get("other_addresses_contact_info"), list):
        result["other_addresses_contact_info"] = result["other_addresses_contact_info"][:60]
    return result
