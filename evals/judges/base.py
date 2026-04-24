"""
Shared judge types.

Every judge is a module exposing:

    name: str                                  # stable identifier
    async def judge(record: dict) -> JudgeResult
        # `record` carries {prompt, expectations, report, sources, scope, confidence, ...}
        # Pure judges inspect only `record` and return a JudgeResult. LLM
        # judges may make external calls; they must still return within
        # ~30s or return verdict=ERROR.

Judges never raise — failure returns a JudgeResult with verdict ERROR and
a note. The scorecard aggregator handles the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class JudgeVerdict(str, Enum):
    PASS = "pass"       # meets the correctness property
    WARN = "warn"       # borderline — flag but don't fail CI
    FAIL = "fail"       # hard violation
    SKIP = "skip"       # not applicable to this prompt (e.g. retrieval not configured)
    ERROR = "error"     # judge itself failed


@dataclass
class JudgeResult:
    judge: str                         # module name
    verdict: JudgeVerdict
    score: float                       # 0..1 where 1=best; for PASS this is typically 1.0
    note: str = ""                     # 1-sentence human explanation
    details: dict[str, Any] = field(default_factory=dict)   # machine-readable detail

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d
