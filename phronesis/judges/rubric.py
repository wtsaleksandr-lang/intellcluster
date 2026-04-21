"""
Scoring rubric for decision evaluation.
Builds dynamic rubrics from user-defined criteria + built-in dimensions.
Supports focus modes and response length settings.
"""

# Built-in dimensions always scored (the baseline)
BUILT_IN_DIMENSIONS = [
    {
        "name": "practicality",
        "label": "Practicality",
        "description": "How practical and feasible is this option to execute? Consider effort, resources, and complexity.",
        "scale": "1-10 (1=impractical, 10=easy to execute immediately)",
    },
    {
        "name": "risk_level",
        "label": "Risk Level",
        "description": "How risky is this option? Consider downsides, deal-breakers, and what could go wrong.",
        "scale": "1-10 (1=extremely risky, 10=very safe/low risk)",
    },
    {
        "name": "roi_potential",
        "label": "ROI / Upside Potential",
        "description": "How much value or return could this option generate? Consider long-term and short-term upside.",
        "scale": "1-10 (1=no real upside, 10=massive potential return)",
    },
    {
        "name": "overall_fit",
        "label": "Overall Fit",
        "description": "Considering everything, how well does this option fit the stated question and priorities?",
        "scale": "1-10 (1=poor fit, 10=perfect match)",
    },
]


def build_dimensions(user_criteria: list[dict]) -> list[dict]:
    """Build the full dimensions list from user criteria + built-in dimensions."""
    dims = []
    for c in user_criteria:
        dims.append({
            "name": c["name"].lower().replace(" ", "_"),
            "label": c["name"],
            "description": f"How well does this option perform on '{c['name']}'? Score based on the user's priorities.",
            "scale": "1-10 (1=very poor, 10=excellent)",
            "weight": c.get("weight", 5),
        })
    for dim in BUILT_IN_DIMENSIONS:
        dims.append({**dim, "weight": 5})
    return dims


# ─── Focus mode instructions ───

FOCUS_INSTRUCTIONS = {
    "balanced": "Evaluate all dimensions equally. Give a balanced assessment of each option.",
    "risks": (
        "Emphasize risk analysis. Weight risk_level heavily. "
        "For each option, explicitly identify deal-breakers, hidden costs, and worst-case scenarios. "
        "The weakness field MUST describe a concrete risk, not a generic concern."
    ),
    "practical": (
        "Emphasize practicality and execution. Weight practicality heavily. "
        "Focus on what can be done TODAY with existing resources. "
        "Penalize options that require significant setup, expertise, or capital that isn't mentioned. "
        "The strength field MUST describe a concrete execution advantage."
    ),
}

# ─── Length instructions ───

LENGTH_INSTRUCTIONS = {
    "concise": (
        "OUTPUT RULES:\n"
        "- Strength: ONE sentence, max 12 words.\n"
        "- Weakness: ONE sentence, max 12 words.\n"
        "- Explanation: 1 sentence only. Ultra-direct."
    ),
    "standard": (
        "OUTPUT RULES:\n"
        "- Strength: ONE sentence, max 20 words. The single biggest advantage.\n"
        "- Weakness: ONE sentence, max 20 words. The single biggest concern.\n"
        "- Explanation: 2 sentences max. Be direct. Say why #1 wins and what #2 lacks.\n"
        "- No filler, no caveats, no hedging."
    ),
    "detailed": (
        "OUTPUT RULES:\n"
        "- Strength: 2-3 sentences. Explain the advantage with specific reasoning.\n"
        "- Weakness: 2-3 sentences. Explain the risk with concrete examples.\n"
        "- Explanation: 3-4 sentences. Compare top options directly. Mention specific tradeoffs.\n"
        "- Be thorough but not repetitive."
    ),
}


# ─── Judge perspective lenses ───

JUDGE_PERSPECTIVES = {
    "general": (
        "You are a sharp decision analyst. Evaluate options blindly and decisively. "
        "Give a balanced, well-rounded assessment across all dimensions."
    ),
    "skeptic": (
        "You are a risk analyst and devil's advocate. Evaluate options blindly. "
        "Your job is to find what could go WRONG with each option. "
        "Actively look for hidden costs, unrealistic assumptions, deal-breakers, and worst-case scenarios. "
        "Be harder on risk_level scores than a general analyst would be. "
        "If an option sounds too good to be true, score it lower."
    ),
    "pragmatist": (
        "You are a pragmatic execution advisor. Evaluate options blindly. "
        "Your job is to assess what can actually be DONE, not what sounds best in theory. "
        "Focus on feasibility, implementation effort, time-to-value, and resource requirements. "
        "Be harder on practicality scores than a general analyst would be. "
        "Prefer options that deliver results with less complexity."
    ),
}

# Map judge names to perspectives for diversity
JUDGE_PERSPECTIVE_MAP = {
    "judge_openai": "general",
    "judge_anthropic": "skeptic",
    "judge_google": "pragmatist",
}


JUDGE_SYSTEM_PROMPT = """{perspective}

Options are labeled Option A, Option B, etc. They were randomly shuffled — do NOT assume ordering.

Score each option on these dimensions:

{dimensions}

SCORING RULES:
- SPREAD YOUR SCORES. The gap between the best and worst option MUST be at least 2 points on most dimensions. If you score everything 6-8, you are failing at your job.
- Use the FULL 1-10 range: 1-3 = poor/risky/impractical, 4-5 = below average, 6-7 = solid, 8-9 = strong, 10 = exceptional (rare).
- Score each dimension INDEPENDENTLY. An option can score 9 on cost but 3 on quality.
- For each dimension, ask: "Is this option clearly better or worse than the others on THIS specific criterion?" If yes, the scores MUST reflect that gap.
- Judge substance, not wording. Specific beats vague.
- High risk + high reward is NOT automatically better than moderate + safe.
- If two options are close overall, find the dimensions where they DIFFER and score those sharply.

{focus_instruction}

{length_instruction}

JSON format:
{{
  "evaluations": {{
    "Option A": {{
      {dim_keys}
      "strength": "<strength text>",
      "weakness": "<weakness text>"
    }}
  }},
  "ranking": ["Option X", "Option Y", ...],
  "explanation": "<explanation text>"
}}"""


def build_judge_system(
    dimensions: list[dict],
    focus: str = "balanced",
    length: str = "standard",
    perspective: str = "general",
) -> str:
    """Build the system prompt for judge models with focus/length/perspective modes."""
    dim_text = "\n".join(
        f"- {d['label']}: {d['description']} ({d['scale']})"
        for d in dimensions
    )
    dim_keys = "\n      ".join(f'"{d["name"]}": "<int>",' for d in dimensions)
    focus_instruction = FOCUS_INSTRUCTIONS.get(focus, FOCUS_INSTRUCTIONS["balanced"])
    length_instruction = LENGTH_INSTRUCTIONS.get(length, LENGTH_INSTRUCTIONS["standard"])
    perspective_text = JUDGE_PERSPECTIVES.get(perspective, JUDGE_PERSPECTIVES["general"])

    return JUDGE_SYSTEM_PROMPT.format(
        perspective=perspective_text,
        dimensions=dim_text,
        dim_keys=dim_keys,
        focus_instruction=focus_instruction,
        length_instruction=length_instruction,
    )


def build_judge_prompt(
    question: str,
    anonymized_options: dict[str, str],
    attachments: list[str] | None = None,
) -> str:
    """Build the user prompt for judge models."""
    parts = [f"## Decision Question\n{question}\n"]

    # Add domain context for product/consumer decisions
    q_lower = question.lower()
    consumer_signals = ["buy", "laptop", "car", "phone", "mortgage", "subscription", "streaming", "price", "cost", "$", "under $", "budget"]
    if any(s in q_lower for s in consumer_signals):
        parts.append(
            "## IMPORTANT: Real-World Product Evaluation\n"
            "These are REAL products/services with known specifications, pricing, and user reviews.\n"
            "You MUST evaluate based on actual real-world data:\n"
            "- Use actual market prices, not guesses\n"
            "- Reference real specs (e.g., battery range in miles, CPU benchmarks, interest rates)\n"
            "- Consider actual user satisfaction and common complaints\n"
            "- Factor in real-world reliability data and known issues\n"
            "- Score based on CONCRETE differences, not abstract impressions\n"
            "- If one option is clearly cheaper/faster/better-reviewed, the scores MUST reflect that gap\n\n"
        )

    if attachments:
        parts.append("## Attached Context\nThe user attached: " + ", ".join(attachments) + "\n")

    for label, description in anonymized_options.items():
        parts.append(f"## {label}\n{description}\n")

    parts.append("\nEvaluate all options using the rubric. Respond in JSON only.")
    return "\n".join(parts)
