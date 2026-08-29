from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter
from fastapi.responses import Response

from intelligence.database import connect
from intelligence.repository import get_entity_by_slug

router = APIRouter(tags=["intelligence-compliance-export"])


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    return str(value)


@router.get("/data/company/{slug}/compliance.csv")
async def intelligence_company_compliance_export(slug: str) -> Response:
    """Export cached EPA ECHO and OSHA evidence without making live API calls."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return Response("Company not found", status_code=404, media_type="text/plain")

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    echo = enrichment.get("epa_echo") if isinstance(enrichment.get("epa_echo"), dict) else None
    osha = enrichment.get("osha") if isinstance(enrichment.get("osha"), dict) else None

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "field", "value", "detail", "source_url"])
    writer.writerow(["company", "name", _cell(company.get("name")), "", ""])
    writer.writerow(["company", "country", _cell(company.get("country")), "", ""])
    writer.writerow(["company", "location", _cell(", ".join(x for x in [company.get("city"), company.get("province")] if x)), "", ""])

    if echo:
        for field in (
            "facility_count",
            "major_facility_count",
            "active_facility_count",
            "inspections_5y",
            "formal_actions_5y",
            "informal_actions_5y",
            "penalty_events_5y",
            "total_penalties",
        ):
            writer.writerow(["epa_summary", field, _cell(echo.get(field)), "EPA ECHO", ""])
        for facility in (echo.get("facilities") or [])[:100]:
            if not isinstance(facility, dict):
                continue
            location = ", ".join(
                str(value).strip()
                for value in (facility.get("address"), facility.get("city"), facility.get("state"), facility.get("postal_code"))
                if value
            )
            detail = " | ".join(
                part
                for part in (
                    f"major={facility.get('major_facility')}" if facility.get("major_facility") is not None else "",
                    f"active={facility.get('active')}" if facility.get("active") is not None else "",
                    f"inspections_5y={facility.get('inspections_5y')}" if facility.get("inspections_5y") is not None else "",
                    f"penalties={facility.get('total_penalties')}" if facility.get("total_penalties") is not None else "",
                )
                if part
            )
            writer.writerow([
                "epa_facility",
                _cell(facility.get("registry_id")),
                _cell(facility.get("name")),
                _cell(location or detail),
                _cell(facility.get("detail_url") or facility.get("source_url")),
            ])

    if osha:
        for field in ("inspection_count_shown", "violations_shown", "latest_inspection", "states", "naics"):
            writer.writerow(["osha_summary", field, _cell(osha.get(field)), "OSHA Establishment Search", ""])
        for inspection in (osha.get("inspections") or [])[:100]:
            if not isinstance(inspection, dict):
                continue
            detail = " | ".join(
                part
                for part in (
                    f"opened={inspection.get('date_opened')}" if inspection.get("date_opened") else "",
                    f"state={inspection.get('state')}" if inspection.get("state") else "",
                    f"type={inspection.get('type')}" if inspection.get("type") else "",
                    f"scope={inspection.get('scope')}" if inspection.get("scope") else "",
                    f"NAICS={inspection.get('naics')}" if inspection.get("naics") else "",
                    f"violations={inspection.get('violations')}" if inspection.get("violations") is not None else "",
                )
                if part
            )
            writer.writerow([
                "osha_inspection",
                _cell(inspection.get("activity")),
                _cell(inspection.get("establishment_name")),
                detail,
                _cell(inspection.get("detail_url")),
            ])

    if not echo and not osha:
        writer.writerow(["compliance", "status", "no_cached_evidence", "No cached EPA ECHO or OSHA evidence is available for this profile.", ""])

    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(company.get("name") or slug)).strip("-")[:100] or "company"
    headers = {"Content-Disposition": f'attachment; filename="{safe_name}-compliance.csv"'}
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
