"""Judge package — each judge scores one correctness property of a run record."""

from evals.judges.base import JudgeResult, JudgeVerdict
from evals.judges import (
    citation_validity,
    structural,
    freshness_alignment,
    confidence_consistency,
    factuality,
)


DETERMINISTIC_JUDGES = [
    citation_validity,
    structural,
    freshness_alignment,
    confidence_consistency,
]

LLM_JUDGES = [
    factuality,
]


__all__ = [
    "JudgeResult", "JudgeVerdict",
    "citation_validity", "structural",
    "freshness_alignment", "confidence_consistency",
    "factuality",
    "DETERMINISTIC_JUDGES", "LLM_JUDGES",
]
