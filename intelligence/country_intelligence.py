from __future__ import annotations

from typing import Any


COUNTRY_MARKETS: dict[str, dict[str, Any]] = {
    "CA": {
        "code": "CA",
        "name": "Canada",
        "flag": "🇨🇦",
        "primary_registry": "Corporations Canada",
        "trade_mode": "category_market_context",
    },
    "US": {
        "code": "US",
        "name": "United States",
        "flag": "🇺🇸",
        "primary_registry": "U.S. public records",
        "trade_mode": "shipment_level",
    },
}


PROFILE_SECTION_ORDER = (
    "overview",
    "trade",
    "suppliers",
    "products",
    "geography",
    "relationships",
    "facilities",
    "compliance",
    "contracts",
    "fleet",
    "patents",
    "contacts",
)


def normalize_country(value: str | None) -> str:
    text = (value or "").strip().upper()
    aliases = {
        "CANADA": "CA",
        "CAN": "CA",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
        "USA": "US",
    }
    return aliases.get(text, text or "CA")


def _state(
    status: str,
    *,
    label: str,
    source: str | None = None,
    message: str | None = None,
) -> dict[str, str | None]:
    return {"status": status, "label": label, "source": source, "message": message}


def profile_capabilities(company: dict[str, Any] | None = None, *, country: str | None = None) -> dict[str, Any]:
    """Describe which universal profile modules have evidence for a company.

    The layout remains stable across countries. A module's state describes the
    evidence level instead of pretending an unavailable dataset equals zero.
    """
    company = company or {}
    code = normalize_country(country or str(company.get("country") or ""))
    market = COUNTRY_MARKETS.get(code, {"code": code, "name": code, "flag": "", "trade_mode": "unknown"})
    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    importyeti = company.get("importyeti") if isinstance(company.get("importyeti"), dict) else None
    if importyeti is None and isinstance(enrichment, dict) and isinstance(enrichment.get("importyeti"), dict):
        importyeti = enrichment["importyeti"]

    is_importer = bool(company.get("is_importer") or company.get("kind") == "Importer")
    hs_codes = company.get("hs_codes") or []
    origins = company.get("origins") or []

    sections: dict[str, dict[str, str | None]] = {
        "overview": _state("available", label="Overview", source="canonical entity graph"),
        "products": _state(
            "available" if hs_codes else "pending",
            label="Products",
            source="public trade/product evidence" if hs_codes else None,
        ),
        "geography": _state(
            "available" if origins or company.get("city") or company.get("province") else "pending",
            label="Geography",
            source="public records",
        ),
        "relationships": _state("pending", label="Relationships"),
        "facilities": _state("planned", label="Facilities"),
        "compliance": _state("planned", label="Compliance"),
        "contracts": _state("planned", label="Contracts"),
        "fleet": _state("planned", label="Fleet"),
        "patents": _state("planned", label="Patents"),
        "contacts": _state("on_demand", label="Contacts", source="cached web/Hunter enrichment"),
    }

    if code == "US":
        if importyeti:
            sections["trade"] = _state("cached", label="Trade", source="ImportYeti API cache")
            sections["suppliers"] = _state("cached", label="Suppliers", source="ImportYeti API cache")
        else:
            sections["trade"] = _state(
                "unlockable",
                label="Trade",
                source="ImportYeti API",
                message="Shipment intelligence has not been cached for this company yet.",
            )
            sections["suppliers"] = _state(
                "unlockable",
                label="Suppliers",
                source="ImportYeti API",
                message="Supplier shipment intelligence has not been cached for this company yet.",
            )
        sections["facilities"] = _state("planned", label="Facilities", source="EPA ECHO / public records")
        sections["compliance"] = _state("planned", label="Compliance", source="OSHA / EPA")
        sections["contracts"] = _state("planned", label="Contracts", source="USASpending / SAM.gov")
        sections["fleet"] = _state("planned", label="Fleet", source="FMCSA")
        sections["patents"] = _state("planned", label="Patents", source="USPTO")
    elif code == "CA":
        if importyeti:
            sections["trade"] = _state("cached", label="Trade", source="cached shipment intelligence")
            sections["suppliers"] = _state("cached", label="Suppliers", source="cached shipment intelligence")
        else:
            sections["trade"] = _state(
                "market_context" if is_importer or hs_codes else "not_available",
                label="Trade",
                source="Canadian Importers + Statistics Canada market context" if is_importer or hs_codes else None,
                message=(
                    "Company-level Canadian shipment records are not currently available; market-level trade context is shown instead."
                    if is_importer or hs_codes
                    else "Company-level Canadian shipment intelligence is not currently available."
                ),
            )
            sections["suppliers"] = _state(
                "not_available",
                label="Suppliers",
                message="Company-level supplier shipment records are not currently available from Canadian public sources.",
            )
        sections["contracts"] = _state("planned", label="Contracts", source="CanadaBuys / public procurement")
        sections["patents"] = _state("planned", label="Patents", source="CIPO / public records")

    return {
        "country": market,
        "section_order": list(PROFILE_SECTION_ORDER),
        "sections": sections,
    }
