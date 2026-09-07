from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


SEARCH_URL = "https://www.osha.gov/ords/imis/establishment.search"
DOL_INSPECTION_URL = "https://apiprod.dol.gov/v4/get/OSHA/inspection/json"


class OSHASourceUnavailable(RuntimeError):
    """Raised when an official OSHA/DOL transport is temporarily unavailable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _fixture() -> str | None:
    raw = os.getenv("OSHA_FIXTURE_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _dol_api_key() -> str:
    return (
        os.getenv("DOL_API_KEY", "").strip()
        or os.getenv("OSHA_DOL_API_KEY", "").strip()
    )


def _clean_cell(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _date_key(value: str) -> datetime:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], fmt)
        except ValueError:
            continue
    return datetime.min


def _display_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%m/%d/%Y")
    except ValueError:
        return text[:10]


def _int(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


@dataclass(frozen=True)
class OSHAInspection:
    activity: str
    date_opened: str
    rid: str
    state: str
    inspection_type: str
    scope: str
    sic: str
    naics: str
    violations: int
    establishment_name: str
    data_source: str = "OSHA Establishment Search"

    @property
    def detail_url(self) -> str:
        activity = re.sub(r"[^0-9.]", "", self.activity)
        return f"https://www.osha.gov/ords/imis/establishment.inspection_detail?id={activity}"


def _rows_from_html(text: str, limit: int) -> list[OSHAInspection]:
    inspections: list[OSHAInspection] = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = [_clean_cell(cell) for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S)]
        if len(cells) < 9:
            continue
        activity_idx = next((i for i, cell in enumerate(cells) if re.fullmatch(r"\d{5,}(?:\.\d+)?", cell)), None)
        if activity_idx is None:
            continue
        cells = cells[activity_idx:]
        if len(cells) < 9:
            continue
        activity = cells[0]
        date_opened = cells[1] if len(cells) > 1 else ""
        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", date_opened):
            continue
        rid = cells[2] if len(cells) > 2 else ""
        state = cells[3] if len(cells) > 3 else ""
        inspection_type = cells[4] if len(cells) > 4 else ""
        scope = cells[5] if len(cells) > 5 else ""
        sic = cells[6] if len(cells) > 6 else ""
        naics = cells[7] if len(cells) > 7 else ""
        establishment_name = cells[-1]
        violations = _int(cells[-2]) if len(cells) >= 10 else 0
        if not establishment_name or establishment_name.lower() == "establishment name":
            continue
        inspections.append(
            OSHAInspection(
                activity=activity,
                date_opened=date_opened,
                rid=rid,
                state=state,
                inspection_type=inspection_type,
                scope=scope,
                sic=sic,
                naics=naics,
                violations=violations,
                establishment_name=establishment_name,
            )
        )
        if len(inspections) >= limit:
            break
    inspections.sort(key=lambda item: _date_key(item.date_opened), reverse=True)
    return inspections


def _rows_from_dol(payload: Any, *, state: str | None, limit: int) -> list[OSHAInspection]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("results") or []
    else:
        rows = payload if isinstance(payload, list) else []
    if not isinstance(rows, list):
        return []

    expected_state = (state or "").strip().upper()
    inspections: list[OSHAInspection] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_state = str(row.get("site_state") or row.get("state") or "").strip().upper()
        if expected_state and row_state and row_state != expected_state:
            continue
        activity = str(row.get("activity_nr") or row.get("activity") or "").strip()
        establishment = str(row.get("estab_name") or row.get("establishment_name") or "").strip()
        if not activity or not establishment:
            continue
        inspections.append(
            OSHAInspection(
                activity=activity,
                date_opened=_display_date(row.get("open_date") or row.get("date_opened")),
                rid=str(row.get("reporting_id") or row.get("rid") or "").strip(),
                state=row_state,
                inspection_type=str(row.get("insp_type") or row.get("inspection_type") or "").strip(),
                scope=str(row.get("insp_scope") or row.get("scope") or "").strip(),
                sic=str(row.get("sic_code") or row.get("sic") or "").strip(),
                naics=str(row.get("naics_code") or row.get("naics") or "").strip(),
                violations=_int(
                    row.get("violations")
                    or row.get("violation_count")
                    or row.get("violations_count")
                ),
                establishment_name=establishment,
                data_source="DOL Open Data — OSHA Inspection",
            )
        )
        if len(inspections) >= limit:
            break
    inspections.sort(key=lambda item: _date_key(item.date_opened), reverse=True)
    return inspections


class OSHAClient:
    """Free, on-demand OSHA establishment inspection lookup.

    The public OSHA establishment-search HTML endpoint can reject automated
    infrastructure with HTTP 403. When ``DOL_API_KEY`` (or the legacy
    ``OSHA_DOL_API_KEY`` alias) is configured, this client instead uses the
    Department of Labor's official OSHA Inspection API. Without a DOL key it
    retains the public OSHA search as a best-effort fallback and reports source
    blocking distinctly rather than pretending that a blocked lookup means zero
    inspections.

    Normal page views do not call this client; callers cache confident matches.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    async def _search_dol(
        self,
        establishment: str,
        *,
        state: str | None,
        limit: int,
        api_key: str,
    ) -> list[OSHAInspection]:
        # The official v4 DOL API supports filter_object. Query by establishment
        # name and apply state filtering locally so the request stays simple and
        # deterministic across API revisions.
        filter_object = {
            "field": "estab_name",
            "operator": "like",
            "value": f"%{establishment.strip()}%",
        }
        params = {
            "X-API-KEY": api_key,
            "limit": str(max(25, min(max(limit * 3, limit), 500))),
            "sort": "desc",
            "sort_by": "open_date",
            "filter_object": json.dumps(filter_object, separators=(",", ":")),
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "IntellCluster/1.0 public-data enrichment"},
        ) as client:
            response = await client.get(DOL_INSPECTION_URL, params=params)
        if response.status_code in {401, 403}:
            raise OSHASourceUnavailable(
                "The official DOL OSHA Inspection API rejected the configured API key.",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise OSHASourceUnavailable(
                "The official DOL OSHA Inspection API rate limit was reached.",
                status_code=429,
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OSHASourceUnavailable(
                "The official DOL OSHA Inspection API is temporarily unavailable."
            ) from exc
        return _rows_from_dol(payload, state=state, limit=limit)

    async def search(self, establishment: str, *, state: str | None = None, limit: int = 50) -> list[OSHAInspection]:
        fixture = _fixture()
        if fixture is not None:
            return _rows_from_html(fixture, limit)

        bounded_limit = max(1, min(int(limit), 100))
        api_key = _dol_api_key()
        if api_key:
            return await self._search_dol(
                establishment,
                state=state,
                limit=bounded_limit,
                api_key=api_key,
            )

        params = {
            "establishment": establishment,
            "state": (state or "all").strip().upper() if state else "all",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; IntellCluster/1.0; +https://intellcluster.com)",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = await client.get(SEARCH_URL, params=params)
        if response.status_code in {403, 429}:
            raise OSHASourceUnavailable(
                "OSHA's public establishment search blocked automated access; "
                "configure DOL_API_KEY to use the official DOL OSHA Inspection API.",
                status_code=response.status_code,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OSHASourceUnavailable(
                "OSHA's public establishment search is temporarily unavailable."
            ) from exc
        return _rows_from_html(response.text, bounded_limit)


def compact_osha_profile(inspections: list[OSHAInspection]) -> dict[str, Any]:
    naics = sorted({row.naics for row in inspections if row.naics})
    states = sorted({row.state for row in inspections if row.state})
    total_violations = sum(row.violations for row in inspections)
    source = inspections[0].data_source if inspections else "OSHA Public Data"
    return {
        "inspection_count_shown": len(inspections),
        "violations_shown": total_violations,
        "latest_inspection": inspections[0].date_opened if inspections else "",
        "states": states,
        "naics": naics,
        "inspections": [
            {
                "activity": row.activity,
                "date_opened": row.date_opened,
                "rid": row.rid,
                "state": row.state,
                "type": row.inspection_type,
                "scope": row.scope,
                "sic": row.sic,
                "naics": row.naics,
                "violations": row.violations,
                "establishment_name": row.establishment_name,
                "detail_url": row.detail_url,
            }
            for row in inspections[:100]
        ],
        "source": source,
        "coverage_note": (
            "OSHA/DOL public inspection evidence. A missing or source-blocked lookup is not evidence "
            "that an establishment has no OSHA inspections or violations."
        ),
    }
