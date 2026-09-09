from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select

from intelligence.database import connect, entities, normalize_name


def _prefix_upper_bound(value: str) -> str | None:
    """Return a selective lexical upper bound for normalized ASCII prefixes.

    ``normalize_name`` emits lowercase letters, digits, and spaces. Carry across
    trailing ``z``/``9`` characters so common prefixes remain compatible with
    the existing PostgreSQL B-tree collation instead of relying on a high
    Unicode sentinel that does not sort reliably in production.
    """
    chars = list(value)
    for index in range(len(chars) - 1, -1, -1):
        char = chars[index]
        if "a" <= char < "z":
            chars[index] = chr(ord(char) + 1)
            return "".join(chars[: index + 1])
        if "0" <= char < "9":
            chars[index] = chr(ord(char) + 1)
            return "".join(chars[: index + 1])
        if char in {"z", "9"}:
            continue
        # Normalized trailing spaces are not expected, but if one appears,
        # continue carrying rather than inventing a collation-sensitive bound.
    return None


def _name_rows(conn, normalized: str, limit: int) -> list[dict[str, object]]:
    upper = _prefix_upper_bound(normalized)
    if upper is None:
        # Extremely unusual all-z/all-9 prefixes can safely fall back to exact
        # equality rather than triggering a full-directory LIKE scan.
        predicate = entities.c.name_normalized == normalized
    else:
        predicate = and_(
            entities.c.name_normalized >= normalized,
            entities.c.name_normalized < upper,
        )
    stmt = (
        select(
            entities.c.canonical_name,
            entities.c.slug,
            entities.c.is_importer,
            entities.c.city,
            entities.c.region,
        )
        .where(predicate)
        .order_by(entities.c.name_normalized.asc(), entities.c.canonical_name.asc())
        .limit(limit)
    )
    return [dict(row) for row in conn.execute(stmt).mappings().all()]


def _corporation_rows(conn, term: str, limit: int) -> list[dict[str, object]]:
    """Use the corporation-number index only for numeric-looking input."""
    compact = "".join(ch for ch in term if ch.isdigit())
    if len(compact) < 2 or compact != "".join(ch for ch in term if not ch.isspace()):
        return []
    upper = _prefix_upper_bound(compact)
    if upper is None:
        predicate = entities.c.corporation_number == compact
    else:
        predicate = and_(
            entities.c.corporation_number >= compact,
            entities.c.corporation_number < upper,
        )
    stmt = (
        select(
            entities.c.canonical_name,
            entities.c.slug,
            entities.c.is_importer,
            entities.c.city,
            entities.c.region,
        )
        .where(predicate)
        .order_by(entities.c.corporation_number.asc(), entities.c.canonical_name.asc())
        .limit(limit)
    )
    return [dict(row) for row in conn.execute(stmt).mappings().all()]


def _suggest_rows(term: str, limit: int = 8) -> list[dict[str, object]]:
    normalized = normalize_name(term)
    if len(normalized) < 2:
        return []

    capped = max(1, min(int(limit), 20))
    with connect() as conn:
        rows = _name_rows(conn, normalized, capped)
        if len(rows) < capped:
            seen = {str(row["slug"]) for row in rows}
            for row in _corporation_rows(conn, term.strip(), capped - len(rows)):
                if str(row["slug"]) not in seen:
                    rows.append(row)
                    seen.add(str(row["slug"]))

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
