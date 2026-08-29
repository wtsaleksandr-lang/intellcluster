from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException

from intelligence.database import connect
from intelligence.enrichment.sec_edgar import SECEDGARClient, compact_sec_profile
from intelligence.repository import get_entity_by_slug, set_entity_enrichment


router = APIRouter(tags=["intelligence-sec-edgar"])


def _recent_marker(marker: object) -> bool:
    if not isinstance(marker, dict) or not marker.get("checked_at"):
        return False
    try:
        checked = datetime.fromisoformat(str(marker["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    max_age = timedelta(days=1 if marker.get("status") == "unavailable" else 30)
    return datetime.now(UTC) - checked <= max_age


def _marker(status: str) -> dict[str, str]:
    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "source": "sec_edgar_free_lookup",
    }


@router.post("/api/intelligence/company/{slug}/enrich/sec-edgar")
async def intelligence_company_sec_edgar_enrichment(slug: str) -> dict[str, object]:
    """Cache a conservative SEC EDGAR public-company match without paid data calls."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if str(company.get("country") or "").upper() != "US":
        raise HTTPException(
            status_code=400,
            detail="SEC EDGAR enrichment currently applies to U.S. companies",
        )

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    cached = enrichment.get("sec_edgar") if isinstance(enrichment, dict) else None
    if isinstance(cached, dict):
        return {
            "company": company,
            "lookup": {"sec_edgar": "cached"},
            "paid_sources_called": False,
        }

    previous_lookup = enrichment.get("sec_edgar_lookup") if isinstance(enrichment, dict) else None
    if _recent_marker(previous_lookup):
        return {
            "company": company,
            "lookup": {
                "sec_edgar": str(previous_lookup.get("status") or "recently_checked"),
                "recently_checked": True,
            },
            "paid_sources_called": False,
        }

    try:
        client = SECEDGARClient(timeout=20)
        matches = await client.search(str(company.get("name") or ""), limit=5)
        strong = [match for match in matches if match.score >= 0.90]
        if len(strong) != 1:
            status = "ambiguous" if len(strong) > 1 else "no_confident_match"
            with connect() as conn:
                set_entity_enrichment(conn, int(company["id"]), "sec_edgar_lookup", _marker(status))
                refreshed = get_entity_by_slug(conn, slug)
            return {
                "company": refreshed or company,
                "lookup": {"sec_edgar": status},
                "paid_sources_called": False,
            }
        match = strong[0]
        submissions = await client.submissions(match.cik)
        profile = compact_sec_profile(match, submissions)
        with connect() as conn:
            set_entity_enrichment(conn, int(company["id"]), "sec_edgar", profile)
            set_entity_enrichment(conn, int(company["id"]), "sec_edgar_lookup", _marker("matched"))
            refreshed = get_entity_by_slug(conn, slug)
        return {
            "company": refreshed or company,
            "lookup": {"sec_edgar": "matched"},
            "paid_sources_called": False,
        }
    except (httpx.HTTPError, RuntimeError, ValueError):
        with connect() as conn:
            set_entity_enrichment(conn, int(company["id"]), "sec_edgar_lookup", _marker("unavailable"))
            refreshed = get_entity_by_slug(conn, slug)
        return {
            "company": refreshed or company,
            "lookup": {"sec_edgar": "unavailable"},
            "paid_sources_called": False,
        }
