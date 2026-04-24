"""
Phronesis OS types — every artifact the advisory pipeline produces or consumes.

Every type is a dataclass that serializes cleanly to JSON via `dataclasses.asdict`
so sessions can be persisted in a JSONL store and re-rendered from disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════


class DecisionCategory(str, Enum):
    """Top-level category the Category Agent classifies the advisory into."""
    CAREER = "career"
    PURCHASE = "purchase"
    BUSINESS = "business"
    FINANCE = "finance"
    VENDOR = "vendor"
    RELOCATION = "relocation"
    STRATEGIC = "strategic"
    PERSONAL = "personal"
    EXPLORATORY = "exploratory"


class AdvisoryStage(str, Enum):
    """Pipeline stations — emitted via SSE so the UI can light up the right card."""
    INTAKE = "intake"
    CLARIFY = "clarify"
    AWAITING_ANSWERS = "awaiting_answers"
    CATEGORY = "category"
    CRITERIA = "criteria"
    EVIDENCE = "evidence"
    OPTIMIZER = "optimizer"
    SKEPTIC = "skeptic"
    PRAGMATIST = "pragmatist"
    SYNTHESIS = "synthesis"
    DONE = "done"
    ERROR = "error"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    MODERATE_HIGH = "moderate-high"
    HIGH = "high"


# ═══════════════════════════════════════════════════════════════════════
# Intake + clarification
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class IntakeResult:
    """
    The structured understanding the Intake Agent extracts from messy input.
    None of the fields are required — absence is information, and downstream
    agents are expected to notice missing data rather than fabricate it.
    """
    advisory_question: str = ""
    options: list[str] = field(default_factory=list)
    user_goal: str = ""
    constraints: list[str] = field(default_factory=list)
    timeline: str | None = None        # "this week", "1 month", "3 months", ...
    budget: str | None = None          # free-text: "$2k", "small", "unlimited"
    risk_tolerance: str | None = None  # low / moderate / high / mentioned-unclear
    emotional_context: str | None = None
    missing_info: list[str] = field(default_factory=list)
    confidence: float = 0.0            # 0-1 how confident the Intake Agent is
    inferred_category: str | None = None  # DecisionCategory value as string


@dataclass
class ClarifyingQuestion:
    """An MCQ the Clarifier Agent wants the user to answer before analysis."""
    id: str                 # stable across session, e.g. "q_timeline"
    question: str
    options: list[str]      # answer labels, 3-6 items
    help_text: str = ""     # optional short explanation
    allow_skip: bool = True
    rationale: str = ""     # why this question materially changes the output


@dataclass
class UserAnswer:
    """User's response to one ClarifyingQuestion."""
    question_id: str
    answer: str | None      # the chosen option label; None if skipped


# ═══════════════════════════════════════════════════════════════════════
# Analysis artifacts
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class CriteriaItem:
    """A single weighted criterion produced by the Criteria Architect."""
    name: str
    weight: int             # 1-10 scale (higher = more important)
    rationale: str = ""     # one-line why-this-matters


@dataclass
class EvidenceItem:
    """One row in the Evidence/Assumption Agent's ledger."""
    claim: str
    kind: str               # "fact_from_user" | "assumption" | "missing" | "external"
    confidence: str = "medium"   # low/medium/high
    source: str | None = None    # free-text where it came from


@dataclass
class AgentOutput:
    """
    Generic agent output, carried end-to-end so the UI can render each
    station's work faithfully. Each agent fills in the fields it cares about.
    """
    agent: str                       # "intake", "optimizer", ...
    status: str = "ok"               # "ok" | "skipped" | "error"
    summary: str = ""                # 1-3 sentence headline for the station card
    bullets: list[str] = field(default_factory=list)
    recommended_option: str | None = None
    confidence: str | None = None
    risks: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)   # model-specific payload
    latency_ms: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    error: str | None = None


@dataclass
class RankingOption:
    """One option in the final ranked output, with per-criterion scores."""
    option: str
    rank: int                        # 1 = winner
    score: float                     # 0-10
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    dimension_scores: dict[str, float] = field(default_factory=dict)
    color: str = "green"             # "green" | "yellow" | "red"


@dataclass
class FinalAdviceReport:
    """
    The user-facing deliverable. Every advisory run produces one of these —
    it's what /advisory/result/{run_id} renders and what export_pdf / export_json
    operate on.
    """
    recommended_best_move: str
    why_this_wins: list[str]
    ranked_options: list[RankingOption] = field(default_factory=list)
    confidence_level: str = ConfidenceLevel.MODERATE.value
    confidence_range: str | None = None          # e.g. "72-80%", optional
    key_risks: list[str] = field(default_factory=list)
    what_could_change_this: list[str] = field(default_factory=list)
    immediate_next_step: str = ""
    action_ladder: list[str] = field(default_factory=list)        # 3-5 concrete steps
    agent_consensus: dict[str, str] = field(default_factory=dict)  # agent -> recommended option
    consensus_level: str = "moderate"                             # unanimous/moderate/split/fragmented


# ═══════════════════════════════════════════════════════════════════════
# Session — the root record persisted per advisory run
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class AdvisorySession:
    """A single advisory run, persisted end-to-end."""
    run_id: str
    user_email: str | None
    created_at: str                   # ISO timestamp
    raw_input: str                    # the messy text the user typed

    # Stage trackers
    stage: str = AdvisoryStage.INTAKE.value
    error: str | None = None

    # Intake + clarification
    intake: IntakeResult | None = None
    clarifying_questions: list[ClarifyingQuestion] = field(default_factory=list)
    user_answers: list[UserAnswer] = field(default_factory=list)

    # Category
    category: str | None = None
    category_confidence: float = 0.0
    category_user_corrected: bool = False

    # Analysis
    criteria: list[CriteriaItem] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    agent_outputs: list[AgentOutput] = field(default_factory=list)

    # Final
    report: FinalAdviceReport | None = None

    # Operational
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
