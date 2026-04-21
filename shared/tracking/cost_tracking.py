"""
Cost tracking for decision evaluations.
Ported from ai-orchestrator evaluation/cost_profiles.py.
"""

import os

MODEL_COSTS = {
    "gpt-4o":                     {"input": 2.50, "output": 10.00},
    "gpt-4o-mini":                {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-6":          {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input": 0.80, "output": 4.00},
    "gemini-2.5-flash":           {"input": 0.15, "output": 0.60},
    "deepseek-chat":              {"input": 0.27, "output": 1.10},
    "grok-3":                     {"input": 3.00, "output": 15.00},
}

# Cost profiles for judge model selection
PROFILES = {
    "cheap": {
        "judge_openai": "gpt-4o-mini",
        "judge_anthropic": "claude-haiku-4-5-20251001",
        "judge_google": "gemini-2.5-flash",
    },
    "balanced": {
        "judge_openai": "gpt-4o",
        "judge_anthropic": "claude-sonnet-4-6",
        "judge_google": "gemini-2.5-flash",
    },
    "full": {
        "judge_openai": "gpt-4o",
        "judge_anthropic": "claude-sonnet-4-6",
        "judge_google": "gemini-2.5-flash",
    },
}


def get_cost_profile() -> dict:
    """Get active cost profile from COST_PROFILE env var. Default: cheap."""
    name = os.environ.get("COST_PROFILE", "cheap").lower()
    return PROFILES.get(name, PROFILES["cheap"])


def estimate_cost(model: str, input_chars: int, output_chars: int) -> float:
    """Estimate USD cost for a single API call."""
    costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
    input_tokens = input_chars / 4
    output_tokens = output_chars / 4
    return (input_tokens / 1_000_000 * costs["input"]) + (output_tokens / 1_000_000 * costs["output"])


class CostTracker:
    """Track costs across a decision evaluation."""

    def __init__(self):
        self.entries = []

    def record(self, judge: str, model: str, input_chars: int, output_chars: int):
        cost = estimate_cost(model, input_chars, output_chars)
        self.entries.append({
            "judge": judge,
            "model": model,
            "input_chars": input_chars,
            "output_chars": output_chars,
            "cost_usd": cost,
        })

    def total(self) -> float:
        return sum(e["cost_usd"] for e in self.entries)

    def summary(self) -> dict:
        by_judge = {}
        for e in self.entries:
            j = e["judge"]
            if j not in by_judge:
                by_judge[j] = {"total_cost": 0.0, "model": e["model"]}
            by_judge[j]["total_cost"] += e["cost_usd"]
        return by_judge
