"""
Tests for the golden-set eval harness.

Focus: deterministic judges (citation_validity, structural,
freshness_alignment, confidence_consistency) + scorecard aggregation.
LLM judges are exercised with a mock call_fn.

All tests run in-process against constructed run records — no real
pipeline, no API calls.

Run:
    python -m tests.test_evals
    # or pytest -q tests/test_evals.py
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


from evals.judges import (
    citation_validity,
    structural,
    freshness_alignment,
    confidence_consistency,
    factuality,
)
from evals.judges.base import JudgeResult, JudgeVerdict
from evals.scorecard import build_scorecard, render


checks: list[tuple[str, bool, str]] = []


def check(name: str, cond, detail: str = ""):
    checks.append((name, bool(cond), detail))
    prefix = "PASS" if cond else "FAIL"
    suffix = f" — {detail}" if detail and not cond else ""
    print(f"  {prefix}: {name}{suffix}")


def _record(**over) -> dict:
    """Sensible default record — all judges PASS on it."""
    base = {
        "prompt_id": "test",
        "expectations": {"needs_freshness": True},
        "freshness_level": "required",
        "retrieval_configured": True,
        "sources": [
            {"id": 1, "published": "2026-01-10", "title": "T1",
             "domain": "a.com", "snippet": "s1", "full_content": "body1"},
            {"id": 2, "published": "2026-02-01", "title": "T2",
             "domain": "b.com", "snippet": "s2", "full_content": None},
        ],
        "source_quality": {},
        "report": {
            "executive_summary": "One. Two.",
            "key_findings": [
                {"finding": "Grounded finding.", "citations": [1], "strength": "strong"},
                {"finding": "Second grounded finding.", "citations": [2], "strength": "moderate"},
            ],
            "evidence_table": [{"claim": "a", "citations": [1], "strength": "strong", "note": ""}],
            "source_confidence_note": "",
            "contradictions": [],
            "risks_unknowns": [],
            "recommendation": "Go with A.",
            "what_could_change": [],
            "next_actions": [],
            "confidence": {
                "band": "moderate-high",
                "components": {
                    "source_quality": 0.7, "evidence_quantity": 0.8,
                    "source_agreement": 0.6, "freshness": 0.85,
                    "contradiction_penalty": 0.1, "model_consensus": 0.72,
                },
                "rationale": "",
            },
        },
    }
    base.update(over)
    return base


# ───── citation_validity ─────

def test_citation_validity_passes_when_all_valid():
    print("\n[citation_validity] PASS on valid citations")
    r = asyncio.run(citation_validity.judge(_record()))
    check("verdict is PASS", r.verdict == JudgeVerdict.PASS, f"got {r.verdict}")
    check("score 1.0", r.score == 1.0)


def test_citation_validity_fails_on_invented_ids():
    print("\n[citation_validity] FAIL on invented citation ids")
    bad = _record()
    bad["report"]["key_findings"][0]["citations"] = [99]
    r = asyncio.run(citation_validity.judge(bad))
    check("verdict is FAIL", r.verdict == JudgeVerdict.FAIL)
    check("invented list populated",
          r.details.get("invented") and r.details["invented"][0]["citation"] == 99)


def test_citation_validity_warns_on_unsupported_factual_claim():
    print("\n[citation_validity] WARN on uncited factual claim")
    bad = _record()
    # A claim with specific number, no citation, no unverified prefix.
    bad["report"]["key_findings"] = [
        {"finding": "Revenue hit $42M in 2026.", "citations": [], "strength": "moderate"},
    ]
    r = asyncio.run(citation_validity.judge(bad))
    check("verdict is WARN", r.verdict == JudgeVerdict.WARN, f"got {r.verdict}")


def test_citation_validity_accepts_unverified_prefix():
    print("\n[citation_validity] PASS when factual claim is explicitly unverified")
    ok = _record()
    ok["report"]["key_findings"] = [
        {"finding": "(model reasoning — unverified): likely 20% margin.",
         "citations": [], "strength": "weak"},
    ]
    r = asyncio.run(citation_validity.judge(ok))
    check("verdict is PASS", r.verdict == JudgeVerdict.PASS)


# ───── structural ─────

def test_structural_fails_on_missing_executive_summary():
    print("\n[structural] FAIL when executive_summary missing")
    bad = _record()
    bad["report"]["executive_summary"] = ""
    r = asyncio.run(structural.judge(bad))
    check("verdict FAIL", r.verdict == JudgeVerdict.FAIL)
    check("lists missing", "executive_summary" in r.details["missing"])


def test_structural_warns_on_single_sentence_summary():
    print("\n[structural] WARN on single-sentence executive summary")
    bad = _record()
    bad["report"]["executive_summary"] = "Just one sentence"
    r = asyncio.run(structural.judge(bad))
    check("verdict WARN", r.verdict == JudgeVerdict.WARN, f"got {r.verdict}")


def test_structural_fails_on_missing_confidence_components():
    print("\n[structural] FAIL when confidence components incomplete")
    bad = _record()
    bad["report"]["confidence"]["components"].pop("freshness")
    r = asyncio.run(structural.judge(bad))
    check("verdict FAIL", r.verdict == JudgeVerdict.FAIL)


def test_structural_passes_on_healthy_report():
    print("\n[structural] PASS on full report")
    r = asyncio.run(structural.judge(_record()))
    check("verdict PASS", r.verdict == JudgeVerdict.PASS)


# ───── freshness_alignment ─────

def test_freshness_alignment_skips_when_retrieval_off():
    print("\n[freshness_alignment] SKIP when retrieval not configured")
    r = asyncio.run(freshness_alignment.judge(_record(retrieval_configured=False)))
    check("verdict SKIP", r.verdict == JudgeVerdict.SKIP)


def test_freshness_alignment_passes_on_recent_sources():
    print("\n[freshness_alignment] PASS on recent dated sources")
    r = asyncio.run(freshness_alignment.judge(_record()))
    check("verdict PASS", r.verdict == JudgeVerdict.PASS)


def test_freshness_alignment_warns_on_stale_sources():
    print("\n[freshness_alignment] WARN when most sources stale")
    stale = _record()
    stale["sources"] = [
        {"id": 1, "published": "2019-01-10"},
        {"id": 2, "published": "2018-02-01"},
    ]
    r = asyncio.run(freshness_alignment.judge(stale))
    check("verdict WARN", r.verdict == JudgeVerdict.WARN, f"got {r.verdict}")


def test_freshness_alignment_fails_when_detector_mismatches():
    print("\n[freshness_alignment] FAIL when detector says not_needed on a fresh-required prompt")
    bad = _record(freshness_level="not_needed")
    r = asyncio.run(freshness_alignment.judge(bad))
    check("verdict FAIL", r.verdict == JudgeVerdict.FAIL)


def test_freshness_alignment_warns_on_empty_sources_when_fresh_required():
    print("\n[freshness_alignment] WARN on empty sources for a fresh-required prompt")
    empty = _record(sources=[])
    r = asyncio.run(freshness_alignment.judge(empty))
    check("verdict WARN", r.verdict == JudgeVerdict.WARN)


# ───── confidence_consistency ─────

def test_confidence_consistency_passes_on_matching_band():
    print("\n[confidence_consistency] PASS when band matches components")
    r = asyncio.run(confidence_consistency.judge(_record()))
    check("verdict PASS", r.verdict == JudgeVerdict.PASS)


def test_confidence_consistency_warns_on_one_step_drift():
    print("\n[confidence_consistency] WARN on 1-step band drift")
    rec = _record()
    rec["report"]["confidence"]["band"] = "high"   # components recompute to moderate-high
    r = asyncio.run(confidence_consistency.judge(rec))
    check("verdict WARN", r.verdict == JudgeVerdict.WARN, f"got {r.verdict}")


def test_confidence_consistency_fails_on_band_far_from_components():
    print("\n[confidence_consistency] FAIL on large band drift")
    rec = _record()
    rec["report"]["confidence"]["band"] = "low"
    r = asyncio.run(confidence_consistency.judge(rec))
    check("verdict FAIL", r.verdict == JudgeVerdict.FAIL)


def test_confidence_consistency_enforces_safety_ceiling():
    print("\n[confidence_consistency] FAIL when empty-sources band exceeds ceiling")
    rec = _record(sources=[])
    rec["expectations"] = {"max_band_without_sources": "moderate"}
    # Make the components recompute to the same band so only the ceiling trips.
    rec["report"]["confidence"]["band"] = "moderate-high"
    rec["report"]["confidence"]["components"] = {
        "source_quality": 0.0, "evidence_quantity": 0.0,
        "source_agreement": 0.0, "freshness": 0.0,
        "contradiction_penalty": 0.0, "model_consensus": 0.65,
    }
    r = asyncio.run(confidence_consistency.judge(rec))
    check("verdict FAIL on ceiling violation",
          r.verdict == JudgeVerdict.FAIL, f"got {r.verdict}")


# ───── factuality (LLM judge, mocked) ─────

async def _mock_call_all_supported(prompt: str, system: str):
    return ('{"verdict":"supported","reason":"ok"}', "mock")


async def _mock_call_all_unsupported(prompt: str, system: str):
    return ('{"verdict":"unsupported","reason":"not in snippet"}', "mock")


def test_factuality_skips_when_call_fn_none():
    print("\n[factuality] SKIP when call_fn is None (CI default)")
    r = asyncio.run(factuality.judge(_record(), call_fn=None))
    check("verdict SKIP", r.verdict == JudgeVerdict.SKIP)


def test_factuality_passes_when_all_supported():
    print("\n[factuality] PASS when all findings supported")
    r = asyncio.run(factuality.judge(_record(), call_fn=_mock_call_all_supported))
    check("verdict PASS", r.verdict == JudgeVerdict.PASS, f"got {r.verdict}")
    check("supported count == 2", r.details["counts"]["supported"] == 2)


def test_factuality_fails_when_all_unsupported():
    print("\n[factuality] FAIL when all findings unsupported")
    r = asyncio.run(factuality.judge(_record(), call_fn=_mock_call_all_unsupported))
    check("verdict FAIL", r.verdict == JudgeVerdict.FAIL, f"got {r.verdict}")


def test_factuality_skips_when_no_cited_findings():
    print("\n[factuality] SKIP when no cited findings")
    rec = _record()
    rec["report"]["key_findings"] = [
        {"finding": "uncited", "citations": [], "strength": "weak"},
    ]
    r = asyncio.run(factuality.judge(rec, call_fn=_mock_call_all_supported))
    check("verdict SKIP", r.verdict == JudgeVerdict.SKIP)


# ───── scorecard ─────

def _j(name: str, v: str, score: float = 1.0):
    return JudgeResult(judge=name, verdict=JudgeVerdict(v), score=score)


def test_scorecard_pass_happy_path():
    print("\n[scorecard] overall PASS when everything passes")
    records = [
        {"prompt_id": "p1", "judges": [
            _j("citation_validity", "pass"),
            _j("structural", "pass"),
            _j("freshness_alignment", "pass"),
            _j("confidence_consistency", "pass"),
        ]},
        {"prompt_id": "p2", "judges": [
            _j("citation_validity", "pass"),
            _j("structural", "pass"),
            _j("freshness_alignment", "pass"),
            _j("confidence_consistency", "pass"),
        ]},
    ]
    sc = build_scorecard(records)
    check("overall_pass_rate == 1.0", sc.overall_pass_rate == 1.0)
    check("ci_verdict PASS", sc.ci_verdict == "pass")
    check("no reasons", sc.ci_reasons == [])


def test_scorecard_fail_on_deterministic_judge_below_threshold():
    print("\n[scorecard] FAIL when a deterministic judge drops below 0.9")
    records = []
    for i in range(10):
        records.append({
            "prompt_id": f"p{i}",
            "judges": [
                _j("citation_validity", "fail" if i < 3 else "pass"),  # 70% pass
                _j("structural", "pass"),
                _j("freshness_alignment", "pass"),
                _j("confidence_consistency", "pass"),
            ],
        })
    sc = build_scorecard(records)
    check("CI verdict FAIL", sc.ci_verdict == "fail")
    check("reason mentions citation_validity",
          any("citation_validity" in r for r in sc.ci_reasons))


def test_scorecard_skip_not_counted():
    print("\n[scorecard] SKIP verdicts excluded from pass rate")
    records = [
        {"prompt_id": "p1", "judges": [
            _j("factuality", "skip"),
            _j("structural", "pass"),
        ]},
    ]
    sc = build_scorecard(records)
    # factuality skipped -> denominator 0 -> pass rate 0 but filtered. Our impl returns 0.
    check("factuality pass_rate 0.0 (all skipped)",
          sc.per_judge_pass_rate["factuality"] == 0.0)
    check("structural 1.0", sc.per_judge_pass_rate["structural"] == 1.0)
    check("overall_pass_rate 1.0 (prompt overall 'pass' since no fails)",
          sc.overall_pass_rate == 1.0)


def test_scorecard_render_produces_output():
    print("\n[scorecard] render produces a non-empty string")
    records = [{"prompt_id": "p1", "judges": [_j("structural", "pass")]}]
    sc = build_scorecard(records)
    out = render(sc)
    check("contains header", "Synthesis Golden-Set Scorecard" in out)
    check("contains verdict line", "CI verdict" in out)
    check("contains per-prompt row", "p1" in out)


# ───── runner ─────

def main():
    tests = [
        test_citation_validity_passes_when_all_valid,
        test_citation_validity_fails_on_invented_ids,
        test_citation_validity_warns_on_unsupported_factual_claim,
        test_citation_validity_accepts_unverified_prefix,
        test_structural_fails_on_missing_executive_summary,
        test_structural_warns_on_single_sentence_summary,
        test_structural_fails_on_missing_confidence_components,
        test_structural_passes_on_healthy_report,
        test_freshness_alignment_skips_when_retrieval_off,
        test_freshness_alignment_passes_on_recent_sources,
        test_freshness_alignment_warns_on_stale_sources,
        test_freshness_alignment_fails_when_detector_mismatches,
        test_freshness_alignment_warns_on_empty_sources_when_fresh_required,
        test_confidence_consistency_passes_on_matching_band,
        test_confidence_consistency_warns_on_one_step_drift,
        test_confidence_consistency_fails_on_band_far_from_components,
        test_confidence_consistency_enforces_safety_ceiling,
        test_factuality_skips_when_call_fn_none,
        test_factuality_passes_when_all_supported,
        test_factuality_fails_when_all_unsupported,
        test_factuality_skips_when_no_cited_findings,
        test_scorecard_pass_happy_path,
        test_scorecard_fail_on_deterministic_judge_below_threshold,
        test_scorecard_skip_not_counted,
        test_scorecard_render_produces_output,
    ]
    for t in tests:
        t()

    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    print(f"\n{'-' * 60}")
    print(f"Evals tests: {passed}/{total} passed")
    if passed != total:
        failures = [n for n, ok, _ in checks if not ok]
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL PASSED")


if __name__ == "__main__":
    main()
