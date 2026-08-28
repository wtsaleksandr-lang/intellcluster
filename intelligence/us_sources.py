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


US_SOURCE_ROADMAP = (
    USIntelligenceSource(
        key="importyeti",
        name="ImportYeti",
        layer="trade",
        access="API",
        cost="paid_on_demand",
        cache_policy="cache purchased company/shipment intelligence; no live page-view calls",
    ),
    USIntelligenceSource(
        key="sam_usaspending",
        name="SAM.gov / USASpending",
        layer="contracts",
        access="public_api",
        cost="free",
        cache_policy="incremental public-data cache",
    ),
    USIntelligenceSource(
        key="fmcsa",
        name="FMCSA",
        layer="fleet",
        access="public_data",
        cost="free",
        cache_policy="scheduled public-data sync",
    ),
    USIntelligenceSource(
        key="epa_echo",
        name="EPA ECHO",
        layer="facilities_compliance",
        access="public_api",
        cost="free",
        cache_policy="lazy or scheduled cache by canonical company/facility",
    ),
    USIntelligenceSource(
        key="osha",
        name="OSHA",
        layer="compliance",
        access="public_data",
        cost="free",
        cache_policy="scheduled or lazy cache",
    ),
    USIntelligenceSource(
        key="sec_edgar",
        name="SEC EDGAR",
        layer="company_financial",
        access="public_api",
        cost="free",
        cache_policy="scheduled identifiers; lazy filing details",
    ),
    USIntelligenceSource(
        key="uspto",
        name="USPTO",
        layer="patents",
        access="public_data",
        cost="free",
        cache_policy="lazy company-linked intellectual-property cache",
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
        }
        for row in US_SOURCE_ROADMAP
    ]
