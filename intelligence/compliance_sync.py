from __future__ import annotations

import argparse
import asyncio
import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, func, select

from intelligence.database import connect, entities
from intelligence.enrichment.epa_echo import EPAEchoClient, EchoFacility, compact_echo_profile
from intelligence.enrichment.osha import OSHAClient, OSHAInspection, compact_osha_profile
from intelligence.repository import get_entity_enrichment, set_entity_enrichment


def _name_key(value: str) -> str:
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"\b(incorporated|inc|corporation|corp|limited|ltd|llc|company|co|usa)\b", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _similar(left: str, right: str) -> bool:
    a, b = _name_key(left), _name_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    at, bt = set(a.split()), set(b.split())
    overlap = len(at & bt) / max(1, len(at | bt))
    return overlap >= 0.72 or (min(len(a), len(b)) >= 5 and (a in b or b in a))


def _choose_echo(company: dict, matches: list[EchoFacility]) -> list[EchoFacility]:
    state = str(company.get("province") or "").strip().upper()
    city = str(company.get("city") or "").strip().casefold()
    chosen: list[EchoFacility] = []
    for match in matches:
        if not _similar(str(company.get("name") or ""), match.name):
            continue
        if state and match.state and state != match.state.upper():
            continue
        if city and match.city and city == match.city.casefold():
            chosen.insert(0, match)
        else:
            chosen.append(match)
    return chosen[:25]


def _choose_osha(company: dict, matches: list[OSHAInspection]) -> list[OSHAInspection]:
    state = str(company.get("province") or "").strip().upper()
    chosen: list[OSHAInspection] = []
    for match in matches:
        if state and match.state and state != match.state.upper():
            continue
        if _similar(str(company.get("name") or ""), match.establishment_name):
            chosen.append(match)
    return chosen[:100]


def _checked_at(value: object) -> datetime | None:
    if not isinstance(value, dict) or not value.get("checked_at"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _candidates(limit: int, max_age_days: int) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    with connect() as conn:
        rows = conn.execute(
            select(
                entities.c.id,
                entities.c.name,
                entities.c.slug,
                entities.c.country,
                entities.c.region,
                entities.c.city,
            )
            .where(and_(func.upper(entities.c.country) == "US", entities.c.name.is_not(None)))
            .order_by(entities.c.id.asc())
            .limit(max(limit * 5, limit))
        ).mappings().all()
        result: list[dict] = []
        for row in rows:
            enrichment = get_entity_enrichment(conn, int(row["id"]))
            marker = enrichment.get("us_compliance_lookup") if isinstance(enrichment, dict) else None
            checked = _checked_at(marker)
            if checked is not None and checked > cutoff:
                continue
            result.append(
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "slug": row["slug"],
                    "country": row["country"],
                    "province": row["region"],
                    "city": row["city"],
                }
            )
            if len(result) >= limit:
                break
    return result


async def _refresh(company: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    echo_profile = None
    osha_profile = None
    try:
        matches = await EPAEchoClient(timeout=20).search_facilities(
            company["name"], state=company.get("province"), city=company.get("city"), limit=25
        )
        chosen = _choose_echo(company, matches)
        if chosen:
            echo_profile = compact_echo_profile(chosen)
            result["epa_echo"] = "matched"
        else:
            result["epa_echo"] = "no_confident_match"
    except (httpx.HTTPError, RuntimeError, ValueError):
        result["epa_echo"] = "unavailable"

    try:
        inspections = await OSHAClient(timeout=20).search(
            company["name"], state=company.get("province"), limit=100
        )
        chosen_osha = _choose_osha(company, inspections)
        if chosen_osha:
            osha_profile = compact_osha_profile(chosen_osha)
            result["osha"] = "matched"
        else:
            result["osha"] = "no_confident_match"
    except (httpx.HTTPError, RuntimeError, ValueError):
        result["osha"] = "unavailable"

    marker = {
        "checked_at": datetime.now(UTC).isoformat(),
        "epa_echo": result.get("epa_echo", "unknown"),
        "osha": result.get("osha", "unknown"),
        "source": "nightly_free_us_compliance",
    }
    with connect() as conn:
        if echo_profile:
            set_entity_enrichment(conn, company["id"], "epa_echo", echo_profile)
        if osha_profile:
            set_entity_enrichment(conn, company["id"], "osha", osha_profile)
        set_entity_enrichment(conn, company["id"], "us_compliance_lookup", marker)
    return result


async def sync(limit: int = 100, max_age_days: int = 30) -> dict[str, int]:
    companies = _candidates(max(1, limit), max(1, max_age_days))
    stats = {"checked": 0, "epa_matches": 0, "osha_matches": 0, "unavailable": 0}
    for company in companies:
        result = await _refresh(company)
        stats["checked"] += 1
        stats["epa_matches"] += int(result.get("epa_echo") == "matched")
        stats["osha_matches"] += int(result.get("osha") == "matched")
        stats["unavailable"] += int("unavailable" in result.values())
        print(f"[{stats['checked']}/{len(companies)}] {company['name']}: {result}", flush=True)
    print(stats, flush=True)
    return stats


def run() -> int:
    parser = argparse.ArgumentParser(description="Refresh cached EPA ECHO and OSHA evidence for U.S. companies.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(sync(limit=args.limit, max_age_days=args.max_age_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
