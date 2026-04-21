#!/usr/bin/env python3
"""
Full blind evaluation runner.
Collects outputs, anonymizes, judges, aggregates, and generates report.

Usage:
    python -m evaluation.run_evaluation                    # full evaluation
    python -m evaluation.run_evaluation --prompts P01,P02  # specific prompts only
    python -m evaluation.run_evaluation --skip-collect     # re-judge existing outputs
    python -m evaluation.run_evaluation --test-mode        # use mock providers (no API cost)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from synthesis.config import settings
from synthesis.evaluation.collectors.app_collector import collect_app_output
from synthesis.evaluation.collectors.standalone_collector import collect_standalone_output
from synthesis.evaluation.judges.blind_judge import anonymize_responses, run_judge, JUDGE_MODELS
from synthesis.evaluation.aggregator import (
    aggregate_prompt_results,
    aggregate_full_evaluation,
    generate_report,
    save_report,
)


OUTPUTS_DIR = Path("evaluation/outputs")
PROMPTS_FILE = Path("evaluation/test_prompts.json")


def load_prompts(filter_ids: list[str] | None = None) -> list[dict]:
    with open(PROMPTS_FILE) as f:
        prompts = json.load(f)
    if filter_ids:
        prompts = [p for p in prompts if p["id"] in filter_ids]
    return prompts


def save_outputs(prompt_id: str, outputs: list[dict]):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    path.write_text(json.dumps(outputs, indent=2, ensure_ascii=False), encoding="utf-8")


def load_outputs(prompt_id: str) -> list[dict]:
    path = OUTPUTS_DIR / f"{prompt_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


async def collect_all_outputs(prompt: dict, app_url: str) -> list[dict]:
    """Collect from app + standalone models for a single prompt."""
    prompt_text = prompt["prompt"]
    category = prompt["category"]
    outputs = []

    # 1. Collect from our app
    print(f"  Collecting from orchestrator app...")
    try:
        app_out = await collect_app_output(prompt_text, category, base_url=app_url)
        app_out["prompt_id"] = prompt["id"]
        app_out["timestamp"] = datetime.now(timezone.utc).isoformat()
        outputs.append(app_out)
        print(f"    Orchestrator: {len(app_out.get('final_output', ''))} chars, {app_out.get('runtime_ms', 0)}ms")
    except Exception as e:
        print(f"    Orchestrator FAILED: {e}")

    # 2. Collect from standalone models
    standalone_providers = {
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
    }

    for provider, api_key in standalone_providers.items():
        if not api_key:
            print(f"  Skipping {provider} (no API key)")
            continue

        print(f"  Collecting from {provider} standalone...")
        try:
            standalone_out = await collect_standalone_output(prompt_text, provider, api_key)
            standalone_out["prompt_id"] = prompt["id"]
            standalone_out["timestamp"] = datetime.now(timezone.utc).isoformat()
            outputs.append(standalone_out)
            print(f"    {provider}: {len(standalone_out.get('final_output', ''))} chars, "
                  f"{standalone_out.get('runtime_ms', 0)}ms")
        except Exception as e:
            print(f"    {provider} FAILED: {e}")

    return outputs


async def judge_prompt(prompt: dict, outputs: list[dict]) -> tuple[list[dict], dict]:
    """Anonymize and judge outputs for a single prompt."""
    # Filter to outputs with actual content
    valid = [o for o in outputs if o.get("final_output")]
    if len(valid) < 2:
        print(f"  Only {len(valid)} valid outputs — skipping judging")
        return [], {}

    anonymized, key_map = anonymize_responses(valid)
    print(f"  Anonymized {len(anonymized)} responses: {list(key_map.values())}")

    judge_results = []
    judge_keys = {
        "judge_openai": settings.openai_api_key,
        "judge_anthropic": settings.anthropic_api_key,
        "judge_google": settings.google_api_key,
    }

    for judge_name, api_key in judge_keys.items():
        if not api_key:
            print(f"  Skipping {judge_name} (no API key)")
            continue

        print(f"  Running {judge_name}...")
        try:
            result = await run_judge(judge_name, api_key, prompt["prompt"], anonymized)
            if "error" in result:
                print(f"    {judge_name} error: {result['error'][:100]}")
            else:
                ranking = result.get("ranking", [])
                winner_label = ranking[0] if ranking else "?"
                winner_system = key_map.get(winner_label, "?")
                print(f"    {judge_name} winner: {winner_label} = {winner_system}")
            judge_results.append(result)
        except Exception as e:
            print(f"    {judge_name} FAILED: {e}")
            judge_results.append({"error": str(e)})

    return judge_results, key_map


async def main():
    parser = argparse.ArgumentParser(description="Run blind evaluation")
    parser.add_argument("--prompts", type=str, help="Comma-separated prompt IDs (e.g. P01,P02)")
    parser.add_argument("--skip-collect", action="store_true", help="Skip collection, re-judge existing outputs")
    parser.add_argument("--app-url", default="http://localhost:8080", help="App URL")
    parser.add_argument("--test-mode", action="store_true", help="Use test mode (mock providers)")
    args = parser.parse_args()

    filter_ids = args.prompts.split(",") if args.prompts else None
    prompts = load_prompts(filter_ids)
    print(f"Loaded {len(prompts)} prompts")

    if args.test_mode:
        os.environ["TEST_MODE"] = "true"
        os.environ["DEV_MODE"] = "true"
        print("TEST MODE: using mock providers")

    all_prompt_results = []

    for i, prompt in enumerate(prompts):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(prompts)}] {prompt['id']}: {prompt['title']}")
        print(f"{'='*60}")

        # Collect outputs
        if args.skip_collect:
            outputs = load_outputs(prompt["id"])
            print(f"  Loaded {len(outputs)} existing outputs from cache")
        else:
            outputs = await collect_all_outputs(prompt, args.app_url)
            save_outputs(prompt["id"], outputs)
            print(f"  Saved {len(outputs)} outputs")

        if not outputs:
            print(f"  No outputs — skipping")
            continue

        # Judge
        judge_results, key_map = await judge_prompt(prompt, outputs)

        # Aggregate
        result = aggregate_prompt_results(prompt, judge_results, key_map)
        all_prompt_results.append(result)
        print(f"  Winner: {result['winner']} | Judges agree: {result['judges_agree']}")

    # Full aggregation
    print(f"\n{'='*60}")
    print("AGGREGATION")
    print(f"{'='*60}")

    full_agg = aggregate_full_evaluation(all_prompt_results)
    print(f"Win counts: {full_agg['win_counts']}")
    print(f"Win rates: {full_agg['win_rate']}")
    print(f"Judge agreement: {full_agg['judge_agreement_rate']:.0%}")

    # Generate report
    report = generate_report(all_prompt_results, full_agg)
    results_json = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompts": [p["id"] for p in prompts],
        "per_prompt": all_prompt_results,
        "aggregation": full_agg,
    }

    md_path, json_path = save_report(report, results_json)
    print(f"\nReport saved:")
    print(f"  Markdown: {md_path}")
    print(f"  JSON: {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
