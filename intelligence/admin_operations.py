from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from intelligence.data_quality import data_quality_report
from intelligence.post_ingest_readiness import post_ingest_readiness
from intelligence.sync_observability import sync_status_snapshot
from shared.admin import require_admin

router = APIRouter(tags=["intelligence-admin"])
templates = Jinja2Templates(directory="intelligence/templates")


@router.get("/admin/intelligence", response_class=HTMLResponse)
async def intelligence_operations_page(
    request: Request,
    _admin: bool = Depends(require_admin),
):
    """Read-only operations console for intelligence ingestion and rollout state."""
    sync = sync_status_snapshot()
    readiness = post_ingest_readiness()
    return templates.TemplateResponse(
        request=request,
        name="intelligence_admin.html",
        context={
            "active": "admin-intelligence",
            "sync": sync,
            "readiness": readiness,
        },
    )


@router.get("/api/intelligence/admin/data-quality")
async def intelligence_admin_data_quality(
    _admin: bool = Depends(require_admin),
) -> dict[str, object]:
    """Run the explicit database-only quality audit.

    This can scan large intelligence tables, so it is intentionally a separate
    administrator-triggered request rather than part of the normal dashboard load.
    It never calls external or paid data sources.
    """
    return data_quality_report()
