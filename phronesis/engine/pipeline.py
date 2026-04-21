"""
Decision Intelligence Engine — Main Pipeline (v2).
Improved workflow: extract → validate → judges (diverse perspectives) → aggregate → synthesize.
"""

import asyncio
import os
import time
import uuid

from phronesis.engine.types import DecisionInput, DecisionResult, RankedOption, AnalysisSettings
from phronesis.engine.verdict import compute_confidence, build_recommendation
from phronesis.engine.validator import validate_extraction, apply_fixes
from phronesis.engine.synthesizer import synthesize_recommendation
from phronesis.judges.rubric import build_dimensions, JUDGE_PERSPECTIVE_MAP
from phronesis.judges.blind_judge import anonymize_options, run_judge, JUDGE_MODELS
from phronesis.judges.aggregator import aggregate_decision_results
from shared.tracking.cost_tracking import CostTracker
from shared.tracking.history import save_decision


# ─── Depth → model tier mapping ───

DEPTH_CONFIGS = {
    "quick": {
        "max_judges": 1,
        "models": {
            "judge_openai": "gpt-4o-mini",
            "judge_anthropic": "claude-haiku-4-5-20251001",
            "judge_google": "gemini-2.5-flash",
        },
        "timeout": 60,
    },
    "standard": {
        "max_judges": 3,
        "models": {
            "judge_openai": "gpt-4o-mini",
            "judge_anthropic": "claude-haiku-4-5-20251001",
            "judge_google": "gemini-2.5-flash",
        },
        "timeout": 300,
    },
    "deep": {
        "max_judges": 3,
        "models": {
            "judge_openai": "gpt-4o",
            "judge_anthropic": "claude-sonnet-4-6",
            "judge_google": "gemini-2.5-flash",
        },
        "timeout": 600,
    },
}


async def run_decision_pipeline(
    input_data: DecisionInput,
    on_step: callable = None,
) -> DecisionResult:
    """Run the full decision evaluation pipeline (v2).

    Workflow:
    1. Validate extraction quality
    2. Apply fixes if needed
    3. Build dimensions from criteria
    4. Anonymize + shuffle options
    5. Run judges in parallel (each with a different perspective)
    6. Aggregate scores
    7. Synthesize recommendation (AI-written, not just picked from judges)
    8. Compute confidence
    """

    run_id = str(uuid.uuid4())[:8]
    pipeline_start = time.time()
    cost_tracker = CostTracker()
    settings = input_data.settings

    def emit(step: str, detail: str = ""):
        if on_step:
            on_step(step, detail)

    # Resolve depth config
    depth_cfg = DEPTH_CONFIGS.get(settings.depth, DEPTH_CONFIGS["standard"])
    max_judges = depth_cfg["max_judges"]
    model_overrides = depth_cfg["models"]
    judge_timeout = depth_cfg["timeout"]

    # ─── Step 1: Validate extraction ───
    emit("validating", "Validating input quality...")
    validation = await validate_extraction(
        input_data.question,
        input_data.options,
        input_data.criteria,
    )

    question = input_data.question
    options = list(input_data.options)
    criteria = list(input_data.criteria)

    if not validation.get("valid") and validation.get("suggested_fixes"):
        emit("validating", "Refining extracted structure...")
        question, options, criteria = apply_fixes(
            question, options, criteria, validation["suggested_fixes"]
        )

    # ─── Step 2: Build scoring dimensions ───
    emit("dimensions", "Building evaluation criteria...")
    dimensions = build_dimensions(criteria)

    # ─── Step 3: Anonymize options ───
    emit("anonymize", "Shuffling options to prevent bias...")
    anonymized, key_map = anonymize_options(options)

    # ─── Step 4: Run judges with diverse perspectives ───
    analyst_word = "analyst" if max_judges == 1 else "analysts"
    emit("judging", f"Running {max_judges} independent {analyst_word}...")

    judge_tasks = []
    judge_names = []
    for judge_name, config in JUDGE_MODELS.items():
        if len(judge_tasks) >= max_judges:
            break
        api_key = None
        for env_key in config["env_keys"]:
            api_key = os.environ.get(env_key)
            if api_key:
                break
        if not api_key:
            continue

        model_override = model_overrides.get(judge_name, config["model"])
        perspective = JUDGE_PERSPECTIVE_MAP.get(judge_name, "general")

        judge_tasks.append(
            run_judge(
                judge_name=judge_name,
                api_key=api_key,
                question=question,
                anonymized_options=anonymized,
                dimensions=dimensions,
                timeout=judge_timeout,
                model_override=model_override,
                focus=settings.focus,
                length=settings.length,
                perspective=perspective,
                attachments=input_data.attachments or None,
            )
        )
        judge_names.append(judge_name)

    if not judge_tasks:
        raise RuntimeError("No AI analysts available. Check API keys.")

    emit("judging", f"Waiting for {len(judge_tasks)} {analyst_word}...")
    judge_results = await asyncio.gather(*judge_tasks, return_exceptions=True)

    # Process results
    processed_results = []
    for i, result in enumerate(judge_results):
        if isinstance(result, Exception):
            processed_results.append({"error": str(result)[:200], "judge": judge_names[i]})
        else:
            processed_results.append(result)
            model = model_overrides.get(judge_names[i], JUDGE_MODELS[judge_names[i]]["model"])
            cost_tracker.record(
                judge=judge_names[i],
                model=model,
                input_chars=len(str(anonymized)) + 2000,
                output_chars=len(str(result)),
            )

    # ─── Step 5: Aggregate ───
    emit("aggregating", "Aggregating analyst scores...")
    aggregated = aggregate_decision_results(
        question=question,
        judge_results=processed_results,
        key_map=key_map,
        dimensions=dimensions,
    )

    # ─── Step 6: Build ranked options ───
    ranked_options = []
    for option_text, data in aggregated["options"].items():
        ranked_options.append(RankedOption(
            option=option_text,
            rank=0,
            final_score=data["avg_scores"].get("overall", 0),
            dimension_scores=data["avg_scores"],
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            rank_points=data.get("rank_points", 0),
        ))

    ranked_options.sort(key=lambda o: (o.final_score, o.rank_points), reverse=True)
    for i, opt in enumerate(ranked_options):
        opt.rank = i + 1

    # ─── Step 7: Synthesize recommendation ───
    emit("synthesizing", "Writing recommendation...")
    synthesized = await synthesize_recommendation(
        question=question,
        winner=aggregated["winner"],
        ranked_options=[
            {"option": o.option, "rank": o.rank, "score": o.final_score}
            for o in ranked_options
        ],
        judge_explanations=aggregated.get("explanations", []),
        judges_agree=aggregated["judges_agree"],
        judge_count=aggregated["judge_count"],
    )

    # Fall back to old verdict logic if synthesizer fails
    if synthesized:
        why_winner_won = synthesized
    else:
        why_winner_won = build_recommendation(aggregated, ranked_options)

    # ─── Step 8: Confidence ───
    emit("confidence", "Computing confidence...")
    confidence_score, confidence_level = compute_confidence(
        judge_count=aggregated["judge_count"],
        judges_agree=aggregated["judges_agree"],
        ranked_options=ranked_options,
    )

    latency_ms = int((time.time() - pipeline_start) * 1000)

    result = DecisionResult(
        question=question,
        ranked_options=ranked_options,
        winner=aggregated["winner"],
        why_winner_won=why_winner_won,
        judges_agree=aggregated["judges_agree"],
        judge_count=aggregated["judge_count"],
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        total_cost_usd=cost_tracker.total(),
        latency_ms=latency_ms,
        run_id=run_id,
    )

    # Save to history
    emit("saving", "Saving results...")
    save_decision({
        "run_id": run_id,
        "question": question,
        "options": options,
        "criteria": criteria,
        "settings": {
            "depth": settings.depth,
            "focus": settings.focus,
            "length": settings.length,
            "web_search": settings.web_search,
        },
        "validation": validation,
        "winner": result.winner,
        "confidence": confidence_level,
        "confidence_score": confidence_score,
        "judges_agree": result.judges_agree,
        "judge_count": result.judge_count,
        "latency_ms": latency_ms,
        "cost_usd": cost_tracker.total(),
        "ranked_options": [
            {
                "option": o.option,
                "rank": o.rank,
                "score": o.final_score,
                "strengths": o.strengths,
                "weaknesses": o.weaknesses,
            }
            for o in ranked_options
        ],
    })

    emit("done", "Analysis complete.")
    return result
