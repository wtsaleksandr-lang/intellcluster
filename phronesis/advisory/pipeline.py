"""
Advisory pipeline orchestrator.

Runs the remainder of the council AFTER the user has answered (or skipped)
the Clarifier's MCQs. Emits SSE-friendly events at each station so the UI
can light up the 6-station pipeline view in real time.

Call graph:
  run_council(session, emit) →
    Category confirm / infer  → emit 'category'
    Criteria Architect        → emit 'criteria'
    Evidence Agent            → emit 'evidence'
    Optimizer + Skeptic + Pragmatist in parallel → emits one per station
    Synthesizer               → emit 'synthesis'
    emit 'done' with full report
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any, Awaitable, Callable

from .agents import (
    CriteriaArchitectAgent,
    DomainExpertAgent,
    EvidenceAgent,
    OptimizerAgent,
    PragmatistAgent,
    SkepticAgent,
    SynthesizerAgent,
)
from .session import save_session
from .types import (
    AdvisorySession,
    AdvisoryStage,
    CriteriaItem,
    EvidenceItem,
    FinalAdviceReport,
    RankingOption,
)


EmitFn = Callable[[str, dict[str, Any]], None]


async def run_council(session: AdvisorySession, emit: EmitFn) -> AdvisorySession:
    """
    Drive every remaining stage. Updates `session` in place and persists
    after each stage so the UI can recover if the connection drops.
    """
    start_total = time.time()

    def _emit(stage: str, payload: dict[str, Any] | None = None) -> None:
        try:
            emit(stage, payload or {})
        except Exception:
            pass

    try:
        # ─── Category (confirm/infer) ───
        session.stage = AdvisoryStage.CATEGORY.value
        if not session.category:
            session.category = (session.intake.inferred_category
                                if session.intake else "exploratory")
        _emit("category", {
            "category": session.category,
            "confidence": session.category_confidence,
            "user_corrected": session.category_user_corrected,
        })
        save_session(session)

        # ─── Criteria Architect ───
        session.stage = AdvisoryStage.CRITERIA.value
        _emit("stage_start", {"stage": "criteria"})
        criteria_out = await CriteriaArchitectAgent().run(session=session)
        session.agent_outputs.append(criteria_out)
        session.criteria = [
            CriteriaItem(
                name=c.get("name", ""),
                weight=int(c.get("weight", 5) or 5),
                rationale=c.get("rationale", ""),
            )
            for c in (criteria_out.raw or {}).get("criteria", [])
            if c.get("name")
        ]
        session.total_cost_usd += criteria_out.cost_usd
        _emit("criteria", {
            "output": asdict(criteria_out),
            "criteria": [asdict(c) for c in session.criteria],
        })
        save_session(session)

        if not session.criteria:
            raise RuntimeError("Criteria Architect returned no criteria")

        # ─── Evidence Agent ───
        session.stage = AdvisoryStage.EVIDENCE.value
        _emit("stage_start", {"stage": "evidence"})
        evidence_out = await EvidenceAgent().run(session=session)
        session.agent_outputs.append(evidence_out)
        ev_raw = evidence_out.raw or {}
        evidence_items: list[EvidenceItem] = []
        for kind_key, kind in (
            ("facts_from_user", "fact_from_user"),
            ("reasonable_assumptions", "assumption"),
            ("missing_critical", "missing"),
            ("external_reference", "external"),
        ):
            for row in (ev_raw.get(kind_key) or [])[:10]:
                if not row.get("claim"):
                    continue
                evidence_items.append(EvidenceItem(
                    claim=row["claim"],
                    kind=kind,
                    confidence=row.get("confidence", "medium"),
                    source=row.get("source"),
                ))
        session.evidence = evidence_items
        session.total_cost_usd += evidence_out.cost_usd
        _emit("evidence", {
            "output": asdict(evidence_out),
            "items": [asdict(e) for e in session.evidence],
            "quality": ev_raw.get("evidence_quality", "moderate"),
        })
        save_session(session)

        # ─── Optimizer + Skeptic + Pragmatist + Domain Expert in parallel ───
        session.stage = AdvisoryStage.OPTIMIZER.value
        _emit("stage_start", {"stage": "council"})

        # Fire all four in parallel; no cross-dependency between them.
        opt_task = OptimizerAgent().run(session=session)
        prag_task = PragmatistAgent().run(session=session)
        # Skeptic knows about the Optimizer's lean only if Optimizer finishes
        # first — it's fine to pass None (prompt handles that case).
        skep_task = SkepticAgent().run(session=session, optimizer_lean=None)
        # Domain Expert persona is routed by session.category inside the agent.
        de_task = DomainExpertAgent().run(session=session)

        opt_out, skep_out, prag_out, de_out = await asyncio.gather(
            opt_task, skep_task, prag_task, de_task, return_exceptions=True
        )

        for out, label in (
            (opt_out, "optimizer"),
            (skep_out, "skeptic"),
            (prag_out, "pragmatist"),
            (de_out, "domain_expert"),
        ):
            if isinstance(out, Exception):
                # Keep the pipeline alive; record a skipped slot.
                from .types import AgentOutput as _AO
                out = _AO(agent=label, status="error", error=str(out)[:200])
            session.agent_outputs.append(out)
            session.total_cost_usd += getattr(out, "cost_usd", 0.0)
            _emit(label, {"output": asdict(out)})

        save_session(session)

        # ─── Synthesizer ───
        session.stage = AdvisoryStage.SYNTHESIS.value
        _emit("stage_start", {"stage": "synthesis"})
        synth_out = await SynthesizerAgent().run(session=session)
        session.agent_outputs.append(synth_out)
        session.total_cost_usd += synth_out.cost_usd

        if synth_out.status != "ok" or not synth_out.raw:
            raise RuntimeError(
                synth_out.error or "Synthesizer returned empty output"
            )

        report = _report_from_raw(synth_out.raw)
        session.report = report
        session.stage = AdvisoryStage.DONE.value
        session.total_latency_ms = int((time.time() - start_total) * 1000)
        save_session(session)

        _emit("done", {
            "run_id": session.run_id,
            "report": asdict(report),
            "total_cost_usd": session.total_cost_usd,
            "total_latency_ms": session.total_latency_ms,
        })

    except Exception as e:
        session.stage = AdvisoryStage.ERROR.value
        session.error = str(e)[:300]
        session.total_latency_ms = int((time.time() - start_total) * 1000)
        save_session(session)
        _emit("error", {"error": session.error})

    return session


def _report_from_raw(data: dict[str, Any]) -> FinalAdviceReport:
    """Turn the Synthesizer's JSON into a typed FinalAdviceReport."""
    ranked_raw = data.get("ranked_options") or []
    ranked: list[RankingOption] = []
    for i, r in enumerate(ranked_raw):
        if not r.get("option"):
            continue
        ranked.append(RankingOption(
            option=r["option"],
            rank=int(r.get("rank", i + 1) or (i + 1)),
            score=float(r.get("score", 0) or 0),
            strengths=list(r.get("strengths") or [])[:5],
            weaknesses=list(r.get("weaknesses") or [])[:5],
            dimension_scores=dict(r.get("dimension_scores") or {}),
            color=(r.get("color") or "yellow").lower(),
        ))
    ranked.sort(key=lambda o: (-o.score, o.rank))
    for i, opt in enumerate(ranked):
        opt.rank = i + 1

    return FinalAdviceReport(
        recommended_best_move=data.get("recommended_best_move") or "",
        why_this_wins=list(data.get("why_this_wins") or [])[:6],
        ranked_options=ranked,
        confidence_level=(data.get("confidence_level") or "moderate").lower(),
        confidence_range=data.get("confidence_range"),
        key_risks=list(data.get("key_risks") or [])[:6],
        what_could_change_this=list(data.get("what_could_change_this") or [])[:6],
        immediate_next_step=data.get("immediate_next_step") or "",
        action_ladder=list(data.get("action_ladder") or [])[:6],
        agent_consensus=dict(data.get("agent_consensus") or {}),
        consensus_level=(data.get("consensus_level") or "moderate").lower(),
    )
