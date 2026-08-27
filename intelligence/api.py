from __future__ import annotations

from fastapi import APIRouter

from intelligence.registry import list_sources


router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/health")
async def intelligence_health() -> dict[str, object]:
    return {
        "status": "ok",
        "registered_sources": len(list_sources()),
    }


@router.get("/sources")
async def intelligence_sources() -> dict[str, object]:
    return {"sources": list_sources()}
