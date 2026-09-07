from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter
from fastapi.responses import Response

from intelligence.database import connect
from intelligence.repository import get_entity_by_slug

router = APIRouter(tags=["intelligence-uspto-export"])


def _cell(value: object) -> str:
    return "" if value is None else str(value)


@router.get("/data/company/{slug}/uspto-patents.csv")
async def intelligence_company_uspto_export(slug: str) -> Response:
    """Export cached USPTO PatentsView evidence; never contacts USPTO."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return Response("Company not found", status_code=404, media_type="text/plain")

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    patents = enrichment.get("uspto_patents") if isinstance(enrichment.get("uspto_patents"), dict) else None

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "patent_id", "grant_date", "title", "cpc_section", "detail", "source_url"])
    if patents:
        writer.writerow([
            "summary",
            "",
            _cell(patents.get("latest_grant_date")),
            _cell(company.get("name")),
            "",
            f"total_patents={int(patents.get('total_patents') or 0)} | matched_assignee={_cell(patents.get('matched_assignee'))}",
            _cell(patents.get("source_url")),
        ])
        for row in patents.get("patents") or []:
            if not isinstance(row, dict):
                continue
            writer.writerow([
                "patent",
                _cell(row.get("patent_id")),
                _cell(row.get("grant_date")),
                _cell(row.get("title")),
                _cell(row.get("cpc_section")),
                "USPTO PatentsView cached bulk evidence",
                _cell(patents.get("source_url")),
            ])
    else:
        writer.writerow([
            "status",
            "",
            "",
            _cell(company.get("name")),
            "",
            "No cached USPTO PatentsView evidence is attached to this company.",
            "",
        ])

    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(company.get("name") or slug)).strip("-")[:100] or "company"
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-uspto-patents.csv"'},
    )
