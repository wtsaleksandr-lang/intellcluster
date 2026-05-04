"""
Core orchestration pipeline.

Flow: Prompt Engineer → Retrieval → Research (parallel, streaming)
      → Consensus → Strategist → (optional) Red Team → Decision-Maker.

New in this version
-------------------
- Real retrieval layer (Tavily, key-gated). Sources flow into every
  downstream agent so claims can be grounded and cited by id.
- Source quality scoring (deterministic heuristic, no LLM cost).
- Composite confidence (source quality × evidence × agreement × freshness
  × contradiction penalty × model consensus). Band reported, not percent.
- Decision-Maker now returns a StructuredReport (executive summary,
  key findings, evidence table, contradictions, risks, recommendation,
  what-could-change, next actions) with citations validated against the
  retrieved source IDs — any fabricated [N] refs are stripped.
- Graceful fallback: if retrieval is unconfigured or returns nothing, the
  pipeline runs as before and confidence is computed from model consensus
  alone. No breaking changes to existing users.

The SSE event surface gains three events:
    sources            — list of RetrievedSource dicts
    source_quality     — {id: SourceQuality dict}
    structured_report  — StructuredReport dict (sent alongside `decision`)
Existing events are unchanged.
"""

import asyncio

from synthesis.config import settings
from synthesis.orchestrator.agents.prompt_engineer import run_prompt_engineer
from synthesis.orchestrator.agents.researcher import call_model, truncate_output
from synthesis.orchestrator.agents.consensus_extractor import extract_consensus, format_consensus_for_strategist
from synthesis.orchestrator.agents.strategist import run_strategist
from synthesis.orchestrator.agents.decision_maker import run_decision_maker
from synthesis.orchestrator.agents.red_team import should_trigger_red_team, run_red_team
from synthesis.orchestrator.logger import log_event
from synthesis.orchestrator.history import save_run
from synthesis.orchestrator.cost_tracking import estimate_cost, log_run_cost
from synthesis.orchestrator.freshness import detect_freshness, get_freshness_instruction
from synthesis.orchestrator.prompts.categories import get_category_context
from synthesis.orchestrator.prompts.global_context import get_global_context
from synthesis.orchestrator.providers import get_providers
from synthesis.orchestrator.retrieval import (
    is_configured as retrieval_configured,
    retrieve_sources,
    format_sources_for_prompt,
)
from synthesis.orchestrator.source_quality import score_sources
from synthesis.orchestrator.confidence import compute_confidence
from synthesis.orchestrator.report_schema import collect_cited_source_ids
from synthesis.orchestrator.scope import format_scope_for_prompt
from synthesis.orchestrator.types import Scope
from synthesis.orchestrator.verification import verify_evidence_rows
from shared.providers.base import ModelResult


async def _emit(queue: asyncio.Queue, event: str, data: dict):
    """Push an SSE event to the queue."""
    try:
        queue.put_nowait({"event": event, "data": data})
    except asyncio.QueueFull:
        pass


async def _run_research_streaming(
    run_id: str,
    phase_num: int,
    prompt: str,
    system: str,
    model_names: list[str],
    queue: asyncio.Queue,
    model_tasks: dict[str, asyncio.Task],
    web_search: bool = False,
    role_specialize: bool = False,
) -> list[ModelResult]:
    """Run research across multiple models, streaming results as each finishes."""
    providers = get_providers(model_names, role="research")
    if not providers:
        return []

    scheduled_names = [p.name for p in providers]
    skipped_names = [m for m in model_names if m not in scheduled_names]
    timeout_used = providers[0].timeout if providers else settings.get_timeout_for_role("research")

    log_event(
        run_id, "research_selection",
        phase=phase_num,
        status="info",
        error=None,
        prompt=(
            f"requested={model_names}, "
            f"scheduled={scheduled_names}, "
            f"skipped={skipped_names}, "
            f"timeout={timeout_used}s"
        ),
    )

    await _emit(queue, "research_info", {
        "phase": phase_num,
        "requested": model_names,
        "scheduled": scheduled_names,
        "skipped": skipped_names,
        "timeout_seconds": timeout_used,
    })

    for p in providers:
        await _emit(queue, "model_status", {
            "model": p.name,
            "phase": phase_num,
            "status": "queued",
            "timeout_seconds": p.timeout,
        })

    task_to_model: dict[asyncio.Task, str] = {}
    for p in providers:
        # v2.2: assign each model a specialized role, so the strategist receives
        # structurally different content from each researcher. Falls back to
        # uniform system prompt if role_specialize is False (v1 behavior).
        if role_specialize:
            from synthesis.orchestrator.research_roles import build_role_system
            per_model_system = build_role_system(p.name, system)
        else:
            per_model_system = system
        task = asyncio.create_task(call_model(p, prompt, per_model_system, web_search=web_search))
        model_tasks[p.name] = task
        task_to_model[task] = p.name
        await _emit(queue, "model_status", {
            "model": p.name,
            "phase": phase_num,
            "status": "running",
        })

    results: list[ModelResult] = []
    pending = set(task_to_model.keys())

    research_timeout = settings.get_timeout_for_role("research")
    orchestration_timeout = research_timeout + 30

    try:
        while pending:
            done, pending = await asyncio.wait(
                pending,
                timeout=orchestration_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done and pending:
                for task in pending:
                    task.cancel()
                    model_name = task_to_model[task]
                    result = ModelResult(
                        model_name=model_name,
                        status="timeout",
                        response_content=None,
                        error=f"Orchestration safety timeout ({orchestration_timeout}s)",
                    )
                    results.append(result)
                    await _emit(queue, "model_result", {
                        "model": model_name,
                        "phase": phase_num,
                        "status": "timeout",
                        "response": None,
                        "error": result.error,
                        "latency_ms": 0,
                    })
                    log_event(
                        run_id, "research",
                        phase=phase_num,
                        model=model_name,
                        status="timeout",
                        error=result.error,
                    )
                pending = set()
                break

            for task in done:
                model_name = task_to_model[task]
                try:
                    result = task.result()
                    result = truncate_output(result)
                except asyncio.CancelledError:
                    result = ModelResult(
                        model_name=model_name,
                        status="cancelled",
                        response_content=None,
                        error="Cancelled by user",
                    )
                except Exception as e:
                    result = ModelResult(
                        model_name=model_name,
                        status="error",
                        response_content=None,
                        error=str(e)[:200],
                    )

                results.append(result)

                await _emit(queue, "model_result", {
                    "model": result.model_name,
                    "phase": phase_num,
                    "status": result.status,
                    "response": result.response_content[:2000] if result.response_content else None,
                    "error": result.error,
                    "latency_ms": result.latency_ms,
                })
                log_event(
                    run_id, "research",
                    phase=phase_num,
                    model=result.model_name,
                    status=result.status,
                    latency_ms=result.latency_ms,
                    prompt=prompt,
                    response=result.response_content,
                    error=result.error,
                )
    finally:
        for p in providers:
            model_tasks.pop(p.name, None)

    return results


async def run_pipeline(
    run_id: str,
    category: str,
    prompt: str,
    models: list[str],
    queue: asyncio.Queue,
    model_tasks: dict[str, asyncio.Task] | None = None,
    mode: str = "standard",
    quick_mode: bool = False,
    attachments: list[dict] | None = None,
    admin_overrides: dict | None = None,
):
    """Execute the full orchestration pipeline."""
    if model_tasks is None:
        model_tasks = {}
    if admin_overrides is None:
        admin_overrides = {}

    mode_config = settings.get_mode_config(mode)

    complexity = settings.classify_prompt_complexity(prompt, category)
    tier = settings.get_effective_tier(mode, complexity)

    force_tier = admin_overrides.get("force_tier", "auto")
    if force_tier != "auto":
        tier = force_tier

    force_web = admin_overrides.get("force_web_search", False)

    log_event(run_id, "routing", status="info",
              prompt=f"mode={mode}, complexity={complexity}, tier={tier}, admin_force_tier={force_tier}")

    mode_config = settings.get_mode_config(mode)
    mode_research_models = mode_config["research_models"]
    available_map = {m["model"] for m in settings.get_available_models()}
    effective_models = [m for m in mode_research_models if m in available_map]
    if models and set(models) != set(mode_research_models):
        effective_models = [m for m in models if m in available_map]
    if not effective_models:
        effective_models = [m for m in mode_research_models if m in available_map]

    log_event(run_id, "routing", status="info",
              error=f"complexity={complexity}, mode={mode}, tier={tier}, "
                    f"research_models={effective_models} ({len(effective_models)})")

    try:
        # ===== STEP 1: Prompt Engineer =====
        await _emit(queue, "progress_message", {"message": "Refining your prompt..."})
        await _emit(queue, "step", {"step": "prompt_engineer", "status": "running"})
        log_event(run_id, "prompt_engineer", status="running")

        pe_result = await run_prompt_engineer(
            user_prompt=prompt[:settings.max_prompt_chars],
            category=category,
            quick_mode=quick_mode,
            attachments=attachments,
            tier=tier,
        )

        refined_prompt = pe_result["refined_prompt"]
        phases = pe_result["phases"]
        scope: Scope = pe_result.get("scope") or Scope()

        admin_max_phases = admin_overrides.get("max_phases")
        if admin_max_phases and admin_max_phases > 0:
            phases = phases[:admin_max_phases]
        elif mode != "expert" and len(phases) > 1:
            phases = phases[:1]

        pe_provider = pe_result.get("provider_used", "unknown")
        pe_fallback = pe_result.get("used_fallback", False)

        pe_label = refined_prompt
        if pe_fallback:
            pe_label = f"[Fallback: {pe_provider}]\n\n{refined_prompt}"

        await _emit(queue, "step", {
            "step": "prompt_engineer",
            "status": "done",
            "result": pe_label,
            "provider": pe_provider,
            "used_fallback": pe_fallback,
        })
        # Always emit scope — even when empty — so the frontend knows to
        # hide the chips row for runs where nothing was inferred.
        await _emit(queue, "scope", {"scope": scope.to_dict()})
        log_event(run_id, "prompt_engineer", status="done",
                  response=refined_prompt,
                  prompt=f"scope={scope.to_dict()}")

        scope_block = format_scope_for_prompt(scope)

        # ===== Freshness Detection =====
        freshness = detect_freshness(prompt, category)
        freshness_instruction = get_freshness_instruction(freshness)
        use_web_search = freshness in ("required", "helpful") or force_web
        await _emit(queue, "freshness", {"level": freshness, "web_search": use_web_search})
        log_event(run_id, "freshness", status=freshness,
                  error=f"web_search={use_web_search}")

        # ===== Retrieval (key-gated; graceful fallback to empty) =====
        retrieved_sources: list = []
        source_quality_map: dict = {}
        retrieval_meta: dict = {"provider": "none", "queries": [], "configured": False}

        if use_web_search and retrieval_configured():
            await _emit(queue, "progress_message", {"message": "Searching the web for sources..."})
            await _emit(queue, "step", {"step": "retrieval", "status": "running"})
            async def _on_progress(info: dict) -> None:
                # Per-provider query/return progress. Piggyback the
                # existing progress_message channel so the UI already
                # renders the humanised line, AND emit a structured
                # `retrieval_progress` event for future UX work.
                stage = info.get("stage")
                provider = info.get("provider")
                if stage == "querying" and provider:
                    qi = info.get("query_idx", 0)
                    tq = info.get("total_queries", 1)
                    await _emit(queue, "progress_message",
                                {"message": f"Searching {provider} ({qi + 1}/{tq})..."})
                elif stage == "returned" and provider:
                    count = info.get("count", 0)
                    await _emit(queue, "progress_message",
                                {"message": f"{provider}: {count} result(s)"})
                elif stage == "fusing":
                    await _emit(queue, "progress_message",
                                {"message": "Fusing and ranking sources..."})
                await _emit(queue, "retrieval_progress", info)

            async def _on_source_added(src: dict) -> None:
                await _emit(queue, "source_added", {"source": src})

            try:
                first_phase_prompt = phases[0]["prompt"] if phases else refined_prompt
                retrieved_sources, retrieval_meta = await retrieve_sources(
                    refined_prompt=refined_prompt,
                    phase_prompt=first_phase_prompt,
                    category=category,
                    max_sources=10,
                    scope=scope,
                    on_progress=_on_progress,
                    on_source_added=_on_source_added,
                )
            except Exception as e:
                log_event(run_id, "retrieval", status="error", error=str(e)[:200])
                retrieved_sources = []

            if retrieved_sources:
                source_quality_map = score_sources(retrieved_sources)

            await _emit(queue, "sources", {
                "sources": [s.to_dict() for s in retrieved_sources],
                "provider": retrieval_meta.get("provider"),
                "providers_used": retrieval_meta.get("providers_used", []),
                "providers_returning": retrieval_meta.get("providers_returning", []),
                "per_provider_counts": retrieval_meta.get("per_provider_counts", {}),
                "queries": retrieval_meta.get("queries", []),
                "enriched": retrieval_meta.get("enriched", 0),
            })
            await _emit(queue, "source_quality", {
                "quality": {sid: q.to_dict() for sid, q in source_quality_map.items()},
            })
            await _emit(queue, "step", {"step": "retrieval", "status": "done"})
            log_event(run_id, "retrieval", status="done",
                      prompt=f"providers={retrieval_meta.get('providers_returning', [])}, "
                             f"sources={len(retrieved_sources)}, "
                             f"enriched={retrieval_meta.get('enriched', 0)}, "
                             f"per_provider={retrieval_meta.get('per_provider_counts', {})}, "
                             f"queries={retrieval_meta.get('queries', [])}")
        else:
            await _emit(queue, "sources", {"sources": [], "provider": "none", "queries": []})
            log_event(run_id, "retrieval", status="skipped",
                      error=f"use_web_search={use_web_search}, "
                            f"tavily_configured={retrieval_configured()}")

        sources_block = format_sources_for_prompt(retrieved_sources)
        valid_source_ids = [s.id for s in retrieved_sources]

        # ===== STEP 2: Phase Loop (Research + Consensus + Strategist) =====
        category_context = get_category_context(category)
        phase_syntheses = []
        all_model_outputs = []
        prior_phase_context = ""
        consensus_data: dict = {}

        await _emit(queue, "phases_info", {
            "total": len(phases),
            "names": [p["name"] for p in phases],
        })

        for phase_idx, phase in enumerate(phases):
            phase_num = phase_idx + 1
            phase_name = phase["name"]
            phase_prompt = phase["prompt"]

            await _emit(queue, "phase_progress", {
                "current": phase_num,
                "total": len(phases),
                "name": phase_name,
            })

            # --- 2a: Research (parallel, streaming) ---
            await _emit(queue, "progress_message", {"message": "Distributing across AI models..."})
            await _emit(queue, "step", {"step": "research", "status": "running"})
            log_event(run_id, "research", phase=phase_num, status="running")

            global_ctx = get_global_context()
            research_system = (
                f"You are a research agent. Provide thorough, specific analysis.\n\n"
                f"{global_ctx}\n\n"
                f"{category_context}\n\n"
                f"Be detailed, specific, and actionable. Avoid generic advice."
                f"{freshness_instruction}"
            )
            if scope_block:
                research_system += "\n\n" + scope_block
            if sources_block:
                research_system += (
                    "\n\n"
                    + sources_block
                    + "\nWhen you cite a specific fact from these sources, "
                      "reference its id in brackets like [1] so downstream "
                      "synthesis can verify it."
                )

            full_prompt = phase_prompt
            if prior_phase_context:
                full_prompt = (
                    f"{phase_prompt}\n\n"
                    f"## Context from Previous Phases\n{prior_phase_context}"
                )

            if settings.test_mode or settings.debug_mode:
                log_event(run_id, "context_merge",
                    phase=phase_num,
                    status="debug",
                    prompt=f"PHASE_PROMPT_LENGTH={len(phase_prompt)}, "
                           f"PRIOR_CONTEXT_LENGTH={len(prior_phase_context)}, "
                           f"MERGED_LENGTH={len(full_prompt)}, "
                           f"HAS_PRIOR={'yes' if prior_phase_context else 'no'}",
                )
                await _emit(queue, "debug_context", {
                    "phase": phase_num,
                    "phase_prompt_length": len(phase_prompt),
                    "prior_context_length": len(prior_phase_context),
                    "merged_prompt_length": len(full_prompt),
                    "has_prior_context": bool(prior_phase_context),
                    "tier": tier,
                    "models": effective_models,
                    "web_search": use_web_search,
                    "retrieved_source_count": len(retrieved_sources),
                })

            # Role specialization (Searcher/Quantifier/Skeptic/etc) is gated
            # by an opt-in flag separate from SYNTHESIS_V2 because eval showed
            # it regressed on most cases (likely because narrow roles lose
            # comprehensive coverage). Held back for further design work.
            import os as _os
            _role_specialize = _os.environ.get("SYNTHESIS_ROLES", "").lower() == "true"
            results = await _run_research_streaming(
                run_id=run_id,
                phase_num=phase_num,
                prompt=full_prompt,
                system=research_system,
                model_names=effective_models,
                queue=queue,
                model_tasks=model_tasks,
                web_search=use_web_search,
                role_specialize=_role_specialize,
            )

            successful = [r for r in results if r.status == "success"]
            failed_models = [r.model_name for r in results if r.status != "success"]
            expected_count = len(effective_models)
            actual_count = len(successful)

            await _emit(queue, "model_tracking", {
                "expected": expected_count,
                "completed": actual_count,
                "failed": failed_models,
                "phase": phase_num,
            })

            min_required = settings.effective_min_models
            if actual_count < min_required:
                error_msg = (
                    f"Insufficient model consensus: {actual_count}/{expected_count} succeeded, "
                    f"need >= {min_required}. "
                    f"Failed: {failed_models}"
                )
                await _emit(queue, "step", {"step": "research", "status": "error"})
                await _emit(queue, "error", {"message": error_msg})
                log_event(run_id, "research", phase=phase_num, status="error", error=error_msg)
                return

            await _emit(queue, "step", {"step": "research", "status": "done"})

            for r in results:
                all_model_outputs.append({
                    "model_name": r.model_name,
                    "status": r.status,
                    "response_content": r.response_content,
                    "latency_ms": r.latency_ms,
                    "phase": phase_num,
                })

            # --- 2b: Consensus Extraction ---
            await _emit(queue, "progress_message", {"message": "Analyzing consensus patterns..."})
            consensus_text = ""
            try:
                consensus_data = await extract_consensus(
                    question=refined_prompt,
                    model_results=successful,
                    tier=tier,
                )
                consensus_text = format_consensus_for_strategist(consensus_data)
                agreement_score = consensus_data.get("agreement_score", 0.5)
                themes_count = len(consensus_data.get("themes", []))
                contradictions_count = len(consensus_data.get("contradictions", []))
                log_event(run_id, "consensus", phase=phase_num, status="done",
                          prompt=f"agreement={agreement_score:.2f}, themes={themes_count}, "
                                 f"contradictions={contradictions_count}")
                await _emit(queue, "consensus", {
                    "phase": phase_num,
                    "agreement_score": agreement_score,
                    "themes": themes_count,
                    "contradictions": contradictions_count,
                })
            except Exception as e:
                log_event(run_id, "consensus", phase=phase_num, status="error", error=str(e)[:200])

            # --- 2c: Strategist (phase-level) ---
            await _emit(queue, "progress_message", {"message": "Synthesizing insights..."})
            await _emit(queue, "step", {"step": "strategist", "status": "running"})
            log_event(run_id, "strategist", phase=phase_num, status="running")

            synthesis = await run_strategist(
                refined_prompt=refined_prompt,
                phase_name=phase_name,
                phase_number=phase_num,
                total_phases=len(phases),
                model_results=successful,
                category=category,
                prior_phase_context=prior_phase_context,
                expected_models=expected_count,
                failed_models=failed_models,
                tier=tier,
                consensus_text=consensus_text,
            )

            phase_syntheses.append({
                "phase_name": phase_name,
                "synthesis": synthesis,
            })

            prior_phase_context += f"\n\n## {phase_name}\n{synthesis}"

            await _emit(queue, "strategist", {
                "phase": phase_num,
                "phase_name": phase_name,
                "result": synthesis,
            })
            await _emit(queue, "step", {"step": "strategist", "status": "done"})
            log_event(run_id, "strategist", phase=phase_num, status="done", response=synthesis)

        # ===== OPTIONAL: Grounded Red Team Critique =====
        red_team_critique = None
        if consensus_data and should_trigger_red_team(consensus_data, category):
            await _emit(queue, "progress_message", {"message": "Running critical analysis..."})
            log_event(run_id, "red_team", status="running")
            try:
                last_synthesis = phase_syntheses[-1]["synthesis"] if phase_syntheses else ""
                red_team_critique = await run_red_team(
                    question=prompt,
                    strategy=last_synthesis,
                    consensus=consensus_data,
                    tier=tier,
                    sources_block=sources_block,
                )
                if red_team_critique:
                    log_event(run_id, "red_team", status="done",
                              response=red_team_critique[:500])
                    await _emit(queue, "red_team", {"critique": red_team_critique[:500]})
            except Exception as e:
                log_event(run_id, "red_team", status="error", error=str(e)[:200])

        # ===== Confidence Decomposition =====
        # Pre-DM confidence based on all current signals. The DM may tighten
        # the set of cited ids; we recompute after the report is parsed.
        pre_confidence = compute_confidence(
            sources=retrieved_sources,
            quality=source_quality_map,
            cited_source_ids=set(valid_source_ids),
            consensus=consensus_data or {},
            freshness_need=freshness,
        )

        # ===== STEP 3: Decision-Maker (cross-phase, structured output) =====
        await _emit(queue, "progress_message", {"message": "Synthesizing final answer..."})
        await _emit(queue, "step", {"step": "decision_maker", "status": "running"})
        log_event(run_id, "decision_maker", status="running")

        dm_syntheses = phase_syntheses
        if red_team_critique:
            dm_syntheses = phase_syntheses + [{
                "phase_name": "Critical Analysis (Red Team)",
                "synthesis": red_team_critique,
            }]

        structured_report, final_output_raw = await run_decision_maker(
            original_prompt=prompt,
            phase_syntheses=dm_syntheses,
            category=category,
            confidence=pre_confidence,
            tier=tier,
            sources_block=sources_block,
            valid_source_ids=valid_source_ids,
            scope_block=scope_block,
        )

        # Recompute confidence using the actually cited source ids from the
        # DM's report — tightens evidence_quantity + corroboration.
        cited_ids = collect_cited_source_ids(structured_report)
        final_confidence = compute_confidence(
            sources=retrieved_sources,
            quality=source_quality_map,
            cited_source_ids=cited_ids,
            consensus=consensus_data or {},
            freshness_need=freshness,
        )
        structured_report.confidence = final_confidence

        # ===== Per-claim verification (cheap LLM pass) =====
        # Runs only when retrieval found sources AND the DM produced a
        # non-empty evidence table with cited rows. Annotates each row's
        # .verification field in place. Never raises.
        verification_stats = {"verified": 0, "supported": 0, "partial": 0, "unsupported": 0}
        if retrieved_sources and structured_report.evidence_table:
            try:
                await _emit(queue, "progress_message",
                            {"message": "Verifying cited claims..."})
                verification_stats = await verify_evidence_rows(
                    report=structured_report,
                    sources=retrieved_sources,
                )
                log_event(run_id, "verification", status="done",
                          prompt=f"{verification_stats}")
                await _emit(queue, "verification", verification_stats)
            except Exception as e:
                log_event(run_id, "verification", status="error",
                          error=str(e)[:200])

        # Emit both the raw decision text (back-compat) and the new structured report.
        await _emit(queue, "decision", {"result": final_output_raw})
        await _emit(queue, "structured_report", {
            "report": structured_report.to_dict(),
            "sources": [s.to_dict() for s in retrieved_sources],
            "source_quality": {sid: q.to_dict() for sid, q in source_quality_map.items()},
            "scope": scope.to_dict(),
            "verification": verification_stats,
        })
        await _emit(queue, "step", {"step": "decision_maker", "status": "done"})
        log_event(run_id, "decision_maker", status="done",
                  response=final_output_raw[:2000] if final_output_raw else "",
                  prompt=f"cited_ids={sorted(cited_ids)}, "
                         f"confidence_band={final_confidence.band}, "
                         f"source_count={len(retrieved_sources)}")

        # ===== COST TRACKING =====
        try:
            model_costs = []
            total_cost = 0.0
            for mo in all_model_outputs:
                if mo.get("status") == "success" and mo.get("response_content"):
                    c = estimate_cost(
                        mo["model_name"],
                        len(prompt) + 500,
                        len(mo["response_content"]),
                    )
                    model_costs.append({"model": mo["model_name"], "cost_usd": round(c, 6)})
                    total_cost += c
            log_run_cost(run_id, model_costs, total_cost, mode=mode, tier=tier)
        except Exception:
            pass

        # ===== SAVE HISTORY =====
        try:
            all_strategist = "\n\n".join(
                f"## {ps['phase_name']}\n{ps['synthesis']}" for ps in phase_syntheses
            )
            save_run(
                run_id=run_id,
                category=category,
                original_prompt=prompt,
                refined_prompt=refined_prompt,
                models=models,
                strategist_output=all_strategist,
                decision_output=final_output_raw,
                mode=mode,
                quick_mode=quick_mode,
                attachments=attachments,
                model_outputs=all_model_outputs,
            )
        except Exception as e:
            log_event(run_id, "history", status="error", error=f"Failed to save: {e}")

        # ===== DONE =====
        await _emit(queue, "done", {"run_id": run_id, "mode": mode})
        log_event(run_id, "pipeline", status="done")

    except asyncio.CancelledError:
        await _emit(queue, "error", {"message": "Run cancelled"})
        log_event(run_id, "pipeline", status="cancelled")
    except Exception as e:
        error_msg = f"Pipeline error: {str(e)[:500]}"
        await _emit(queue, "error", {"message": error_msg})
        log_event(run_id, "pipeline", status="error", error=error_msg)
