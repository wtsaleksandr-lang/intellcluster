"""
Structured report schema + parser.

The Decision-Maker is asked to return a JSON object that maps onto
StructuredReport. This module:

  - defines the JSON schema the DM is instructed to use
  - parses the DM response into a StructuredReport
  - validates citations against the retrieved source IDs (drops invented refs)
  - provides a text fallback (wraps the raw Markdown in a minimal report)
  - exposes `collect_cited_source_ids()` for confidence aggregation

Philosophy: be forgiving on parsing, strict on citations. We never
invent citations — any [N] that doesn't match a real retrieved source
is stripped out before rendering.
"""

from __future__ import annotations

import json
import re

from synthesis.orchestrator.types import (
    ConfidenceScore,
    Contradiction,
    EvidenceRow,
    KeyFinding,
    StructuredReport,
)


# The schema shown to the DM in the system prompt. Kept small.
SCHEMA_DOC = """{
  "executive_summary": "2-4 sentence plain-English summary of the answer.",
  "key_findings": [
    {"finding": "Concrete finding written for the user.",
     "citations": [1, 3],
     "strength": "strong | moderate | weak"}
  ],
  "evidence_table": [
    {"claim": "Specific claim backed by evidence.",
     "citations": [2],
     "strength": "strong | moderate | weak",
     "note": "Optional short note (quote, figure, caveat)."}
  ],
  "source_confidence_note": "One paragraph on overall source quality & gaps.",
  "contradictions": [
    {"point": "What sources disagree about.",
     "side_a": "Position A.",
     "side_b": "Position B.",
     "citations_a": [1],
     "citations_b": [4]}
  ],
  "risks_unknowns": ["Things that could invalidate the finding."],
  "recommendation": "Decisive recommendation. One paragraph.",
  "what_could_change": ["Signals that would flip the conclusion."],
  "next_actions": ["Concrete next step the user can take."]
}"""


def build_schema_instruction(valid_source_ids: list[int]) -> str:
    """System-prompt fragment describing the required JSON response."""
    ids_line = (
        f"Valid citation IDs are: {valid_source_ids}. "
        "You MUST only cite from this list. Any other id is forbidden."
        if valid_source_ids
        else "NO external sources were retrieved. Leave every `citations` "
             "array empty — do NOT invent citations."
    )

    return f"""## Output Format — STRICT

Respond with ONE JSON object. No Markdown, no prose outside the object.

Use this schema:

{SCHEMA_DOC}

## Citation Rules
{ids_line}

- Every KEY FINDING that states a specific fact (number, claim, statistic)
  MUST include at least one citation id pointing into the retrieved sources.
- If a finding cannot be supported by retrieved sources, prefix it with
  "(model reasoning — unverified): " and leave citations empty.
- NEVER fabricate a URL, author, or publication.

## Strength labels
- "strong":   corroborated by multiple high-quality sources
- "moderate": supported by at least one credible source OR strong model consensus
- "weak":     single low-authority source OR inferred from model reasoning only

Return ONLY the JSON object."""


# ────────── Parsing ──────────

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.IGNORECASE)
_OBJECT = re.compile(r"\{[\s\S]*\}")


def _extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    m = _JSON_FENCE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass

    m = _OBJECT.search(text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


def _sanitise_citations(raw_citations, valid_ids: set[int]) -> list[int]:
    if not isinstance(raw_citations, list):
        return []
    out = []
    for c in raw_citations:
        try:
            cid = int(c)
        except (TypeError, ValueError):
            continue
        if cid in valid_ids and cid not in out:
            out.append(cid)
    return out


def _s(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _strength(value) -> str:
    v = _s(value).lower()
    if v in ("strong", "moderate", "weak"):
        return v
    return "moderate"


def parse_structured_report(
    raw: str,
    confidence: ConfidenceScore,
    valid_source_ids: list[int],
) -> tuple[StructuredReport | None, str]:
    """Parse DM response.

    Returns (report, parse_error). On success parse_error is "".
    On failure, the caller should fall back to a text-wrapped report
    using `text_fallback_report()`.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return None, "could not extract JSON object"

    valid_set = set(valid_source_ids)

    try:
        key_findings = []
        for f in data.get("key_findings") or []:
            if not isinstance(f, dict):
                continue
            finding = _s(f.get("finding"))
            if not finding:
                continue
            key_findings.append(KeyFinding(
                finding=finding,
                citations=_sanitise_citations(f.get("citations"), valid_set),
                strength=_strength(f.get("strength")),
            ))

        evidence_rows = []
        for r in data.get("evidence_table") or []:
            if not isinstance(r, dict):
                continue
            claim = _s(r.get("claim"))
            if not claim:
                continue
            evidence_rows.append(EvidenceRow(
                claim=claim,
                citations=_sanitise_citations(r.get("citations"), valid_set),
                strength=_strength(r.get("strength")),
                note=_s(r.get("note")),
            ))

        contradictions = []
        for c in data.get("contradictions") or []:
            if not isinstance(c, dict):
                continue
            point = _s(c.get("point"))
            if not point:
                continue
            contradictions.append(Contradiction(
                point=point,
                side_a=_s(c.get("side_a")),
                side_b=_s(c.get("side_b")),
                citations_a=_sanitise_citations(c.get("citations_a"), valid_set),
                citations_b=_sanitise_citations(c.get("citations_b"), valid_set),
            ))

        risks = [
            _s(x) for x in (data.get("risks_unknowns") or []) if _s(x)
        ]
        wcc = [
            _s(x) for x in (data.get("what_could_change") or []) if _s(x)
        ]
        nxt = [
            _s(x) for x in (data.get("next_actions") or []) if _s(x)
        ]

        report = StructuredReport(
            executive_summary=_s(data.get("executive_summary")),
            key_findings=key_findings,
            evidence_table=evidence_rows,
            source_confidence_note=_s(data.get("source_confidence_note")),
            contradictions=contradictions,
            risks_unknowns=risks,
            recommendation=_s(data.get("recommendation")),
            what_could_change=wcc,
            next_actions=nxt,
            confidence=confidence,
        )
        return report, ""
    except Exception as e:
        return None, f"parse error: {str(e)[:200]}"


def collect_cited_source_ids(report: StructuredReport) -> set[int]:
    """All citation ids used anywhere in the report."""
    ids: set[int] = set()
    for f in report.key_findings:
        ids.update(f.citations)
    for r in report.evidence_table:
        ids.update(r.citations)
    for c in report.contradictions:
        ids.update(c.citations_a)
        ids.update(c.citations_b)
    return ids


def text_fallback_report(
    raw_text: str,
    confidence: ConfidenceScore,
) -> StructuredReport:
    """Wrap free-text DM output in a minimal StructuredReport so the UI
    still renders. Used when JSON parsing fails."""
    summary = raw_text.strip().split("\n\n", 1)[0][:600] if raw_text else ""
    return StructuredReport(
        executive_summary=summary or "(model returned unstructured output)",
        key_findings=[],
        evidence_table=[],
        source_confidence_note=(
            "The model did not return a structured response; the full answer "
            "is preserved below but without per-claim citations."
        ),
        contradictions=[],
        risks_unknowns=[],
        recommendation=raw_text.strip(),
        what_could_change=[],
        next_actions=[],
        confidence=confidence,
    )
