from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter
from fastapi.responses import Response

from intelligence.database import connect
from intelligence.repository import get_entity_by_slug


router = APIRouter(tags=["intelligence-sec-export"])


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " | ".join(str(item) for item in value)
    return str(value)


@router.get("/data/company/{slug}/sec-edgar.csv")
async def intelligence_company_sec_export(slug: str) -> Response:
    """Export cached SEC EDGAR evidence without making a live SEC request."""
    with connect() as conn:
        company = get_entity_by_slug(conn, slug)
    if company is None:
        return Response("Company not found", status_code=404, media_type="text/plain")

    enrichment = company.get("enrichment") if isinstance(company.get("enrichment"), dict) else {}
    sec = enrichment.get("sec_edgar") if isinstance(enrichment.get("sec_edgar"), dict) else None
    lookup = enrichment.get("sec_edgar_lookup") if isinstance(enrichment.get("sec_edgar_lookup"), dict) else None

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["section", "field", "value", "detail", "source_url"])
    writer.writerow(["company", "name", _cell(company.get("name")), "", ""])
    writer.writerow(["company", "country", _cell(company.get("country")), "", ""])

    if sec:
        for field in (
            "cik",
            "name",
            "ticker",
            "exchange",
            "tickers",
            "exchanges",
            "sic",
            "sic_description",
            "state_of_incorporation",
            "fiscal_year_end",
            "latest_filing_date",
            "latest_filing_form",
            "filing_count_shown",
        ):
            writer.writerow([
                "sec_summary",
                field,
                _cell(sec.get(field)),
                "SEC EDGAR",
                _cell(sec.get("source_url")),
            ])
        for filing in (sec.get("recent_filings") or [])[:100]:
            if not isinstance(filing, dict):
                continue
            detail = " | ".join(
                part
                for part in (
                    f"report_date={filing.get('reportDate')}" if filing.get("reportDate") else "",
                    f"accession={filing.get('accessionNumber')}" if filing.get("accessionNumber") else "",
                    f"document={filing.get('primaryDocument')}" if filing.get("primaryDocument") else "",
                    f"description={filing.get('primaryDocDescription')}" if filing.get("primaryDocDescription") else "",
                )
                if part
            )
            writer.writerow([
                "sec_filing",
                _cell(filing.get("form")),
                _cell(filing.get("filingDate")),
                detail,
                _cell(filing.get("filing_url")),
            ])
    elif lookup:
        writer.writerow([
            "sec_lookup",
            "status",
            _cell(lookup.get("status")),
            _cell(lookup.get("checked_at")),
            "",
        ])
    else:
        writer.writerow([
            "sec_lookup",
            "status",
            "not_checked",
            "No cached SEC EDGAR lookup has been performed for this profile.",
            "",
        ])

    safe_name = re.sub(
        r"[^a-zA-Z0-9._-]+",
        "-",
        str(company.get("name") or slug),
    ).strip("-")[:100] or "company"
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}-sec-edgar.csv"'
    }
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )
