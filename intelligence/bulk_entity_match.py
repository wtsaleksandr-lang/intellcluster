from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from intelligence.database import entities


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    step = max(1, size)
    for start in range(0, len(values), step):
        yield values[start : start + step]


def resolve_unique_entities(
    conn: Connection,
    normalized_names: Iterable[str],
    *,
    country_hints: dict[str, str | None] | None = None,
    batch_size: int = 2_000,
) -> dict[str, int]:
    """Resolve exact normalized names in bounded SQL batches.

    A name is returned only when exactly one canonical entity survives the
    optional country hint. Duplicate names are intentionally omitted rather than
    guessed. This is designed for large local bulk datasets: it avoids one SQL
    query per supplier/assignee and never loads canonical entities unrelated to
    names present in the source file.
    """
    names = sorted({name for name in normalized_names if name})
    result: dict[str, int] = {}
    hints = country_hints or {}

    for chunk in _chunks(names, batch_size):
        rows = conn.execute(
            select(
                entities.c.id,
                entities.c.name_normalized,
                entities.c.country,
            ).where(entities.c.name_normalized.in_(chunk))
        ).mappings().all()
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[str(row["name_normalized"] or "")].append(dict(row))

        for name in chunk:
            candidates = grouped.get(name, [])
            hint = str(hints.get(name) or "").upper()
            if hint:
                candidates = [
                    candidate
                    for candidate in candidates
                    if str(candidate.get("country") or "").upper() == hint
                ]
            if len(candidates) == 1:
                result[name] = int(candidates[0]["id"])

    return result
