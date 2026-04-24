"""
Citation validity judge (deterministic).

Checks that every citation id used anywhere in the structured report
points into the retrieved source list. Also flags key findings that
claim specific facts without any citation — unless they are properly
prefixed with "(model reasoning — unverified):".

PASS  — all citations valid AND every factual finding either has a
        citation or the unverified prefix
WARN  — all citations valid but >= 1 factual finding unsupported
FAIL  — any invented / out-of-range citation id (this is the bug we
        built the whole citation-sanitisation layer to prevent)
SKIP  — no structured report was produced (handled upstream; should not
        normally happen)
"""

from __future__ import annotations

import re

from evals.judges.base import JudgeResult, JudgeVerdict


name = "citation_validity"


# Claims are considered "factual" when they reference numbers, dates,
# percentages, or look like specific claims a user would want verified.
_FACTUAL_MARKERS = re.compile(
    r"(\b\d[\d,.]*\s?(%|percent|x|USD|\$|€|£))"
    r"|(\b20\d{2}\b)"
    r"|(\bQ[1-4]\b)"
    r"|(\b\d+\s?(?:million|billion|thousand|k|M|B)\b)",
    re.IGNORECASE,
)

UNVERIFIED_PREFIX = "(model reasoning — unverified)"


async def judge(record: dict) -> JudgeResult:
    report = record.get("report") or {}
    sources = record.get("sources") or []
    valid_ids = {
        int(s["id"]) for s in sources
        if isinstance(s, dict) and isinstance(s.get("id"), int)
    }

    if not report:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.SKIP,
            score=0.0,
            note="no structured report in record",
        )

    invented = []
    total_cites = 0

    def _collect(cites: list, context: str) -> None:
        nonlocal total_cites
        for c in cites or []:
            try:
                cid = int(c)
            except (TypeError, ValueError):
                continue
            total_cites += 1
            if valid_ids and cid not in valid_ids:
                invented.append({"citation": cid, "where": context})

    for f in report.get("key_findings") or []:
        _collect(f.get("citations"), "key_findings")
    for r in report.get("evidence_table") or []:
        _collect(r.get("citations"), "evidence_table")
    for c in report.get("contradictions") or []:
        _collect(c.get("citations_a"), "contradictions.side_a")
        _collect(c.get("citations_b"), "contradictions.side_b")

    # Factual findings without any citation AND without unverified prefix.
    unsupported_factual: list[str] = []
    for f in report.get("key_findings") or []:
        text = (f.get("finding") or "").strip()
        if not text:
            continue
        if text.lower().startswith(UNVERIFIED_PREFIX.lower()):
            continue
        if f.get("citations"):
            continue
        if _FACTUAL_MARKERS.search(text):
            unsupported_factual.append(text[:140])

    if invented:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.FAIL,
            score=0.0,
            note=f"{len(invented)} invented citation(s) — sanitiser should have caught this",
            details={
                "invented": invented,
                "valid_ids": sorted(valid_ids),
                "total_cites": total_cites,
            },
        )

    if unsupported_factual:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.WARN,
            score=0.7,
            note=f"{len(unsupported_factual)} factual finding(s) lack citations and unverified prefix",
            details={
                "unsupported_factual": unsupported_factual,
                "total_cites": total_cites,
            },
        )

    return JudgeResult(
        judge=name,
        verdict=JudgeVerdict.PASS,
        score=1.0,
        note=f"{total_cites} citations, all valid" if total_cites else "no citations to validate",
        details={"total_cites": total_cites},
    )
