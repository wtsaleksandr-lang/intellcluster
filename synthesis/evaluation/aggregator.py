"""
Aggregate judge scores and generate evaluation reports.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from synthesis.evaluation.rubric import DIMENSIONS


def aggregate_prompt_results(
    prompt_data: dict,
    judge_results: list[dict],
    key_map: dict[str, str],
) -> dict:
    """Aggregate judge scores for a single prompt.

    Returns:
        {
            "prompt_id": ...,
            "prompt_title": ...,
            "systems": {
                "orchestrator": {"avg_scores": {...}, "rank_points": int, ...},
                "standalone_openai": {...},
                ...
            },
            "winner": str,
            "judges_agree": bool,
        }
    """
    # Reverse key_map: response_label -> system_name
    label_to_system = key_map

    # Collect scores per system
    system_scores = {}  # system -> {dim -> [scores]}
    system_rank_points = {}  # system -> [rank positions]

    for judge_result in judge_results:
        if "error" in judge_result:
            continue

        evals = judge_result.get("evaluations", {})
        ranking = judge_result.get("ranking", [])

        for label, scores in evals.items():
            system = label_to_system.get(label, "unknown")
            if system not in system_scores:
                system_scores[system] = {d["name"]: [] for d in DIMENSIONS}
                system_rank_points[system] = []

            for dim in DIMENSIONS:
                val = scores.get(dim["name"])
                if isinstance(val, (int, float)):
                    system_scores[system][dim["name"]].append(val)

        # Rank points: 1st place = N points, 2nd = N-1, etc.
        for rank_pos, label in enumerate(ranking):
            system = label_to_system.get(label, "unknown")
            if system not in system_rank_points:
                system_rank_points[system] = []
            system_rank_points[system].append(len(ranking) - rank_pos)

    # Calculate averages
    systems = {}
    for system, dims in system_scores.items():
        avg = {}
        for dim_name, scores in dims.items():
            avg[dim_name] = round(sum(scores) / len(scores), 2) if scores else 0
        avg["overall"] = round(sum(avg.values()) / len(avg), 2) if avg else 0
        rank_pts = system_rank_points.get(system, [])
        systems[system] = {
            "avg_scores": avg,
            "rank_points": sum(rank_pts),
            "times_ranked_first": sum(1 for p in rank_pts if p == max(rank_pts) if rank_pts),
        }

    # Determine winner: primary = overall score, tiebreaker = rank points
    if systems:
        all_zero = all(systems[s]["avg_scores"].get("overall", 0) == 0 for s in systems)
        if all_zero:
            winner = max(systems, key=lambda s: systems[s].get("rank_points", 0))
        else:
            winner = max(systems, key=lambda s: (
                systems[s]["avg_scores"].get("overall", 0),
                systems[s].get("rank_points", 0),
            ))
    else:
        winner = "none"

    # Check judge agreement
    judge_winners = []
    for jr in judge_results:
        if "error" not in jr and jr.get("ranking"):
            first = jr["ranking"][0]
            judge_winners.append(label_to_system.get(first, "unknown"))
    judges_agree = len(set(judge_winners)) <= 1 if judge_winners else False

    return {
        "prompt_id": prompt_data.get("id"),
        "prompt_title": prompt_data.get("title"),
        "category": prompt_data.get("category"),
        "systems": systems,
        "winner": winner,
        "judges_agree": judges_agree,
        "judge_count": len([j for j in judge_results if "error" not in j]),
    }


def aggregate_full_evaluation(prompt_results: list[dict]) -> dict:
    """Aggregate results across all prompts.

    Returns:
        {
            "total_prompts": int,
            "win_counts": {"orchestrator": N, ...},
            "win_rate": {"orchestrator": 0.7, ...},
            "category_performance": {...},
            "avg_scores_overall": {...},
            "judge_agreement_rate": float,
        }
    """
    win_counts = {}
    category_wins = {}  # category -> {system -> count}
    system_totals = {}  # system -> {dim -> [all scores]}
    agree_count = 0

    for pr in prompt_results:
        winner = pr["winner"]
        win_counts[winner] = win_counts.get(winner, 0) + 1

        cat = pr.get("category", "unknown")
        if cat not in category_wins:
            category_wins[cat] = {}
        category_wins[cat][winner] = category_wins[cat].get(winner, 0) + 1

        for system, data in pr.get("systems", {}).items():
            if system not in system_totals:
                system_totals[system] = {d["name"]: [] for d in DIMENSIONS}
                system_totals[system]["overall"] = []
            for dim, val in data.get("avg_scores", {}).items():
                if dim in system_totals[system]:
                    system_totals[system][dim].append(val)

        if pr.get("judges_agree"):
            agree_count += 1

    total = len(prompt_results)
    win_rate = {s: round(c / total, 2) for s, c in win_counts.items()} if total else {}

    avg_overall = {}
    for system, dims in system_totals.items():
        avg_overall[system] = {}
        for dim, vals in dims.items():
            avg_overall[system][dim] = round(sum(vals) / len(vals), 2) if vals else 0

    return {
        "total_prompts": total,
        "win_counts": win_counts,
        "win_rate": win_rate,
        "category_performance": category_wins,
        "avg_scores_overall": avg_overall,
        "judge_agreement_rate": round(agree_count / total, 2) if total else 0,
    }


def generate_report_v2(prompt_results: list[dict], full_agg: dict,
                       cost_data: dict | None = None, speed_data: dict | None = None) -> str:
    """Generate enhanced Round 2 evaluation report with executive summary, cost, speed, verdict."""
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = full_agg["total_prompts"]

    # EXECUTIVE SUMMARY
    lines.append("# Multi-AI Orchestrator — Blind Evaluation Report (Round 2)")
    lines.append(f"\nGenerated: {now}")
    lines.append(f"Prompts evaluated: {total}")
    lines.append(f"Judge agreement rate: {full_agg['judge_agreement_rate']:.0%}")

    lines.append("\n## Executive Summary\n")
    orch_rate = full_agg["win_rate"].get("orchestrator", 0)
    orch_wins = full_agg["win_counts"].get("orchestrator", 0)
    lines.append(f"The Orchestrator won **{orch_wins} of {total}** prompts ({orch_rate:.0%} win rate).")

    # Find strongest rival
    rival_counts = {k: v for k, v in full_agg["win_counts"].items() if k != "orchestrator"}
    if rival_counts:
        top_rival = max(rival_counts, key=rival_counts.get)
        rival_display = top_rival.replace("standalone_", "").replace("_", " ").title()
        lines.append(f"Strongest rival: **{rival_display}** with {rival_counts[top_rival]} wins.")

    orch_avg = full_agg.get("avg_scores_overall", {}).get("orchestrator", {}).get("overall", 0)
    lines.append(f"Orchestrator average overall score: **{orch_avg:.1f}/10**")

    # LEADERBOARD
    lines.append("\n## Leaderboard\n")
    lines.append("| Rank | System | Wins | Win Rate | Avg Score |")
    lines.append("|------|--------|------|----------|-----------|")
    all_systems = full_agg.get("avg_scores_overall", {})
    ranked = sorted(all_systems.items(), key=lambda x: x[1].get("overall", 0), reverse=True)
    for rank, (system, scores) in enumerate(ranked, 1):
        display = system.replace("standalone_", "").replace("_", " ").title()
        wins = full_agg["win_counts"].get(system, 0)
        rate = full_agg["win_rate"].get(system, 0)
        lines.append(f"| {rank} | {display} | {wins} | {rate:.0%} | {scores.get('overall', 0):.1f} |")

    # AVERAGE SCORES
    lines.append("\n## Detailed Scores by System\n")
    dims = [d["name"] for d in DIMENSIONS] + ["overall"]
    header = "| System | " + " | ".join(d.capitalize() for d in dims) + " |"
    sep = "|--------|" + "|".join("-------" for _ in dims) + "|"
    lines.append(header)
    lines.append(sep)
    for system, scores in ranked:
        display = system.replace("standalone_", "").replace("_", " ").title()
        vals = " | ".join(f"{scores.get(d, 0):.1f}" for d in dims)
        lines.append(f"| {display} | {vals} |")

    # BY CATEGORY RESULTS
    lines.append("\n## Results by Category\n")
    cat_map = {}
    for pr in prompt_results:
        cat = pr.get("category", "unknown")
        if cat not in cat_map:
            cat_map[cat] = []
        cat_map[cat].append(pr)

    for cat, prs in cat_map.items():
        cat_display = cat.replace("_", " ").title()
        lines.append(f"### {cat_display}\n")
        for pr in prs:
            winner_display = pr["winner"].replace("standalone_", "").replace("_", " ").title()
            agree = "unanimous" if pr.get("judges_agree") else "split"
            lines.append(f"- **{pr['prompt_title']}**: Winner = {winner_display} ({agree})")
        lines.append("")

    # COST VS QUALITY TABLE
    if cost_data:
        lines.append("\n## Cost vs Quality\n")
        lines.append("| System | Avg Cost/Prompt | Avg Score | Cost per Quality Point |")
        lines.append("|--------|----------------|-----------|----------------------|")
        for system in ranked:
            sys_name = system[0]
            display = sys_name.replace("standalone_", "").replace("_", " ").title()
            cost = cost_data.get(sys_name, {}).get("avg_cost", 0)
            score = system[1].get("overall", 0)
            cpp = cost / score if score > 0 else 0
            lines.append(f"| {display} | ${cost:.4f} | {score:.1f} | ${cpp:.4f} |")

    # RESPONSE SPEED TABLE
    if speed_data:
        lines.append("\n## Response Speed\n")
        lines.append("| System | Avg Response Time | Fastest | Slowest |")
        lines.append("|--------|-------------------|---------|---------|")
        for sys_name, data in speed_data.items():
            display = sys_name.replace("standalone_", "").replace("_", " ").title()
            lines.append(f"| {display} | {data.get('avg', 0):.1f}s | {data.get('min', 0):.1f}s | {data.get('max', 0):.1f}s |")

    # PER-PROMPT DETAILS
    lines.append("\n## Per-Prompt Results\n")
    for pr in prompt_results:
        winner_display = pr["winner"].replace("standalone_", "").replace("_", " ").title()
        agree_str = "Yes (unanimous)" if pr.get("judges_agree") else "No (split)"
        lines.append(f"### {pr['prompt_id']}: {pr['prompt_title']}")
        lines.append(f"- Category: {pr.get('category', 'N/A')}")
        lines.append(f"- Winner: **{winner_display}**")
        lines.append(f"- Judges agree: {agree_str}")

        if pr.get("systems"):
            lines.append("")
            lines.append("| System | Clarity | Depth | Action. | Reason. | Useful | Overall |")
            lines.append("|--------|---------|-------|---------|---------|--------|---------|")
            sys_sorted = sorted(pr["systems"].items(), key=lambda x: x[1].get("avg_scores", {}).get("overall", 0), reverse=True)
            for system, data in sys_sorted:
                sc = data.get("avg_scores", {})
                display = system.replace("standalone_", "").replace("_", " ").title()
                lines.append(
                    f"| {display} | {sc.get('clarity', 0):.1f} | {sc.get('depth', 0):.1f} | "
                    f"{sc.get('actionability', 0):.1f} | {sc.get('reasoning', 0):.1f} | "
                    f"{sc.get('usefulness', 0):.1f} | {sc.get('overall', 0):.1f} |"
                )
        lines.append("")

    # WHERE ORCHESTRATOR LOSES
    losses = [pr for pr in prompt_results if pr["winner"] != "orchestrator"]
    lines.append("\n## Where the Orchestrator Loses\n")
    if losses:
        for pr in losses:
            winner_display = pr["winner"].replace("standalone_", "").replace("_", " ").title()
            orch_score = pr.get("systems", {}).get("orchestrator", {}).get("avg_scores", {}).get("overall", 0)
            winner_score = pr.get("systems", {}).get(pr["winner"], {}).get("avg_scores", {}).get("overall", 0)
            margin = winner_score - orch_score
            margin_label = "marginal" if margin < 0.5 else "clear" if margin < 1.5 else "significant"
            lines.append(f"- **{pr['prompt_title']}**: Lost to {winner_display} by {margin:.1f} pts ({margin_label})")
    else:
        lines.append("The Orchestrator won every prompt.")

    # MEANINGFUL VS MARGINAL WINS
    wins = [pr for pr in prompt_results if pr["winner"] == "orchestrator"]
    lines.append("\n## Win Quality Analysis\n")
    meaningful = 0
    marginal = 0
    for pr in wins:
        orch_score = pr.get("systems", {}).get("orchestrator", {}).get("avg_scores", {}).get("overall", 0)
        # Find best non-orchestrator
        rivals = {k: v for k, v in pr.get("systems", {}).items() if k != "orchestrator"}
        if rivals:
            best_rival_score = max(v.get("avg_scores", {}).get("overall", 0) for v in rivals.values())
            margin = orch_score - best_rival_score
            if margin >= 0.5:
                meaningful += 1
            else:
                marginal += 1
    lines.append(f"- Meaningful wins (margin >= 0.5): **{meaningful}**")
    lines.append(f"- Marginal wins (margin < 0.5): **{marginal}**")

    # HONEST VERDICT
    lines.append("\n## Honest Verdict\n")
    if orch_rate >= 0.7 and orch_avg >= 8.5:
        lines.append("The Orchestrator **clearly outperforms** standalone frontier models across most prompt types. "
                      "Multi-model synthesis produces demonstrably deeper, more actionable, and more balanced outputs.")
    elif orch_rate >= 0.5:
        lines.append("The Orchestrator **competes strongly** with standalone frontier models and wins more often than it loses. "
                      "It excels at complex, multi-faceted prompts but may not justify its cost for simpler queries.")
    elif orch_rate >= 0.3:
        lines.append("The Orchestrator shows **mixed results**. It wins in specific categories but standalone models "
                      "are competitive or better in others. The product needs to focus on its strongest use cases.")
    else:
        lines.append("The Orchestrator **underperforms** standalone models in this benchmark. "
                      "The synthesis step may not add enough value to justify the added cost and latency.")

    # SHOULD THIS PRODUCT CONTINUE?
    lines.append("\n## Should This Product Continue?\n")
    if orch_rate >= 0.6 and orch_avg >= 8.0:
        lines.append("**Yes.** The data shows genuine quality improvement over standalone models. "
                      "Focus on the prompt categories where the orchestrator wins most decisively.")
    elif orch_rate >= 0.4:
        lines.append("**Yes, with focus.** The orchestrator adds value for specific prompt types. "
                      "Consider positioning as a premium tool for complex analysis, not general-purpose AI.")
    elif orch_rate >= 0.2:
        lines.append("**Pivot.** The orchestrator doesn't consistently outperform standalone models. "
                      "Consider pivoting to focus on the synthesis/comparison visualization rather than trying to beat individual models.")
    else:
        lines.append("**No.** The data doesn't support the core value proposition. "
                      "Standalone models produce equal or better results at lower cost and latency.")

    return "\n".join(lines)


def generate_report(prompt_results: list[dict], full_agg: dict) -> str:
    """Generate a markdown evaluation report."""
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# Blind Evaluation Report")
    lines.append(f"\nGenerated: {now}")
    lines.append(f"\nPrompts evaluated: {full_agg['total_prompts']}")
    lines.append(f"Judge agreement rate: {full_agg['judge_agreement_rate']:.0%}")

    # Win summary
    lines.append("\n## Win Summary\n")
    lines.append("| System | Wins | Win Rate |")
    lines.append("|--------|------|----------|")
    for system, count in sorted(full_agg["win_counts"].items(), key=lambda x: -x[1]):
        rate = full_agg["win_rate"].get(system, 0)
        display = system.replace("standalone_", "").replace("_", " ").title()
        lines.append(f"| {display} | {count} | {rate:.0%} |")

    # Average scores
    lines.append("\n## Average Scores by System\n")
    dims = [d["name"] for d in DIMENSIONS] + ["overall"]
    header = "| System | " + " | ".join(d.capitalize() for d in dims) + " |"
    sep = "|--------|" + "|".join("-------" for _ in dims) + "|"
    lines.append(header)
    lines.append(sep)
    for system, scores in full_agg.get("avg_scores_overall", {}).items():
        display = system.replace("standalone_", "").replace("_", " ").title()
        vals = " | ".join(f"{scores.get(d, 0):.1f}" for d in dims)
        lines.append(f"| {display} | {vals} |")

    # Category breakdown
    lines.append("\n## Performance by Category\n")
    for cat, wins in full_agg.get("category_performance", {}).items():
        lines.append(f"**{cat}**: " + ", ".join(f"{s}={c}" for s, c in wins.items()))

    # Per-prompt details
    lines.append("\n## Per-Prompt Results\n")
    for pr in prompt_results:
        lines.append(f"### {pr['prompt_id']}: {pr['prompt_title']}")
        lines.append(f"Category: {pr.get('category', 'N/A')}")
        lines.append(f"Winner: **{pr['winner']}**")
        lines.append(f"Judges agree: {'Yes' if pr.get('judges_agree') else 'No'}")
        lines.append("")

        if pr.get("systems"):
            lines.append("| System | Clarity | Depth | Action. | Reason. | Useful | Overall |")
            lines.append("|--------|---------|-------|---------|---------|--------|---------|")
            for system, data in pr["systems"].items():
                sc = data.get("avg_scores", {})
                display = system.replace("standalone_", "").replace("_", " ").title()
                lines.append(
                    f"| {display} | {sc.get('clarity', 0):.1f} | {sc.get('depth', 0):.1f} | "
                    f"{sc.get('actionability', 0):.1f} | {sc.get('reasoning', 0):.1f} | "
                    f"{sc.get('usefulness', 0):.1f} | {sc.get('overall', 0):.1f} |"
                )
        lines.append("")

    # Analysis
    lines.append("\n## Analysis\n")
    orch_rate = full_agg["win_rate"].get("orchestrator", 0)
    if orch_rate >= 0.7:
        lines.append("The orchestrator consistently outperforms standalone models, "
                      "indicating that multi-model synthesis adds significant value.")
    elif orch_rate >= 0.4:
        lines.append("The orchestrator shows competitive performance, winning in some categories "
                      "but not all. Multi-model synthesis adds value for complex/multi-faceted prompts.")
    else:
        lines.append("Standalone models perform comparably or better in this evaluation. "
                      "Consider focusing orchestration on prompt types where synthesis adds clear value.")

    return "\n".join(lines)


def save_report(report: str, results_json: dict, output_dir: str = "evaluation/reports"):
    """Save report as markdown and raw JSON."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    md_path = Path(output_dir) / f"eval_{ts}.md"
    json_path = Path(output_dir) / f"eval_{ts}.json"

    md_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps(results_json, indent=2, ensure_ascii=False), encoding="utf-8")

    return str(md_path), str(json_path)
