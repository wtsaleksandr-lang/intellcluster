"""
Aggregate judge scores for decision options.
Ported from ai-orchestrator evaluation/aggregator.py — adapted for option ranking.
"""


def _resolve_label(label: str, key_map: dict[str, str]) -> str:
    """Resolve an anonymized label to the original option text.
    Handles exact match, case-insensitive match, and partial match.
    """
    # Exact match
    if label in key_map:
        return key_map[label]

    # Case-insensitive
    label_lower = label.lower().strip()
    for k, v in key_map.items():
        if k.lower().strip() == label_lower:
            return v

    # Partial match (e.g., "A" matches "Option A")
    for k, v in key_map.items():
        if label_lower in k.lower() or k.lower() in label_lower:
            return v

    # If label looks like "Option X" pattern, it's an unresolved anonymized label — return it
    # but flag it so we know
    return label


def aggregate_decision_results(
    question: str,
    judge_results: list[dict],
    key_map: dict[str, str],
    dimensions: list[dict],
) -> dict:
    """Aggregate judge scores for a decision.

    Returns:
        {
            "question": ...,
            "options": {
                "Option text": {"avg_scores": {...}, "rank_points": int, "strength": ..., "weakness": ...},
                ...
            },
            "winner": str,
            "judges_agree": bool,
            "judge_count": int,
            "explanations": [str],
        }
    """
    label_to_option = key_map  # "Option A" -> "actual option text"
    dim_names = [d["name"] for d in dimensions]

    # Collect scores per option
    option_scores = {}     # option_text -> {dim -> [scores]}
    option_rank_points = {}  # option_text -> [rank_points]
    option_strengths = {}  # option_text -> [strengths]
    option_weaknesses = {} # option_text -> [weaknesses]
    explanations = []

    for judge_result in judge_results:
        if "error" in judge_result:
            continue

        evals = judge_result.get("evaluations", {})
        ranking = judge_result.get("ranking", [])
        explanation = judge_result.get("explanation", "")
        if explanation:
            explanations.append(explanation)

        for label, scores in evals.items():
            option_text = _resolve_label(label, label_to_option)
            if option_text not in option_scores:
                option_scores[option_text] = {d: [] for d in dim_names}
                option_rank_points[option_text] = []
                option_strengths[option_text] = []
                option_weaknesses[option_text] = []

            for dim_name in dim_names:
                val = scores.get(dim_name)
                if isinstance(val, (int, float)):
                    option_scores[option_text][dim_name].append(val)

            if scores.get("strength"):
                option_strengths[option_text].append(scores["strength"])
            if scores.get("weakness"):
                option_weaknesses[option_text].append(scores["weakness"])

        # Rank points: 1st place = N, 2nd = N-1, etc.
        for rank_pos, label in enumerate(ranking):
            option_text = _resolve_label(label, label_to_option)
            if option_text not in option_rank_points:
                option_rank_points[option_text] = []
            option_rank_points[option_text].append(len(ranking) - rank_pos)

    # Calculate averages and build result
    options = {}
    for option_text, dims in option_scores.items():
        avg = {}
        for dim_name, scores in dims.items():
            avg[dim_name] = round(sum(scores) / len(scores), 2) if scores else 0
        avg["overall"] = round(sum(avg.values()) / len(avg), 2) if avg else 0

        rank_pts = option_rank_points.get(option_text, [])
        options[option_text] = {
            "avg_scores": avg,
            "rank_points": sum(rank_pts),
            "times_ranked_first": sum(1 for p in rank_pts if p == max(rank_pts)) if rank_pts else 0,
            "strengths": list(set(option_strengths.get(option_text, []))),
            "weaknesses": list(set(option_weaknesses.get(option_text, []))),
        }

    # Determine winner
    if options:
        all_zero = all(options[o]["avg_scores"].get("overall", 0) == 0 for o in options)
        if all_zero:
            winner = max(options, key=lambda o: options[o].get("rank_points", 0))
        else:
            winner = max(options, key=lambda o: (
                options[o]["avg_scores"].get("overall", 0),
                options[o].get("rank_points", 0),
            ))
    else:
        winner = "none"

    # Check judge agreement
    judge_winners = []
    for jr in judge_results:
        if "error" not in jr and jr.get("ranking"):
            first_label = jr["ranking"][0]
            judge_winners.append(label_to_option.get(first_label, first_label))
    judges_agree = len(set(judge_winners)) <= 1 if judge_winners else False

    return {
        "question": question,
        "options": options,
        "winner": winner,
        "judges_agree": judges_agree,
        "judge_count": len([j for j in judge_results if "error" not in j]),
        "explanations": explanations,
    }
