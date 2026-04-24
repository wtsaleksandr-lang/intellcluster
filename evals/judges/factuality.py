"""
Factuality judge (LLM, cost-efficient tier).

For each key_finding that CITES at least one source, ask a cheap model:
"Given ONLY these source snippets, is this finding supported, partially
supported, or unsupported?"

Aggregate:
  - supported / partial / unsupported counts
  - % supported-or-partial (the main quality signal)

PASS  — >=80% supported-or-partial
WARN  — >=50% supported-or-partial
FAIL  — <50% supported-or-partial
SKIP  — no cited findings in the report, OR factuality judge disabled
        (CI default), OR no provider key available

Deliberately cheap tier — we're not trying to ace factuality perfectly,
we're looking for REGRESSIONS. Running Opus on this would cost more than
the original run.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from evals.judges.base import JudgeResult, JudgeVerdict


name = "factuality"


SYSTEM_PROMPT = """You are a factuality auditor for AI research reports.

Given a CLAIM and a list of SOURCE SNIPPETS, decide whether each snippet
supports the claim, partially supports it, or does not support it.

Rules:
- Use ONLY the snippets provided. Do not use external knowledge.
- A "partial" verdict means the snippet speaks to the claim but doesn't
  fully confirm it (e.g. mentions the topic, misses the number).
- A "supported" verdict requires that the snippet contains enough
  concrete detail to back the claim on its own or with the others.
- Be strict. If in doubt, choose "partial".

Respond with a single JSON object, no prose, no markdown:
{"verdict": "supported" | "partial" | "unsupported",
 "reason": "<one short sentence>"}"""


USER_TEMPLATE = """CLAIM:
{claim}

SOURCE SNIPPETS (cited by this claim only):
{snippets}

Verdict?"""


def _build_snippets_block(finding_citations: list[int], sources: list[dict]) -> str:
    by_id = {int(s["id"]): s for s in sources if isinstance(s.get("id"), int)}
    lines = []
    for cid in finding_citations:
        src = by_id.get(int(cid))
        if not src:
            continue
        body = src.get("full_content") or src.get("snippet") or ""
        body = (body or "")[:1200]
        lines.append(f"[{cid}] {src.get('title', '')} ({src.get('domain', '')})\n{body}")
    return "\n\n".join(lines) if lines else "(no snippets available)"


def _parse_verdict(raw: str) -> tuple[str, str]:
    """Extract a verdict + reason from a model response."""
    if not raw:
        return "error", "empty response"
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return "error", "no JSON in response"
    try:
        data = json.loads(m.group())
    except Exception:
        return "error", "invalid JSON"
    v = (data.get("verdict") or "").strip().lower()
    if v not in {"supported", "partial", "unsupported"}:
        return "error", f"unknown verdict '{v}'"
    return v, (data.get("reason") or "")[:240]


async def _score_one(claim: str, snippets: str, call_fn, semaphore: asyncio.Semaphore) -> dict:
    """Score one finding. call_fn signature mirrors synthesis.providers."""
    async with semaphore:
        user = USER_TEMPLATE.format(claim=claim.strip()[:1200], snippets=snippets)
        try:
            raw, _provider = await call_fn(prompt=user, system=SYSTEM_PROMPT)
        except Exception as e:
            return {"verdict": "error", "reason": str(e)[:240]}
    verdict, reason = _parse_verdict(raw or "")
    return {"verdict": verdict, "reason": reason}


async def judge(record: dict, call_fn=None, concurrency: int = 3) -> JudgeResult:
    """Run the factuality judge.

    `call_fn` is an async callable `async (prompt, system) -> (raw_text, provider_name)`.
    When None, the judge is SKIPPED (CI-safe default).
    """
    if call_fn is None:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.SKIP,
            score=0.0,
            note="factuality judge requires --judge llm (disabled by default)",
        )

    report = record.get("report") or {}
    sources = record.get("sources") or []
    findings = [
        f for f in (report.get("key_findings") or [])
        if isinstance(f, dict) and (f.get("citations") or [])
        and (f.get("finding") or "").strip()
    ]

    if not findings:
        return JudgeResult(
            judge=name,
            verdict=JudgeVerdict.SKIP,
            score=0.0,
            note="no cited findings to evaluate",
        )

    sem = asyncio.Semaphore(concurrency)
    tasks = []
    for f in findings:
        snippets = _build_snippets_block(f.get("citations") or [], sources)
        tasks.append(_score_one(f["finding"], snippets, call_fn, sem))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    counts = {"supported": 0, "partial": 0, "unsupported": 0, "error": 0}
    detail_rows: list[dict[str, Any]] = []
    for f, r in zip(findings, results):
        if isinstance(r, BaseException):
            counts["error"] += 1
            detail_rows.append({"finding": f["finding"][:120], "verdict": "error", "reason": str(r)[:200]})
            continue
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        detail_rows.append({"finding": f["finding"][:120], **r})

    total = sum(counts.values()) or 1
    supp_or_partial = (counts["supported"] + counts["partial"]) / total

    if counts["error"] == total:
        return JudgeResult(
            judge=name, verdict=JudgeVerdict.ERROR, score=0.0,
            note="every factuality call failed",
            details={"counts": counts, "rows": detail_rows},
        )

    if supp_or_partial >= 0.8:
        verdict = JudgeVerdict.PASS
    elif supp_or_partial >= 0.5:
        verdict = JudgeVerdict.WARN
    else:
        verdict = JudgeVerdict.FAIL

    return JudgeResult(
        judge=name,
        verdict=verdict,
        score=round(supp_or_partial, 3),
        note=f"{counts['supported']} supported, {counts['partial']} partial, "
             f"{counts['unsupported']} unsupported, {counts['error']} error "
             f"(of {total})",
        details={"counts": counts, "rows": detail_rows},
    )
