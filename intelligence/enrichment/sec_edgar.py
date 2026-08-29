from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from intelligence.entity_resolution import normalize_company_name


TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_CACHE_TTL_SECONDS = 86_400
_TICKER_CACHE: tuple[float, list[dict[str, Any]]] | None = None


@dataclass(frozen=True)
class SECCompanyMatch:
    cik: str
    name: str
    ticker: str | None
    exchange: str | None
    score: float


def _user_agent() -> str:
    return os.getenv(
        "SEC_EDGAR_USER_AGENT",
        "IntellCluster/1.0 contact@intellcluster.com",
    ).strip() or "IntellCluster/1.0 contact@intellcluster.com"


def _fixture() -> dict[str, Any] | None:
    raw = os.getenv("SEC_EDGAR_FIXTURE_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _score_name(query: str, candidate: str) -> float:
    left = normalize_company_name(query)
    right = normalize_company_name(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    containment = 0.92 if len(left) >= 5 and (left in right or right in left) else 0.0
    return max(overlap, containment)


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = payload.get("fields")
    data = payload.get("data")
    if isinstance(fields, list) and isinstance(data, list):
        rows: list[dict[str, Any]] = []
        for values in data:
            if isinstance(values, list):
                rows.append(dict(zip(fields, values, strict=False)))
        return rows

    # Compatibility with company_tickers.json style fixtures.
    rows = []
    for value in payload.values():
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _recent_filings(submissions: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    columns = {
        key: value
        for key, value in recent.items()
        if isinstance(value, list)
    }
    if not columns:
        return []
    size = min(max((len(values) for values in columns.values()), default=0), limit)
    filings: list[dict[str, Any]] = []
    cik_digits = "".join(ch for ch in str(submissions.get("cik") or "") if ch.isdigit())
    cik_plain = str(int(cik_digits)) if cik_digits else ""
    for index in range(size):
        row = {
            key: values[index] if index < len(values) else None
            for key, values in columns.items()
        }
        accession = str(row.get("accessionNumber") or "")
        document = str(row.get("primaryDocument") or "")
        accession_compact = accession.replace("-", "")
        if cik_plain and accession_compact and document:
            row["filing_url"] = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/"
                f"{accession_compact}/{document}"
            )
        filings.append(row)
    return filings


def compact_sec_profile(match: SECCompanyMatch, submissions: dict[str, Any]) -> dict[str, Any]:
    tickers = submissions.get("tickers") if isinstance(submissions.get("tickers"), list) else []
    exchanges = submissions.get("exchanges") if isinstance(submissions.get("exchanges"), list) else []
    recent = _recent_filings(submissions)
    return {
        "cik": match.cik,
        "name": str(submissions.get("name") or match.name),
        "ticker": match.ticker,
        "exchange": match.exchange,
        "tickers": tickers,
        "exchanges": exchanges,
        "sic": submissions.get("sic"),
        "sic_description": submissions.get("sicDescription"),
        "state_of_incorporation": submissions.get("stateOfIncorporation"),
        "fiscal_year_end": submissions.get("fiscalYearEnd"),
        "former_names": submissions.get("formerNames") if isinstance(submissions.get("formerNames"), list) else [],
        "filing_count_shown": len(recent),
        "latest_filing_date": recent[0].get("filingDate") if recent else None,
        "latest_filing_form": recent[0].get("form") if recent else None,
        "recent_filings": recent,
        "source": "SEC EDGAR",
        "source_url": f"https://www.sec.gov/edgar/browse/?CIK={match.cik}",
        "coverage_note": "Ticker-associated SEC filers; a missing match does not prove the company has no SEC filings.",
    }


class SECEDGARClient:
    """Free, keyless SEC EDGAR company/submission lookup with in-process caching."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": _user_agent(),
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }

    async def _ticker_rows(self) -> list[dict[str, Any]]:
        fixture = _fixture()
        if fixture is not None:
            ticker_payload = fixture.get("tickers")
            if isinstance(ticker_payload, dict):
                return _rows_from_payload(ticker_payload)
            return []

        global _TICKER_CACHE
        now = time.monotonic()
        if _TICKER_CACHE and _TICKER_CACHE[0] > now:
            return _TICKER_CACHE[1]

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        ) as client:
            response = await client.get(TICKERS_URL)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SEC ticker mapping returned an unexpected payload")
        rows = _rows_from_payload(payload)
        _TICKER_CACHE = (now + _CACHE_TTL_SECONDS, rows)
        return rows

    async def search(self, query: str, *, limit: int = 10) -> list[SECCompanyMatch]:
        query = query.strip()
        if not query:
            return []
        matches: list[SECCompanyMatch] = []
        for row in await self._ticker_rows():
            name = str(row.get("name") or row.get("title") or "").strip()
            if not name:
                continue
            score = _score_name(query, name)
            if score < 0.72:
                continue
            raw_cik = row.get("cik") if row.get("cik") is not None else row.get("cik_str")
            digits = "".join(ch for ch in str(raw_cik or "") if ch.isdigit())
            if not digits:
                continue
            matches.append(
                SECCompanyMatch(
                    cik=digits.zfill(10),
                    name=name,
                    ticker=str(row.get("ticker") or "").strip() or None,
                    exchange=str(row.get("exchange") or "").strip() or None,
                    score=score,
                )
            )
        matches.sort(key=lambda item: (-item.score, item.name.casefold(), item.cik))
        return matches[: max(1, min(int(limit), 25))]

    async def submissions(self, cik: str) -> dict[str, Any]:
        digits = "".join(ch for ch in str(cik) if ch.isdigit()).zfill(10)
        if not digits.strip("0"):
            raise ValueError("A valid SEC CIK is required")

        fixture = _fixture()
        if fixture is not None:
            payload = fixture.get("submissions")
            if not isinstance(payload, dict):
                raise ValueError("SEC fixture is missing submissions")
            return payload

        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            follow_redirects=True,
        ) as client:
            response = await client.get(SUBMISSIONS_URL.format(cik=digits))
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SEC submissions returned an unexpected payload")
        return payload

    async def company_profile(self, query: str) -> dict[str, Any] | None:
        matches = await self.search(query, limit=5)
        if len(matches) != 1:
            return None
        match = matches[0]
        submissions = await self.submissions(match.cik)
        return compact_sec_profile(match, submissions)
