from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter
from fastapi.responses import Response

from intelligence.database import connect
from intelligence.repository import get_entity_by_slug

router = APIRouter(tags=["intelligence-canadabuys-export"])


def _cell(value: object) -> str:
    return "" if value is None else str(value)


@router.get("/data/company/{slug}/canadabuys-contracts.csv")
async def intelligence_company_canadabuys_export(slug: str) -> Response:
    """Export cached CanadaBuys contract evidence without a network request."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return Response("Company not found", status_code=404, media_type="text/plain")

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    contracts = (
        enrichment.get("canadabuys_contracts")
        if isinstance(enrichment.get("canadabuys_contracts"), dict)
        else None
    )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "section",
        "contract_number",
        "reference_number",
        "award_date",
        "title",
        "contracting_entity",
        "value",
        "currency",
        "status",
        "instrument_type",
        "unspsc",
        "source_url",
    ])
    if contracts:
        writer.writerow([
            "summary",
            "",
            "",
            "",
            _cell(company.get("name")),
            "",
            _cell(contracts.get("cad_value_shown")),
            "CAD",
            f"unique_contracts={int(contracts.get('contract_count') or 0)}",
            "",
            "",
            _cell(contracts.get("source_url")),
        ])
        for row in contracts.get("contracts") or []:
            if not isinstance(row, dict):
                continue
            writer.writerow([
                "contract",
                _cell(row.get("contract_number")),
                _cell(row.get("reference_number")),
                _cell(row.get("award_date")),
                _cell(row.get("title")),
                _cell(row.get("contracting_entity")),
                _cell(row.get("value")),
                _cell(row.get("currency")),
                _cell(row.get("status")),
                _cell(row.get("instrument_type")),
                _cell(row.get("unspsc")),
                _cell(contracts.get("source_url")),
            ])
    else:
        writer.writerow([
            "status",
            "",
            "",
            "",
            _cell(company.get("name")),
            "",
            "",
            "",
            "No cached CanadaBuys contract evidence is attached to this company.",
            "",
            "",
            "",
        ])

    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(company.get("name") or slug)).strip("-")[:100] or "company"
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-canadabuys-contracts.csv"'},
    )
