"""
Lightweight cost tracking — estimates per-run cost based on model usage.
Admin-only visibility.
"""

import json
import os
from datetime import datetime, timezone

COST_DIR = "logs"
COST_FILE = os.path.join(COST_DIR, "cost_tracking.jsonl")

# Approximate cost per 1K tokens (input + output averaged)
MODEL_COSTS_PER_1K = {
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.0002,
    "claude-sonnet-4-6": 0.006,
    "claude-opus-4-6": 0.03,
    "claude-haiku-4-5-20251001": 0.0005,
    "gemini-2.5-flash": 0.0003,
    "gemini-2.0-flash": 0.0002,
    "gemini-1.5-flash": 0.0001,
    "deepseek-chat": 0.0003,
    "grok-3": 0.005,
}


def estimate_cost(model: str, input_chars: int, output_chars: int) -> float:
    """Estimate cost for a single API call. Returns USD."""
    input_tokens = input_chars / 4
    output_tokens = output_chars / 4
    total_tokens = input_tokens + output_tokens
    rate = MODEL_COSTS_PER_1K.get(model, 0.005)
    return (total_tokens / 1000) * rate


def estimate_run_cost(
    research_models: list[str],
    strategist_model: str,
    decision_model: str,
    pe_model: str,
    prompt_chars: int,
    max_output_chars: int = 3000,
    phases: int = 1,
) -> dict:
    """Estimate total run cost before execution.
    Returns {low, mid, high, breakdown}.
    """
    avg_input = prompt_chars + 500  # system prompt overhead
    avg_output = max_output_chars

    breakdown = []

    # PE cost
    pe_cost = estimate_cost(pe_model, avg_input, 800)
    breakdown.append({"role": "prompt_engineer", "model": pe_model, "cost": round(pe_cost, 5)})

    # Research costs (per phase)
    research_total = 0
    for m in research_models:
        c = estimate_cost(m, avg_input, avg_output)
        research_total += c
        breakdown.append({"role": "research", "model": m, "cost": round(c, 5)})
    research_total *= phases

    # Strategist (per phase)
    strat_cost = estimate_cost(strategist_model, avg_output * len(research_models), avg_output) * phases
    breakdown.append({"role": "strategist", "model": strategist_model, "cost": round(strat_cost, 5)})

    # Decision maker (once)
    dm_cost = estimate_cost(decision_model, avg_output * phases, avg_output)
    breakdown.append({"role": "decision_maker", "model": decision_model, "cost": round(dm_cost, 5)})

    total_mid = pe_cost + research_total + strat_cost + dm_cost
    return {
        "low": round(total_mid * 0.6, 4),
        "mid": round(total_mid, 4),
        "high": round(total_mid * 1.5, 4),
        "breakdown": breakdown,
    }


def get_daily_cost() -> float:
    """Get total cost for today."""
    if not os.path.exists(COST_FILE):
        return 0.0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0.0
    with open(COST_FILE, "r") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("timestamp", "").startswith(today):
                    total += entry.get("total_cost_usd", 0)
            except (json.JSONDecodeError, KeyError):
                continue
    return round(total, 4)


def log_run_cost(
    run_id: str,
    model_costs: list[dict],
    total_cost: float,
    mode: str = "standard",
    tier: str = "standard",
):
    """Log cost data for a run."""
    os.makedirs(COST_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "mode": mode,
        "tier": tier,
        "total_cost_usd": round(total_cost, 6),
        "model_costs": model_costs,
    }
    with open(COST_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_cost_summary(limit: int = 50) -> dict:
    """Get recent cost data and totals."""
    if not os.path.exists(COST_FILE):
        return {"runs": [], "total_cost_usd": 0, "run_count": 0}

    runs = []
    total = 0.0
    with open(COST_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    runs.append(entry)
                    total += entry.get("total_cost_usd", 0)
                except json.JSONDecodeError:
                    continue

    runs.reverse()
    return {
        "runs": runs[:limit],
        "total_cost_usd": round(total, 4),
        "run_count": len(runs),
    }
