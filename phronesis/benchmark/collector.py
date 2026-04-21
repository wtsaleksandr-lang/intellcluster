"""
Benchmark collector — runs test prompts through the Decision Tool pipeline.
"""

import asyncio
import json
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phronesis.engine.types import DecisionInput, AnalysisSettings
from phronesis.engine.pipeline import run_decision_pipeline


async def collect_output(prompt_data: dict) -> dict:
    """Run a single prompt through the Decision Tool and return the full result."""

    input_data = DecisionInput(
        question=prompt_data["question"],
        options=prompt_data["options"],
        criteria=prompt_data["criteria"],
        settings=AnalysisSettings(depth="standard", focus="balanced", length="standard"),
    )

    start = time.time()
    steps = []

    def on_step(step, detail):
        steps.append({"step": step, "detail": detail, "time": time.time() - start})

    result = await run_decision_pipeline(input_data, on_step=on_step)
    elapsed_ms = int((time.time() - start) * 1000)

    return {
        "prompt_id": prompt_data["id"],
        "question": result.question,
        "winner": result.winner,
        "why_winner_won": result.why_winner_won,
        "judges_agree": result.judges_agree,
        "judge_count": result.judge_count,
        "confidence": result.confidence_level,
        "confidence_score": result.confidence_score,
        "cost_usd": result.total_cost_usd,
        "latency_ms": elapsed_ms,
        "run_id": result.run_id,
        "ranked_options": [
            {
                "option": o.option,
                "rank": o.rank,
                "score": o.final_score,
                "strengths": o.strengths,
                "weaknesses": o.weaknesses,
                "dimension_scores": o.dimension_scores,
                "rank_points": o.rank_points,
            }
            for o in result.ranked_options
        ],
        "steps": steps,
    }


async def collect_all(prompts: list[dict]) -> list[dict]:
    """Run all prompts sequentially (to avoid API rate limits)."""
    results = []
    for i, prompt in enumerate(prompts):
        print(f"  [{i+1}/{len(prompts)}] {prompt['id']}: {prompt['title']}...", end="", flush=True)
        try:
            output = await collect_output(prompt)
            print(f" winner={output['winner']}, {output['latency_ms']}ms")
            results.append(output)
        except Exception as e:
            print(f" FAILED: {e}")
            results.append({"prompt_id": prompt["id"], "error": str(e)[:200]})
    return results
