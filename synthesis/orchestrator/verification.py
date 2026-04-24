"""
Per-claim verification pass.

After the Decision-Maker produces its structured report, this module
asks a cheap model to check whether each evidence-table claim is
actually supported by its cited source snippets. Results are attached
to EvidenceRow.verification in place.

Why it exists
-------------
Citation-sanitisation (in report_schema.parse_structured_report) can
only guarantee that every [N] points into the retrieved source list —
not that the SNIPPET at source [N] actually backs the claim. A model
can cite a source that mentions a tangentially-related fact. This pass
catches that bug at production-time, and surfaces it to the user as a
verification chip next to the evidence row.

Cost
----
Uses the cost_efficient tier (Haiku / Gemini Flash). Up to MAX_CLAIMS
claims per run. At ~$0.001 per call × 6 claims = ~$0.006 per run. Cheap
enough to run unconditionally when retrieval is configured.

Never raises. Network or model failures leave `verification` as None
for the affected rows; the UI renders them without a chip.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from synthesis.orchestrator.providers import call_with_role_fallback
from synthesis.orchestrator.types import EvidenceRow, RetrievedSource, StructuredReport


MAX_CLAIMS = 6
CONCURRENCY = 3


SYSTEM_PROMPT = """You are a factuality auditor.

Given a CLAIM and the SNIPPETS that support it, decide whether the
snippets back the claim.

Rules:
- Use ONLY the snippets. Do not use outside knowledge.
- "supported"   — the snippets contain enough concrete detail to back the claim.
- "partial"     — the snippets mention the topic but don't fully confirm the claim.
- "unsupported" — the snippets don't back the claim (even if it might be true elsewhere).
- When in doubt choose "partial". Err strict.

Respond with one JSON object, no prose, no markdown:
{"verdict": "supported" | "partial" | "unsupported",
 "reason": "<one short sentence>"}"""


USER_TEMPLATE = """CLAIM:
{claim}

SNIPPETS:
{snippets}

Verdict?"""


CallFn = Callable[[str, str], Awaitable[tuple[str, str]]]


async def _default_call_fn(prompt: str, system: str) -> tuple[str, str]:
    """Default production caller — cost_efficient tier, strategist role."""
    result, provider = await call_with_role_fallback(
        role="strategist",
        prompt=prompt,
        system=system,
        tier="cost_efficient",
    )
    return (result.response_content or ""), provider


def _build_snippets(citations: list[int], sources: list[RetrievedSource]) -> str:
    by_id = {s.id: s for s in sources}
    parts = []
    for cid in citations or []:
        try:
            sid = int(cid)
        except (TypeError, ValueError):
            continue
        src = by_id.get(sid)
        if not src:
            continue
        body = (src.full_content or src.snippet or "").strip()
        if not body:
            continue
        parts.append(f"[{sid}] {src.title} ({src.domain})\n{body[:1200]}")
    return "\n\n".join(parts) if parts else "(no snippets available)"


def _parse_verdict(raw: str) -> str:
    """Return 'supported' / 'partial' / 'unsupported' or '' on parse failure."""
    if not raw:
        return ""
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return ""
    try:
        data = json.loads(m.group())
    except Exception:
        return ""
    v = (data.get("verdict") or "").strip().lower()
    return v if v in {"supported", "partial", "unsupported"} else ""


async def _verify_one(
    row: EvidenceRow,
    sources: list[RetrievedSource],
    call_fn: CallFn,
    sem: asyncio.Semaphore,
) -> str | None:
    """Score one row. Returns the verdict string or None on any issue."""
    if not row.citations:
        return None
    snippets = _build_snippets(row.citations, sources)
    if snippets.startswith("(no snippets"):
        return None
    user = USER_TEMPLATE.format(claim=row.claim.strip()[:1200], snippets=snippets)
    async with sem:
        try:
            raw, _provider = await call_fn(user, SYSTEM_PROMPT)
        except Exception:
            return None
    verdict = _parse_verdict(raw)
    return verdict or None


async def verify_evidence_rows(
    report: StructuredReport,
    sources: list[RetrievedSource],
    call_fn: CallFn | None = None,
    max_claims: int = MAX_CLAIMS,
    concurrency: int = CONCURRENCY,
) -> dict[str, Any]:
    """Annotate the report's evidence rows with verification verdicts.

    Returns a small stats dict for logging / SSE:
      {"verified": int, "supported": int, "partial": int, "unsupported": int}
    """
    stats = {"verified": 0, "supported": 0, "partial": 0, "unsupported": 0}

    if not report.evidence_table or not sources:
        return stats

    call_fn = call_fn or _default_call_fn
    rows = [r for r in report.evidence_table if r.citations][:max_claims]
    if not rows:
        return stats

    sem = asyncio.Semaphore(concurrency)
    verdicts = await asyncio.gather(
        *[_verify_one(r, sources, call_fn, sem) for r in rows],
        return_exceptions=True,
    )

    for row, v in zip(rows, verdicts):
        if isinstance(v, BaseException) or v is None:
            continue
        row.verification = v
        stats["verified"] += 1
        if v in stats:
            stats[v] += 1

    return stats
