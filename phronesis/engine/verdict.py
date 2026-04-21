"""
Verdict logic — computes confidence and generates recommendation summary.
v3: Recalibrated confidence formula based on benchmark analysis.
"""

from phronesis.engine.types import DecisionResult, RankedOption


def compute_confidence(
    judge_count: int,
    judges_agree: bool,
    ranked_options: list[RankedOption],
) -> tuple[float, str]:
    """Compute confidence score (0-100) and level.

    v3 calibration fixes:
    - Spread is the PRIMARY signal (was under-weighted)
    - Agreement is a MODIFIER, not a primary factor (was over-weighted)
    - 2 judges is acceptable, not heavily penalized (was too harsh)
    - Score and agreement must be CONSISTENT (high agreement + low spread = capped)
    """
    if not ranked_options:
        return 30, "low"

    # ─── Base: Score spread (PRIMARY signal, 0-40 points) ───
    spread = 0.0
    if len(ranked_options) >= 2:
        spread = ranked_options[0].final_score - ranked_options[1].final_score

    if spread >= 2.5:
        spread_score = 40   # dominant winner
    elif spread >= 1.5:
        spread_score = 32
    elif spread >= 1.0:
        spread_score = 25
    elif spread >= 0.5:
        spread_score = 18
    elif spread >= 0.2:
        spread_score = 10   # slight edge
    else:
        spread_score = 0    # essentially tied

    # ─── Judge reliability (0-25 points) ───
    if judge_count >= 3:
        judge_score = 25
    elif judge_count == 2:
        judge_score = 18    # 2 judges is fine, not heavily penalized
    elif judge_count == 1:
        judge_score = 5
    else:
        judge_score = 0

    # ─── Agreement modifier (-10 to +15) ───
    # Agreement only matters when multiple judges responded
    if judge_count >= 2:
        if judges_agree:
            agree_mod = 15
        else:
            agree_mod = -5
    else:
        agree_mod = 0  # single judge can't agree/disagree

    # ─── Consistency check: cap confidence when signals conflict ───
    # High agreement but tiny spread = can't be very confident
    if judges_agree and spread < 0.3 and judge_count >= 2:
        agree_mod = min(agree_mod, 5)  # cap agreement bonus

    # Low agreement but huge spread = still reasonably confident
    if not judges_agree and spread >= 1.5:
        agree_mod = max(agree_mod, 0)  # don't penalize

    # ─── Option count adjustment (-5 to 0) ───
    n_options = len(ranked_options)
    option_adj = -3 if n_options >= 6 else -1 if n_options >= 4 else 0

    # ─── Final score ───
    score = 25 + spread_score + judge_score + agree_mod + option_adj  # baseline 25
    score = max(15, min(92, round(score)))

    if score >= 70:
        level = "high"
    elif score >= 50:
        level = "moderate"
    else:
        level = "low"

    return score, level


def build_recommendation(result: dict, ranked_options: list[RankedOption]) -> str:
    """Build a concise, decisive recommendation. Fallback when synthesizer is unavailable."""
    explanations = result.get("explanations", [])

    if explanations and ranked_options:
        winner_name = ranked_options[0].option.lower()
        matching = [e for e in explanations if winner_name in e.lower() or ranked_options[0].option in e]
        best = matching[0] if matching else explanations[0]
        sentences = [s.strip() for s in best.replace('\n', ' ').split('.') if s.strip()]
        if len(sentences) > 3:
            sentences = sentences[:3]
        return '. '.join(sentences) + '.'

    if not ranked_options:
        return "Unable to determine a clear recommendation."

    winner = ranked_options[0]
    parts = [f"{winner.option} is the strongest choice"]
    if winner.strengths:
        parts.append(f"primarily for its {winner.strengths[0].lower().rstrip('.')}")
    if len(ranked_options) >= 2:
        runner = ranked_options[1]
        spread = winner.final_score - runner.final_score
        if spread < 0.5:
            parts.append(f"though {runner.option} is a close alternative")
        else:
            parts.append(f"scoring {spread:.1f} points above {runner.option}")
    return '. '.join(parts) + '.'
