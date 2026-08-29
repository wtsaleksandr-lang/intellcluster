from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class USIntelligenceSource:
    key: str
    name: str
    layer: str
    access: str
    cost: str
    cache_policy: str
    status: str


US_SOURCE_ROADMAP = (
    USIntelligenceSource(
        key="importyeti",
        name="ImportYeti",
        layer="trade",
        access="API",
        cost="paid_on_demand",
        cache_policy="cache purchased company/shipment intelligence; no live page-view calls",
        status="implemented_guarded_cache",
    ),
    USIntelligenceSource(
        key="sam_usaspending",
        name="SAM.gov / USASpending",
        layer="contracts",
        access="public_api",
        cost="free",
        cache_policy="on-demand recipient/award enrichment; persist normalized result",
        status="implemented_usaspending",
    ),
    USIntelligenceSource(
        key="fmcsa",
        name="FMCSA",
        layer="fleet",
        access="public_data",
        cost="free",
        cache_policy=(
            "guarded resumable bulk census bootstrap plus conservative mixed-source "
            "resolution and on-demand company lookup"
        ),
        status="implemented_fast_seed_guarded",
    ),
    USIntelligenceSource(
        key="epa_echo",
        name="EPA ECHO",
        layer="facilities_compliance",
        access="public_api",
        cost="free",
        cache_policy="on-demand canonical-company/facility cache; no repeated page-view calls",
        status="implemented_on_demand",
    ),
    USIntelligenceSource(
        key="osha",
        name="OSHA",
        layer="compliance",
        access="public_data",
        cost="free",
        cache_policy="on-demand establishment inspection cache; no repeated page-view calls",
        status="implemented_on_demand",
    ),
    USIntelligenceSource(
        key="sec_edgar",
        name="SEC EDGAR",
        layer="company_financial",
        access="public_api",
        cost="free",
        cache_policy="scheduled identifiers; lazy filing details",
        status="planned",
    ),
    USIntelligenceSource(
        key="uspto",
        name="USPTO",
        layer="patents",
        access="public_data",
        cost="free",
        cache_policy="lazy company-linked intellectual-property cache",
        status="planned",
    ),
)


def source_roadmap() -> list[dict[str, str]]:
    return [
        {
            "key": row.key,
            "name": row.name,
            "layer": row.layer,
            "access": row.access,
            "cost": row.cost,
            "cache_policy": row.cache_policy,
            "status": row.status,
        }
        for row in US_SOURCE_ROADMAP
    ]
