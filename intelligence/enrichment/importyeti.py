from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class ImportYetiMatch:
    slug: str
    title: str
    address: str | None
    total_shipments: int | None
    most_recent_shipment: str | None


def live_importyeti_enabled() -> bool:
    """Return true only when paid/live ImportYeti network access is explicitly enabled.

    Cached data is the normal operating mode. This opt-in prevents ordinary page
    views, smoke tests, CI and UI development from accidentally consuming credits.
    """
    return os.getenv("IMPORTYETI_ALLOW_LIVE", "").strip().casefold() in {"1", "true", "yes", "on"}


def load_importyeti_fixture() -> dict[str, Any] | None:
    """Load one reusable local ImportYeti response for development/tests.

    Set IMPORTYETI_FIXTURE_PATH to a JSON file containing either the API data object
    or a full API response with a top-level ``data`` object. No network request is
    made when this fixture is used.
    """
    raw_path = os.getenv("IMPORTYETI_FIXTURE_PATH", "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    return dict(data) if isinstance(data, dict) else None


class ImportYetiClient:
    """Async client for controlled ImportYeti enrichment.

    Network access is intentionally disabled unless IMPORTYETI_ALLOW_LIVE=1.
    Development and tests should use persisted cache or IMPORTYETI_FIXTURE_PATH.
    """

    BASE_URL = "https://data.importyeti.com/v1.0"

    def __init__(self, api_key: str | None = None, *, allow_live: bool | None = None) -> None:
        self.api_key = api_key or os.getenv("IMPORTYETI_API_KEY")
        self.allow_live = live_importyeti_enabled() if allow_live is None else allow_live
        self.fixture = load_importyeti_fixture()
        if self.allow_live and not self.api_key:
            raise RuntimeError("IMPORTYETI_API_KEY is not configured")

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            return {"Accept": "application/json"}
        return {"IYApiKey": self.api_key, "Accept": "application/json"}

    def _assert_live_allowed(self) -> None:
        if not self.allow_live:
            raise RuntimeError(
                "Live ImportYeti requests are disabled. Use cached data or set "
                "IMPORTYETI_ALLOW_LIVE=1 for an intentional paid refresh."
            )

    async def _get(
        self,
        path: str,
        *,
        timeout: int = 45,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.fixture is not None:
            data = dict(self.fixture)
            data.setdefault("_cachedAt", datetime.now(UTC).isoformat())
            data["_fixture"] = True
            return data
        self._assert_live_allowed()
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
        if self.fixture is not None:
            title = str(self.fixture.get("title") or self.fixture.get("_matchedTitle") or name)
            slug = str(self.fixture.get("_slug") or "cached-test-company")
            return [
                ImportYetiMatch(
                    slug=slug,
                    title=title,
                    address=self.fixture.get("address") or self.fixture.get("address_plain"),
                    total_shipments=self.fixture.get("total_shipments"),
                    most_recent_shipment=None,
                )
            ]
        self._assert_live_allowed()
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
        "_fixture",
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
