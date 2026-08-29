from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from intelligence.database import connect
from intelligence.enrichment.importyeti import (
    ImportYetiClient,
    ImportYetiMatch,
    compact_profile,
    live_importyeti_enabled,
    load_importyeti_fixture,
)
from intelligence.entity_resolution import normalize_company_name
from intelligence.repository import get_entity_by_slug, set_entity_enrichment
from intelligence.supplier_explorer import sync_supplier_relationships
from shared.admin import require_admin

router = APIRouter(tags=["intelligence-importyeti"])


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


def _choose_match(
    company_name: str,
    matches: list[ImportYetiMatch],
) -> tuple[ImportYetiMatch | None, str]:
    ranked = sorted(
        ((_score_name(company_name, match.title), match) for match in matches),
        key=lambda item: (-item[0], item[1].title.casefold()),
    )
    strong = [item for item in ranked if item[0] >= 0.90]
    if not strong:
        return None, "no_confident_match"
    if len(strong) > 1 and strong[0][0] - strong[1][0] < 0.05:
        return None, "ambiguous"
    return strong[0][1], "matched"


def _marker(status: str, *, fixture: bool, network_attempted: bool) -> dict[str, object]:
    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "source": "importyeti_explicit_acquisition",
        "fixture": fixture,
        "network_attempted": network_attempted,
    }


def _cached_profile(company: dict) -> dict | None:
    profile = company.get("importyeti")
    if isinstance(profile, dict):
        return profile
    enrichment = company.get("enrichment")
    if isinstance(enrichment, dict) and isinstance(enrichment.get("importyeti"), dict):
        return enrichment["importyeti"]
    return None


@router.post("/api/intelligence/company/{slug}/enrich/importyeti")
async def intelligence_company_importyeti_enrichment(
    request: Request,
    slug: str,
    refresh: bool = Query(default=False),
    confirm_paid: bool = Query(default=False),
):
    """Explicitly acquire and cache ImportYeti intelligence.

    Existing cache and deterministic fixtures are cost-free and can be reused without
    admin authorization. Any path capable of making a paid network request requires
    an authenticated IntellCluster admin session *before* checking the paid switches.
    A real acquisition then additionally requires caller confirmation, the process
    master switch, a configured API key, and an explicit live-enabled client.
    """
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if str(company.get("country") or "").upper() != "US":
        raise HTTPException(
            status_code=400,
            detail="ImportYeti company intelligence currently applies to U.S. profiles",
        )

    cached = _cached_profile(company)
    if cached and not refresh:
        return {
            "company": company,
            "lookup": {"importyeti": "cached"},
            "paid_sources_called": False,
            "acquisition": {
                "mode": "cache",
                "request_cost": cached.get("_requestCost"),
                "credits_remaining": cached.get("_creditsRemaining"),
            },
        }

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    previous_lookup = enrichment.get("importyeti_lookup") if isinstance(enrichment, dict) else None
    if not refresh and not cached and isinstance(previous_lookup, dict):
        return {
            "company": company,
            "lookup": {
                "importyeti": str(previous_lookup.get("status") or "previously_checked"),
                "previously_checked": True,
            },
            "paid_sources_called": False,
            "acquisition": {"mode": "cached_lookup"},
        }

    fixture = load_importyeti_fixture()
    fixture_mode = fixture is not None
    if not fixture_mode:
        # Intent confirmation is not authorization. Check the existing signed admin
        # session before creating any network-capable paid client.
        require_admin(request)
        if not confirm_paid:
            return JSONResponse(
                {
                    "detail": (
                        "Paid ImportYeti acquisition requires confirm_paid=true. "
                        "Existing cached intelligence never requires paid confirmation."
                    ),
                    "paid_sources_called": False,
                },
                status_code=409,
            )
        if not live_importyeti_enabled():
            return JSONResponse(
                {
                    "detail": (
                        "Paid ImportYeti acquisition is disabled by the server master switch."
                    ),
                    "paid_sources_called": False,
                },
                status_code=409,
            )
        if not os.getenv("IMPORTYETI_API_KEY"):
            return JSONResponse(
                {
                    "detail": "IMPORTYETI_API_KEY is not configured.",
                    "paid_sources_called": False,
                },
                status_code=503,
            )

    network_attempted = not fixture_mode
    client = ImportYetiClient(allow_live=network_attempted)
    try:
        matches = await client.search_company(str(company.get("name") or ""), page_size=5)
        chosen, status = _choose_match(str(company.get("name") or ""), matches)
        if chosen is None:
            marker = _marker(
                status,
                fixture=fixture_mode,
                network_attempted=network_attempted,
            )
            with connect() as conn:
                set_entity_enrichment(
                    conn,
                    int(company["id"]),
                    "importyeti_lookup",
                    marker,
                )
                refreshed = get_entity_by_slug(conn, slug)
            return {
                "company": refreshed or company,
                "lookup": {"importyeti": status},
                "paid_sources_called": network_attempted,
                "acquisition": {
                    "mode": "fixture" if fixture_mode else "paid_search",
                    "profile_cached": False,
                },
            }

        raw_profile = await client.company_profile(chosen.slug)
        profile = compact_profile(raw_profile)
        profile["_slug"] = chosen.slug
        profile["_matchedTitle"] = chosen.title
        profile["_matchAddress"] = chosen.address
        profile["_acquiredVia"] = (
            "fixture" if fixture_mode else "explicit_paid_importyeti"
        )
        marker = _marker(
            "matched",
            fixture=fixture_mode,
            network_attempted=network_attempted,
        )
        with connect() as conn:
            entity_id = int(company["id"])
            set_entity_enrichment(conn, entity_id, "importyeti", profile)
            set_entity_enrichment(conn, entity_id, "importyeti_lookup", marker)
            sync_supplier_relationships(conn, entity_id, profile)
            refreshed = get_entity_by_slug(conn, slug)
        return {
            "company": refreshed or company,
            "lookup": {"importyeti": "matched"},
            "paid_sources_called": network_attempted,
            "acquisition": {
                "mode": "fixture" if fixture_mode else "explicit_paid",
                "profile_cached": True,
                "request_cost": profile.get("_requestCost"),
                "credits_remaining": profile.get("_creditsRemaining"),
            },
        }
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        marker = _marker(
            "unavailable",
            fixture=fixture_mode,
            network_attempted=network_attempted,
        )
        with connect() as conn:
            set_entity_enrichment(
                conn,
                int(company["id"]),
                "importyeti_lookup",
                marker,
            )
            refreshed = get_entity_by_slug(conn, slug)
        return JSONResponse(
            {
                "company": refreshed or company,
                "lookup": {"importyeti": "unavailable"},
                "detail": str(exc),
                "paid_sources_called": network_attempted,
                "acquisition": {
                    "mode": "fixture" if fixture_mode else "paid_attempt",
                    "profile_cached": False,
                },
            },
            status_code=502,
        )
