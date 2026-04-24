"""
Shared dataclasses for retrieval, source scoring, confidence, and the
structured final report. Everything passed between agents that isn't raw
text or a model result lives here.

Kept JSON-serialisable (asdict) for history / SSE / template rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


# ────────── Scope ──────────

@dataclass
class Scope:
    """Structured scope extracted by the Prompt Engineer.

    All fields are free-form strings (models resist strict enums) or None
    when PE couldn't confidently infer them. The point isn't machine
    precision — it's to make downstream agents stop guessing.

    timeframe:       when does the user care about? "Q4 2026", "current state",
                     "last 12 months", "all-time", None
    region:          geographic scope. "US", "EU", "UK only", "global", None
    audience:        who the answer is FOR. "solo founders",
                     "enterprise DevOps leads", None
    decision_intent: the user's core verb. "buy", "build", "compare",
                     "understand", "validate", "investigate", "plan", None
    """
    timeframe: str | None = None
    region: str | None = None
    audience: str | None = None
    decision_intent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def is_empty(self) -> bool:
        return not any([self.timeframe, self.region, self.audience, self.decision_intent])


# ────────── Retrieval ──────────

@dataclass
class RetrievedSource:
    """A single web source pulled during retrieval.

    id:                 stable 1-based index used in citations (e.g. [1])
    title:              page title
    url:                canonical URL
    domain:             extracted host (used by source-quality scoring)
    published:          ISO date string if available, else None
    snippet:            short content excerpt (<= 600 chars)
    full_content:       extracted main article text (Tavily raw_content,
                        truncated). None when the provider couldn't extract
                        the full page — use `snippet` in that case.
    retrieved_at:       ISO timestamp when we fetched it
    relevance:          provider-supplied score (0-1) — post-fusion this
                        carries the Reciprocal Rank Fusion score
    query:              the search query that produced this hit
    provider:           name of the primary provider that surfaced it
    providers_agreeing: list of provider names that ALSO returned this
                        URL in the same run (corroboration signal)
    """
    id: int
    title: str
    url: str
    domain: str
    published: str | None
    snippet: str
    retrieved_at: str
    relevance: float = 0.0
    query: str = ""
    full_content: str | None = None
    provider: str | None = None
    providers_agreeing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ────────── Source quality ──────────

@dataclass
class SourceQuality:
    """Per-source quality breakdown produced by source_quality.score_source().

    All 0–1. overall is a weighted aggregate.
    """
    authority: float
    recency: float
    relevance: float
    originality: float
    corroboration: float
    bias_risk: float          # 0 = clean, 1 = high affiliate/SEO risk. Higher = WORSE.
    directness: float
    overall: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ────────── Confidence ──────────

@dataclass
class ConfidenceScore:
    """Composite confidence with visible components.

    band is one of: 'low' | 'moderate' | 'moderate-high' | 'high'.
    We deliberately avoid single-percent precision — it implies rigour we
    don't have.
    """
    band: str
    components: dict[str, float]   # source_quality, evidence_quantity, source_agreement, freshness, contradiction_penalty, model_consensus
    rationale: str                 # 1–2 sentence human-readable explanation

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ────────── Structured report ──────────

@dataclass
class KeyFinding:
    finding: str
    citations: list[int] = field(default_factory=list)     # RetrievedSource.id references
    strength: str = "moderate"                             # 'strong' | 'moderate' | 'weak'


@dataclass
class EvidenceRow:
    claim: str
    citations: list[int]
    strength: str                                          # 'strong' | 'moderate' | 'weak'
    note: str = ""
    # Populated by verification.py after the DM produces the report.
    # Values: "supported" | "partial" | "unsupported" | None (not run / no citations)
    verification: str | None = None


@dataclass
class Contradiction:
    point: str
    side_a: str
    side_b: str
    citations_a: list[int] = field(default_factory=list)
    citations_b: list[int] = field(default_factory=list)


@dataclass
class StructuredReport:
    """The output of the Decision-Maker when retrieval ran.

    Every section is optional-but-present (empty list / "" if the DM
    had nothing to say). Rendering code is forgiving of missing fields.
    """
    executive_summary: str
    key_findings: list[KeyFinding]
    evidence_table: list[EvidenceRow]
    source_confidence_note: str
    contradictions: list[Contradiction]
    risks_unknowns: list[str]
    recommendation: str
    what_could_change: list[str]
    next_actions: list[str]
    confidence: ConfidenceScore

    def to_dict(self) -> dict[str, Any]:
        return {
            "executive_summary": self.executive_summary,
            "key_findings": [asdict(f) for f in self.key_findings],
            "evidence_table": [asdict(r) for r in self.evidence_table],
            "source_confidence_note": self.source_confidence_note,
            "contradictions": [asdict(c) for c in self.contradictions],
            "risks_unknowns": self.risks_unknowns,
            "recommendation": self.recommendation,
            "what_could_change": self.what_could_change,
            "next_actions": self.next_actions,
            "confidence": self.confidence.to_dict(),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
