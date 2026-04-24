"""
Advisory-session store. One row per session in history/advisory_sessions.jsonl.

Two persistence modes:
  1. `start_session(raw_input, email)` — creates a new session, runs Intake
     + Clarifier, returns the session (awaiting user answers).
  2. `submit_answers(run_id, answers)` — records the answers and returns the
     session ready for the pipeline orchestrator to pick up.

The pipeline orchestrator (phronesis.advisory.pipeline) is the only place
that mutates the `report` field. Everything else lives here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import (
    AdvisorySession,
    AdvisoryStage,
    ClarifyingQuestion,
    IntakeResult,
    UserAnswer,
)


_FILE = Path("history/advisory_sessions.jsonl")


# ═══════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════


def _to_row(session: AdvisorySession) -> dict[str, Any]:
    return asdict(session)


def _from_row(row: dict[str, Any]) -> AdvisorySession:
    # Manual construction so we can gracefully handle added fields in newer rows.
    intake = None
    if row.get("intake"):
        intake = IntakeResult(**row["intake"])
    clarifying = [ClarifyingQuestion(**q) for q in row.get("clarifying_questions", [])]
    answers = [UserAnswer(**a) for a in row.get("user_answers", [])]

    # Criteria/evidence/agent_outputs/report are plain dicts — we re-instantiate
    # lazily only when the pipeline needs them. For storage round-trip this
    # dict→dict passthrough is fine.
    from .types import CriteriaItem, EvidenceItem, AgentOutput, FinalAdviceReport, RankingOption

    criteria = [CriteriaItem(**c) for c in row.get("criteria", [])]
    evidence = [EvidenceItem(**e) for e in row.get("evidence", [])]
    outputs = [AgentOutput(**o) for o in row.get("agent_outputs", [])]

    report = None
    r = row.get("report")
    if r:
        ranked = [RankingOption(**ro) for ro in r.get("ranked_options", [])]
        r_copy = dict(r); r_copy["ranked_options"] = ranked
        report = FinalAdviceReport(**r_copy)

    return AdvisorySession(
        run_id=row["run_id"],
        user_email=row.get("user_email"),
        created_at=row["created_at"],
        raw_input=row["raw_input"],
        stage=row.get("stage", AdvisoryStage.INTAKE.value),
        error=row.get("error"),
        intake=intake,
        clarifying_questions=clarifying,
        user_answers=answers,
        category=row.get("category"),
        category_confidence=row.get("category_confidence", 0.0),
        category_user_corrected=row.get("category_user_corrected", False),
        criteria=criteria,
        evidence=evidence,
        agent_outputs=outputs,
        report=report,
        total_cost_usd=row.get("total_cost_usd", 0.0),
        total_latency_ms=row.get("total_latency_ms", 0),
    )


def save_session(session: AdvisorySession) -> None:
    """Append the latest session state. Sessions are append-only; readers
    reconstruct the final state from the last row with a given run_id."""
    _FILE.parent.mkdir(exist_ok=True)
    with open(_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(_to_row(session), ensure_ascii=False) + "\n")


def get_session(run_id: str) -> AdvisorySession | None:
    """Return the latest version of a session by run_id, or None."""
    if not _FILE.exists():
        return None
    latest: dict[str, Any] | None = None
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("run_id") == run_id:
                latest = row
    if not latest:
        return None
    return _from_row(latest)


def list_recent(limit: int = 50, user_email: str | None = None) -> list[AdvisorySession]:
    """Return recent sessions, newest first, deduped by run_id."""
    if not _FILE.exists():
        return []
    latest_per_id: dict[str, dict[str, Any]] = {}
    with open(_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            rid = row.get("run_id")
            if not rid:
                continue
            if user_email and (row.get("user_email") or "").lower() != user_email.lower():
                continue
            latest_per_id[rid] = row
    rows = list(latest_per_id.values())
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return [_from_row(r) for r in rows[:limit]]


# ═══════════════════════════════════════════════════════════════════════
# Session lifecycle (high-level helpers imported by routes.py)
# ═══════════════════════════════════════════════════════════════════════


async def start_session(
    raw_input: str,
    user_email: str | None = None,
) -> AdvisorySession:
    """Create a new session, run Intake + Clarifier, persist, return it.

    After this call the session's stage will be either:
      * AWAITING_ANSWERS (if the Clarifier produced MCQs), or
      * CRITERIA (if Intake produced enough signal to skip clarification).

    In both cases callers proceed to submit_answers() — it's a no-op when
    there are no questions.
    """
    from .agents.intake import IntakeAgent
    from .agents.clarifier import ClarifierAgent

    run_id = uuid.uuid4().hex[:8]
    session = AdvisorySession(
        run_id=run_id,
        user_email=user_email,
        created_at=datetime.now(timezone.utc).isoformat(),
        raw_input=raw_input.strip(),
    )

    # ─── Intake ───
    intake_out = await IntakeAgent().run(raw_input=session.raw_input)
    session.agent_outputs.append(intake_out)
    if intake_out.status == "error":
        session.stage = AdvisoryStage.ERROR.value
        session.error = intake_out.error
        save_session(session)
        return session

    # Intake raw JSON → typed IntakeResult
    i = intake_out.raw or {}
    session.intake = IntakeResult(
        advisory_question=i.get("advisory_question", raw_input[:200]),
        options=i.get("options", []),
        user_goal=i.get("user_goal", ""),
        constraints=i.get("constraints", []),
        timeline=i.get("timeline"),
        budget=i.get("budget"),
        risk_tolerance=i.get("risk_tolerance"),
        emotional_context=i.get("emotional_context"),
        missing_info=i.get("missing_info", []),
        confidence=float(i.get("confidence", 0.5)),
        inferred_category=i.get("inferred_category"),
    )
    session.category = session.intake.inferred_category
    session.category_confidence = session.intake.confidence

    session.stage = AdvisoryStage.CLARIFY.value

    # ─── Clarifier ───
    clarify_out = await ClarifierAgent().run(session=session)
    session.agent_outputs.append(clarify_out)

    qs = []
    for q in (clarify_out.raw or {}).get("questions", []):
        if not q.get("question") or not q.get("options"):
            continue
        qs.append(ClarifyingQuestion(
            id=q.get("id") or f"q_{len(qs)+1}",
            question=q["question"],
            options=q["options"][:6],
            help_text=q.get("help_text", ""),
            allow_skip=bool(q.get("allow_skip", True)),
            rationale=q.get("rationale", ""),
        ))
    session.clarifying_questions = qs[:5]  # hard cap per spec

    if session.clarifying_questions:
        session.stage = AdvisoryStage.AWAITING_ANSWERS.value
    else:
        session.stage = AdvisoryStage.CATEGORY.value

    save_session(session)
    return session


def submit_answers(run_id: str, answers: list[dict[str, Any]]) -> AdvisorySession | None:
    """Record the user's MCQ answers. Returns the updated session or None if not found."""
    session = get_session(run_id)
    if not session:
        return None

    q_ids = {q.id for q in session.clarifying_questions}
    session.user_answers = [
        UserAnswer(question_id=a.get("question_id", ""), answer=a.get("answer"))
        for a in answers
        if a.get("question_id") in q_ids
    ]
    session.stage = AdvisoryStage.CATEGORY.value
    save_session(session)
    return session


def record_category_correction(run_id: str, category: str | None) -> AdvisorySession | None:
    """User clicked 'Change' on the inferred category."""
    session = get_session(run_id)
    if not session:
        return None
    session.category = category
    session.category_user_corrected = True
    save_session(session)
    return session
