from __future__ import annotations

import os
from typing import Any

import httpx


class HunterClient:
    """Small Hunter.io client designed for lazy, cached enrichment.

    Do not enrich the full corpus up front. Call this only for entities that
    users view/search/export and persist the response in the application DB.
    """

    BASE_URL = "https://api.hunter.io/v2"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("HUNTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("HUNTER_API_KEY is not configured")

    async def domain_search(
        self,
        domain: str,
        *,
        limit: int = 10,
        department: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "domain": domain,
            "api_key": self.api_key,
            "limit": max(1, min(limit, 100)),
        }
        if department:
            params["department"] = department
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.BASE_URL}/domain-search", params=params)
            response.raise_for_status()
            return response.json()

    async def company_contacts(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        payload = await self.domain_search(domain, limit=limit)
        return list(payload.get("data", {}).get("emails", []) or [])
