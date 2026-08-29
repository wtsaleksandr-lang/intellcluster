from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


CURRENT_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_facilities"
LEGACY_URL = "https://ofmpub.epa.gov/echo/echo_rest_services.get_facilities"
DEFAULT_QCOLUMNS = "3,4,5,6,30,31,33,34,36,38,39,40,41"


def _fixture() -> dict[str, Any] | None:
    raw = os.getenv("EPA_ECHO_FIXTURE_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _money(value: Any) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "")
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class EchoFacility:
    registry_id: str
    name: str
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    major: bool = False
    active: bool = False
    inspections_5y: int = 0
    last_inspection: str = ""
    informal_actions_5y: int = 0
    formal_actions_5y: int = 0
    last_formal_action: str = ""
    penalties_5y: int = 0
    total_penalties: float = 0.0

    @property
    def address(self) -> str:
        return ", ".join(v for v in [self.street, self.city, self.state, self.zip_code] if v)


class EPAEchoClient:
    """Free on-demand EPA ECHO facility/compliance lookup.

    Normal page views never call this client. Results are intended to be cached in
    the canonical company enrichment blob. A fixture path can be supplied for CI.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    async def search_facilities(
        self,
        company_name: str,
        *,
        state: str | None = None,
        city: str | None = None,
        limit: int = 25,
    ) -> list[EchoFacility]:
        fixture = _fixture()
        if fixture is not None:
            payload = fixture
        else:
            params = {
                "output": "JSON",
                "p_fn": company_name,
                "tablelist": "Y",
                "responseset": str(max(1, min(int(limit), 100))),
                "qcolumns": DEFAULT_QCOLUMNS,
            }
            if state:
                params["p_st"] = state.strip().upper()
            if city:
                params["p_ct"] = city.strip()
            payload = None
            last_error: Exception | None = None
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                for endpoint in (CURRENT_URL, LEGACY_URL):
                    try:
                        response = await client.get(endpoint, params=params)
                        response.raise_for_status()
                        candidate = response.json()
                        if isinstance(candidate, dict):
                            payload = candidate
                            break
                    except (httpx.HTTPError, ValueError) as exc:
                        last_error = exc
            if payload is None:
                if last_error:
                    raise last_error
                return []

        results = payload.get("Results") if isinstance(payload, dict) else None
        if not isinstance(results, dict):
            results = payload if isinstance(payload, dict) else {}
        rows = results.get("Facilities") or results.get("facilities") or []
        if isinstance(rows, dict):
            rows = [rows]

        facilities: list[EchoFacility] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            registry_id = str(row.get("RegistryID") or row.get("registry_id") or "").strip()
            name = str(row.get("FacName") or row.get("facility_name") or "").strip()
            if not registry_id or not name:
                continue
            facilities.append(
                EchoFacility(
                    registry_id=registry_id,
                    name=name,
                    street=str(row.get("FacStreet") or "").strip(),
                    city=str(row.get("FacCity") or "").strip(),
                    state=str(row.get("FacState") or "").strip(),
                    zip_code=str(row.get("FacZip") or "").strip(),
                    latitude=_float_or_none(row.get("FacLat")),
                    longitude=_float_or_none(row.get("FacLong") or row.get("FacLongitude")),
                    major=str(row.get("FacMajorFlag") or "").strip().upper() == "Y",
                    active=str(row.get("FacActiveFlag") or "").strip().upper() == "Y",
                    inspections_5y=_int(row.get("FacInspectionCount")),
                    last_inspection=str(row.get("FacDateLastInspection") or row.get("FacDateLastInspectio") or "").strip(),
                    informal_actions_5y=_int(row.get("FacInformalCount")),
                    formal_actions_5y=_int(row.get("FacFormalActionCount")),
                    last_formal_action=str(row.get("FacDateLastFormalAction") or row.get("FacDateLastFormalA") or "").strip(),
                    penalties_5y=_int(row.get("FacPenaltyCount")),
                    total_penalties=_money(row.get("FacTotalPenalties")),
                )
            )
        return facilities


def compact_echo_profile(facilities: list[EchoFacility]) -> dict[str, Any]:
    total_inspections = sum(row.inspections_5y for row in facilities)
    total_formal = sum(row.formal_actions_5y for row in facilities)
    total_informal = sum(row.informal_actions_5y for row in facilities)
    total_penalties = sum(row.total_penalties for row in facilities)
    penalty_events = sum(row.penalties_5y for row in facilities)
    return {
        "facility_count": len(facilities),
        "major_facility_count": sum(1 for row in facilities if row.major),
        "active_facility_count": sum(1 for row in facilities if row.active),
        "inspections_5y": total_inspections,
        "formal_actions_5y": total_formal,
        "informal_actions_5y": total_informal,
        "penalty_events_5y": penalty_events,
        "total_penalties": total_penalties,
        "facilities": [
            {
                "registry_id": row.registry_id,
                "name": row.name,
                "address": row.address,
                "city": row.city,
                "state": row.state,
                "zip": row.zip_code,
                "latitude": row.latitude,
                "longitude": row.longitude,
                "major": row.major,
                "active": row.active,
                "inspections_5y": row.inspections_5y,
                "last_inspection": row.last_inspection,
                "informal_actions_5y": row.informal_actions_5y,
                "formal_actions_5y": row.formal_actions_5y,
                "last_formal_action": row.last_formal_action,
                "penalties_5y": row.penalties_5y,
                "total_penalties": row.total_penalties,
                "echo_url": f"https://echo.epa.gov/detailed-facility-report?fid={row.registry_id}",
            }
            for row in facilities[:25]
        ],
        "source": "EPA ECHO",
    }
