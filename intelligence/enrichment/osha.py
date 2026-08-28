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


def _fixture() -> str | None:
    raw = os.getenv("OSHA_FIXTURE_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _clean_cell(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _date_key(value: str) -> datetime:
    try:
        return datetime.strptime(value[:10], "%m/%d/%Y")
    except ValueError:
        return datetime.min


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
        # OSHA currently displays Violations before Establishment Name. Some rows
        # omit a violation value, so use the final cell as the establishment.
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


class OSHAClient:
    """Free, on-demand OSHA establishment inspection lookup.

    OSHA's public establishment search is HTML rather than a documented JSON API.
    This parser intentionally extracts only stable result-table fields and caches
    the compact result upstream so ordinary profile views do not repeatedly query
    OSHA.
    """

    def __init__(self, *, timeout: float = 45.0) -> None:
        self.timeout = timeout

    async def search(self, establishment: str, *, state: str | None = None, limit: int = 50) -> list[OSHAInspection]:
        fixture = _fixture()
        if fixture is not None:
            return _rows_from_html(fixture, limit)
        params = {
            "establishment": establishment,
            "state": (state or "all").strip().upper() if state else "all",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": "IntellCluster/1.0 public-data enrichment"},
        ) as client:
            response = await client.get(SEARCH_URL, params=params)
            response.raise_for_status()
        return _rows_from_html(response.text, max(1, min(int(limit), 100)))


def compact_osha_profile(inspections: list[OSHAInspection]) -> dict[str, Any]:
    naics = sorted({row.naics for row in inspections if row.naics})
    states = sorted({row.state for row in inspections if row.state})
    total_violations = sum(row.violations for row in inspections)
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
        "source": "OSHA Establishment Search",
    }
