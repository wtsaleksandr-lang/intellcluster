"""
Core types for the Decision Intelligence Engine.
"""

from dataclasses import dataclass, field


@dataclass
class AnalysisSettings:
    """User-configurable analysis settings."""
    depth: str = "standard"       # quick | standard | deep
    focus: str = "balanced"       # balanced | risks | practical
    length: str = "standard"      # concise | standard | detailed
    web_search: bool = False


@dataclass
class DecisionInput:
    """User-submitted decision request."""
    question: str
    options: list[str]           # 2-10 options
    criteria: list[dict]         # [{"name": "Cost", "weight": 8}, ...]
    settings: AnalysisSettings = field(default_factory=AnalysisSettings)
    attachments: list[str] = field(default_factory=list)  # filenames (context only for now)


@dataclass
class RankedOption:
    """A single option with its evaluation results."""
    option: str
    rank: int
    final_score: float           # 0-10
    dimension_scores: dict       # {dim_name: avg_score}
    strengths: list[str]
    weaknesses: list[str]
    rank_points: int


@dataclass
class DecisionResult:
    """Complete evaluation output."""
    question: str
    ranked_options: list[RankedOption]
    winner: str
    why_winner_won: str
    judges_agree: bool
    judge_count: int
    confidence_level: str        # "high" | "moderate" | "low"
    confidence_score: float      # 0-100
    total_cost_usd: float
    latency_ms: int
    run_id: str
