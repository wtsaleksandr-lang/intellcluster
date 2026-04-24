"""
Composite confidence calculation.

Replaces the single-number `agreement_score` (which was agreement-among-LLMs
only) with a multi-component score that reflects:

    source_quality       avg overall source-quality across cited sources
    evidence_quantity    how much cited evidence backs the claims (saturates)
    source_agreement     do the sources corroborate each other (domain diversity)
    freshness            avg recency across sources (weighted toward required)
    contradiction_level  how many conflicts across sources / models (PENALTY)
    model_consensus      the existing LLM-agreement score

We output a BAND (low / moderate / moderate-high / high) rather than a
spurious percent. The ComponentScores are kept for debugging / UI.
"""

from __future__ import annotations

from typing import Any

from synthesis.orchestrator.types import ConfidenceScore, RetrievedSource, SourceQuality


# Weights. If an input is missing (no sources retrieved), the weight is
# redistributed proportionally across the components we do have.
WEIGHTS = {
    "source_quality":     0.22,
    "evidence_quantity":  0.14,
    "source_agreement":   0.14,
    "freshness":          0.12,
    "contradiction_penalty": 0.10,   # SUBTRACTED
    "model_consensus":    0.28,
}


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _evidence_quantity(cited_ids: set[int], total_sources: int) -> float:
    """Saturating curve: 0 cited → 0 ; 5+ cited → ~1.0."""
    n = len(cited_ids)
    if n == 0:
        return 0.0
    if total_sources == 0:
        return 0.0
    # Cap at 1.0, reach ~0.8 at 4 cites, ~1.0 at 6+.
    return min(1.0, 0.25 * n)


def _source_agreement(sources: list[RetrievedSource]) -> float:
    """Proxy: distinct-domain diversity. 1 domain = 0.3, 5+ distinct = 1.0."""
    if not sources:
        return 0.0
    distinct = len({s.domain for s in sources if s.domain})
    return min(1.0, 0.3 + 0.15 * (distinct - 1)) if distinct else 0.3


def _freshness_score(sources: list[RetrievedSource], quality: dict[int, SourceQuality], freshness_need: str) -> float:
    """Average recency across sources, weighted by freshness need."""
    if not sources:
        return 0.0
    recencies = [quality[s.id].recency for s in sources if s.id in quality]
    if not recencies:
        return 0.0
    avg = _avg(recencies)
    # If freshness was required, penalise mediocre averages harder.
    if freshness_need == "required":
        return max(0.0, avg - 0.1)
    return avg


def _contradiction_penalty(consensus: dict, sources: list[RetrievedSource]) -> float:
    """0 = no contradictions ; 1 = many contradictions across models AND sources.

    We penalise the band when model outputs disagree OR (future work)
    source evidence contradicts itself. For now we key off the consensus
    dict's contradictions count + agreement_score inverted.
    """
    n_contra = len(consensus.get("contradictions", []))
    agreement = float(consensus.get("agreement_score", 0.5) or 0.5)
    disagreement = 1.0 - agreement
    # Combine: each contradiction adds 0.15, capped.
    return min(1.0, disagreement * 0.6 + n_contra * 0.15)


def _band_for(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.60:
        return "moderate-high"
    if score >= 0.40:
        return "moderate"
    return "low"


def compute_confidence(
    sources: list[RetrievedSource],
    quality: dict[int, SourceQuality],
    cited_source_ids: set[int],
    consensus: dict,
    freshness_need: str,
) -> ConfidenceScore:
    """Produce the final ConfidenceScore from available signals.

    Graceful when sources/quality are empty (no retrieval configured) —
    weights redistribute so the score leans on model_consensus alone, and
    the rationale explicitly tells the user that.
    """
    # Per-component raw scores (0–1)
    sq = _avg([q.overall for q in quality.values()]) if quality else 0.0
    eq = _evidence_quantity(cited_source_ids, len(sources))
    sa = _source_agreement(sources)
    fr = _freshness_score(sources, quality, freshness_need)
    cp = _contradiction_penalty(consensus, sources)
    mc = float(consensus.get("agreement_score", 0.5) or 0.5)

    components = {
        "source_quality":     round(sq, 3),
        "evidence_quantity":  round(eq, 3),
        "source_agreement":   round(sa, 3),
        "freshness":          round(fr, 3),
        "contradiction_penalty": round(cp, 3),
        "model_consensus":    round(mc, 3),
    }

    # Active weight set: when retrieval didn't run, drop source-dependent
    # components; redistribute their weight onto model_consensus + evidence.
    active = dict(WEIGHTS)
    if not sources:
        for k in ("source_quality", "evidence_quantity", "source_agreement", "freshness"):
            active[k] = 0.0
        # Normalise remaining.
        total = sum(v for k, v in active.items() if k != "contradiction_penalty")
        if total > 0:
            factor = (1.0 - active["contradiction_penalty"]) / total
            for k in active:
                if k != "contradiction_penalty":
                    active[k] *= factor

    # Aggregate (positive minus penalty).
    positive = sum(active[k] * components[k] for k in components if k != "contradiction_penalty")
    penalty = active["contradiction_penalty"] * components["contradiction_penalty"]
    positive_weight_sum = sum(v for k, v in active.items() if k != "contradiction_penalty") or 1.0
    score = max(0.0, min(1.0, (positive / positive_weight_sum) - penalty))

    band = _band_for(score)
    rationale = _rationale(components, sources, band)

    return ConfidenceScore(
        band=band,
        components=components,
        rationale=rationale,
    )


def _rationale(components: dict[str, float], sources: list[RetrievedSource], band: str) -> str:
    pieces = []
    n = len(sources)

    if n == 0:
        pieces.append("No external sources retrieved — confidence rests on model consensus alone.")
    else:
        pieces.append(f"Based on {n} retrieved source{'s' if n != 1 else ''}.")
        sq = components["source_quality"]
        if sq >= 0.7:
            pieces.append("Source quality is strong")
        elif sq >= 0.5:
            pieces.append("Source quality is mixed")
        else:
            pieces.append("Source quality is weak")

        fr = components["freshness"]
        if fr >= 0.7:
            pieces[-1] += " and recent"
        elif fr <= 0.3:
            pieces[-1] += " and largely dated"

    cp = components["contradiction_penalty"]
    if cp >= 0.5:
        pieces.append("Contradictions between inputs reduce confidence.")
    elif cp <= 0.2 and components["model_consensus"] >= 0.6:
        pieces.append("Models largely agree.")

    return " ".join(p.rstrip(".") + "." for p in pieces if p).strip()
