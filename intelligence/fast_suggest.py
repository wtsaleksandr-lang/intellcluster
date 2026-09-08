from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select

from intelligence.database import connect, entities, normalize_name


def _suggest_rows(term: str, limit: int = 8) -> list[dict[str, object]]:
    normalized = normalize_name(term)
    if len(normalized) < 2:
        return []

    # Use the existing B-tree on name_normalized as a prefix range instead of
    # running the full cross-dataset search (products/suppliers/HS) on every
    # autocomplete keystroke. Corporation number remains a second indexed path.
    name_prefix = and_(
        entities.c.name_normalized >= normalized,
        entities.c.name_normalized < f"{normalized}\uffff",
    )
    corporation_prefix = entities.c.corporation_number.like(f"{term.strip()}%")
    stmt = (
        select(
            entities.c.canonical_name,
            entities.c.slug,
            entities.c.is_importer,
            entities.c.city,
            entities.c.region,
        )
        .where(or_(name_prefix, corporation_prefix))
        .order_by(entities.c.name_normalized.asc(), entities.c.canonical_name.asc())
        .limit(max(1, min(int(limit), 20)))
    )
    with connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    return [
        {
            "name": str(row["canonical_name"]),
            "slug": str(row["slug"]),
            "kind": "Importer" if row["is_importer"] else "Company",
            "location": ", ".join(
                value for value in [str(row["city"] or ""), str(row["region"] or "")] if value
            ),
            "hs_codes": [],
        }
        for row in rows
    ]


def install_fast_suggest(app) -> None:
    """Intercept /data/suggest with an indexed, name-first autocomplete path."""
    if getattr(app.state, "intellcluster_fast_suggest_installed", False):
        return
    app.state.intellcluster_fast_suggest_installed = True

    @app.middleware("http")
    async def fast_suggest(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/data/suggest":
            term = str(request.query_params.get("q") or "").strip()[:120]
            if len(term) < 2:
                return JSONResponse({"items": []})
            try:
                return JSONResponse({"items": _suggest_rows(term)})
            except Exception as exc:  # noqa: BLE001 - autocomplete must fail soft
                print(f"[fast-suggest] fallback after error: {exc}", flush=True)
                return JSONResponse({"items": []})
        return await call_next(request)
