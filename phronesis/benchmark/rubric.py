"""
Benchmark rubric for evaluating Decision Intelligence Tool outputs.
Judges grade the QUALITY of the tool's decision analysis, not the decision itself.
"""

DIMENSIONS = [
    {
        "name": "winner_accuracy",
        "label": "Winner Accuracy",
        "description": "Does the recommended winner make logical sense given the question, options, and criteria? Would a reasonable expert agree?",
        "scale": "1-10 (1=clearly wrong winner, 10=obviously correct choice)",
    },
    {
        "name": "reasoning_quality",
        "label": "Reasoning Quality",
        "description": "Is the 'why it won' explanation specific, logical, and grounded in the criteria? Or is it generic filler that could apply to any option?",
        "scale": "1-10 (1=generic/meaningless, 10=specific and compelling)",
    },
    {
        "name": "score_differentiation",
        "label": "Score Differentiation",
        "description": "Are the scores meaningfully spread across options? Do they reflect real differences, or are they clustered in a narrow 6-8 range?",
        "scale": "1-10 (1=all scores identical, 10=clear meaningful spread)",
    },
    {
        "name": "strength_weakness_quality",
        "label": "Strength/Weakness Quality",
        "description": "Are the strengths and weaknesses concrete, specific, and useful? Or are they generic statements that could apply to anything?",
        "scale": "1-10 (1=generic filler, 10=specific and actionable insights)",
    },
    {
        "name": "confidence_calibration",
        "label": "Confidence Calibration",
        "description": "Does the confidence level match the clarity of the result? High confidence for clear winners, low for tight races?",
        "scale": "1-10 (1=confidence is misleading, 10=confidence accurately reflects certainty)",
    },
    {
        "name": "decisiveness",
        "label": "Decisiveness",
        "description": "Does the output commit to a clear recommendation? Or does it hedge with 'it depends', 'consider your needs', or other non-committal language?",
        "scale": "1-10 (1=hedges and refuses to decide, 10=clear decisive recommendation)",
    },
]


EVAL_SYSTEM_PROMPT = """You are an expert evaluator grading the quality of an AI decision analysis tool.

You will see: the original decision question, the tool's full output (winner, scores, strengths/weaknesses, recommendation text, confidence level), and the scoring rubric.

Your job: evaluate how GOOD the tool's analysis is, NOT whether you personally agree with the winner.

Score on these dimensions:

{dimensions}

RULES:
- A tool can pick a "wrong" winner but still have excellent reasoning — score reasoning separately from winner accuracy.
- Generic outputs like "Option A has good value" deserve low scores on strength/weakness quality.
- If all options score 6-8 with no differentiation, score_differentiation should be low.
- If confidence is "high" but the scores are nearly tied, confidence_calibration should be low.
- If the recommendation says "it depends on your priorities" instead of committing, decisiveness is low.

JSON format:
{{
  "scores": {{
    {dim_keys}
  }},
  "overall": <int 1-10>,
  "verdict": "<1 sentence: what's the biggest quality issue with this output?>"
}}"""


def build_eval_system() -> str:
    """Build the system prompt for benchmark evaluator judges."""
    dim_text = "\n".join(
        f"- {d['label']}: {d['description']} ({d['scale']})"
        for d in DIMENSIONS
    )
    dim_keys = "\n    ".join(f'"{d["name"]}": <int>,' for d in DIMENSIONS)
    return EVAL_SYSTEM_PROMPT.format(dimensions=dim_text, dim_keys=dim_keys)


def build_eval_prompt(prompt_data: dict, tool_output: dict) -> str:
    """Build the user prompt for benchmark evaluation."""
    ranked = tool_output.get("ranked_options", [])
    rankings_text = "\n".join(
        f"  #{o['rank']} {o['option']} — score {o['score']:.1f}/10"
        + (f"\n    Strengths: {', '.join(o.get('strengths', []))}" if o.get("strengths") else "")
        + (f"\n    Weaknesses: {', '.join(o.get('weaknesses', []))}" if o.get("weaknesses") else "")
        for o in ranked
    )

    return f"""## Original Decision
Question: {prompt_data['question']}
Options: {', '.join(prompt_data['options'])}
Criteria: {', '.join(c['name'] + ' (weight ' + str(c['weight']) + ')' for c in prompt_data['criteria'])}

## Tool Output
Winner: {tool_output.get('winner', 'N/A')}
Recommendation: {tool_output.get('why_winner_won', 'N/A')}
Confidence: {tool_output.get('confidence', 'N/A')} ({tool_output.get('confidence_score', 'N/A')}%)
Judges: {tool_output.get('judge_count', 'N/A')}, Agreement: {'Yes' if tool_output.get('judges_agree') else 'No'}

Rankings:
{rankings_text}

## Task
Evaluate the QUALITY of this analysis. Respond in JSON only."""
