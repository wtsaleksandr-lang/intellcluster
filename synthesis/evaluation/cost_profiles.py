"""
Testing cost profiles for benchmark evaluation.
Controls which models are used for judging and standalone collection.

Profiles:
  cheap    — minimize Anthropic costs aggressively (use Haiku for judging)
  balanced — moderate use (Sonnet for judging)
  full     — no cost optimization (use configured models)

Set via TESTING_PROFILE env var. Default: cheap.
"""

import os

# Per-model cost estimates (USD per 1M tokens: input, output)
MODEL_COSTS = {
    "gpt-4o":                     {"input": 2.50, "output": 10.00},
    "gpt-4o-mini":                {"input": 0.15, "output": 0.60},
    "claude-sonnet-4-6":          {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input": 0.80, "output": 4.00},
    "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
    "gemini-2.5-flash":           {"input": 0.15, "output": 0.60},
    "deepseek-chat":              {"input": 0.27, "output": 1.10},
    "grok-3":                     {"input": 3.00, "output": 15.00},
}

PROFILES = {
    "cheap": {
        "description": "Minimize Anthropic costs — use Haiku for judging, skip expensive standalone",
        "judge_models": {
            "judge_openai": "gpt-4o-mini",           # cheap OpenAI
            "judge_anthropic": "claude-haiku-4-5-20251001",  # cheapest Anthropic
            "judge_google": "gemini-2.5-flash",       # already cheap
        },
        "standalone_models": {
            "openai": "gpt-4o",           # keep flagship for fair comparison
            "anthropic": "claude-sonnet-4-6",  # keep Sonnet (not Opus) for standalone
            "google": "gemini-2.5-flash",
        },
        "skip_expensive_judges": True,
        "max_judges": 3,
    },
    "balanced": {
        "description": "Moderate cost — Sonnet for judging, standard standalone",
        "judge_models": {
            "judge_openai": "gpt-4o",
            "judge_anthropic": "claude-sonnet-4-6",
            "judge_google": "gemini-2.5-flash",
        },
        "standalone_models": {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-6",
            "google": "gemini-2.5-flash",
        },
        "skip_expensive_judges": False,
        "max_judges": 3,
    },
    "full": {
        "description": "No cost optimization — use best models everywhere",
        "judge_models": {
            "judge_openai": "gpt-4o",
            "judge_anthropic": "claude-sonnet-4-6",
            "judge_google": "gemini-2.5-flash",
        },
        "standalone_models": {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-6",
            "google": "gemini-2.5-flash",
        },
        "skip_expensive_judges": False,
        "max_judges": 3,
    },
}


def get_testing_profile() -> dict:
    """Get the active testing profile from TESTING_PROFILE env var."""
    profile_name = os.environ.get("TESTING_PROFILE", "cheap").lower()
    profile = PROFILES.get(profile_name, PROFILES["cheap"])
    profile["name"] = profile_name
    return profile


def estimate_prompt_cost(model: str, input_chars: int, output_chars: int) -> float:
    """Estimate USD cost for a single API call."""
    costs = MODEL_COSTS.get(model, {"input": 3.0, "output": 15.0})
    # Rough: 1 token ~ 4 chars
    input_tokens = input_chars / 4
    output_tokens = output_chars / 4
    return (input_tokens / 1_000_000 * costs["input"]) + (output_tokens / 1_000_000 * costs["output"])


class CostTracker:
    """Track costs per system across a benchmark run."""

    def __init__(self):
        self.entries = []  # [{system, model, role, input_chars, output_chars, cost_usd}]

    def record(self, system: str, model: str, role: str, input_chars: int, output_chars: int):
        cost = estimate_prompt_cost(model, input_chars, output_chars)
        self.entries.append({
            "system": system,
            "model": model,
            "role": role,
            "input_chars": input_chars,
            "output_chars": output_chars,
            "cost_usd": cost,
        })

    def summary(self) -> dict:
        """Return per-system cost summary."""
        by_system = {}
        for e in self.entries:
            sys = e["system"]
            if sys not in by_system:
                by_system[sys] = {"total_cost": 0.0, "calls": 0, "models_used": set()}
            by_system[sys]["total_cost"] += e["cost_usd"]
            by_system[sys]["calls"] += 1
            by_system[sys]["models_used"].add(e["model"])

        # Convert sets to lists for JSON
        for sys in by_system:
            by_system[sys]["models_used"] = sorted(by_system[sys]["models_used"])

        return by_system

    def total(self) -> float:
        return sum(e["cost_usd"] for e in self.entries)

    def report_lines(self) -> list[str]:
        """Generate markdown cost summary lines."""
        lines = ["\n## Cost Summary\n"]
        summary = self.summary()
        lines.append("| System | Calls | Est. Cost | Models Used |")
        lines.append("|--------|-------|-----------|-------------|")
        total = 0.0
        for sys in sorted(summary.keys()):
            data = summary[sys]
            display = sys.replace("standalone_", "").replace("_", " ").title()
            models = ", ".join(data["models_used"])
            lines.append(f"| {display} | {data['calls']} | ${data['total_cost']:.4f} | {models} |")
            total += data["total_cost"]
        lines.append(f"| **Total** | | **${total:.4f}** | |")
        return lines
