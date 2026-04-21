"""
Scoring rubric for blind evaluation.
Used by judge models to score anonymized responses.
"""

# Round 1-2 dimensions (general intelligence)
DIMENSIONS_GENERAL = [
    {"name": "clarity", "label": "Clarity", "description": "How clear and well-structured?", "scale": "1-10"},
    {"name": "depth", "label": "Depth", "description": "How deep and thorough?", "scale": "1-10"},
    {"name": "actionability", "label": "Actionability", "description": "How actionable and specific?", "scale": "1-10"},
    {"name": "reasoning", "label": "Reasoning Quality", "description": "How sound is the logic?", "scale": "1-10"},
    {"name": "usefulness", "label": "Overall Usefulness", "description": "How useful to the person asking?", "scale": "1-10"},
]

# Round 3 dimensions (commercial/real-world value)
DIMENSIONS_COMMERCIAL = [
    {
        "name": "accuracy",
        "label": "Accuracy",
        "description": "Are the facts, numbers, regulations, and technical details correct? Would a professional trust this?",
        "scale": "1-10 (1=contains clear errors, 10=factually reliable)",
    },
    {
        "name": "practical_usefulness",
        "label": "Practical Usefulness",
        "description": "Could a real business professional use this response to make a decision or take action TODAY?",
        "scale": "1-10 (1=theoretical/generic, 10=immediately usable in a real business)",
    },
    {
        "name": "actionability",
        "label": "Actionability",
        "description": "Are there specific steps, tool names, numbers, and timelines — or just vague advice?",
        "scale": "1-10 (1=vague platitudes, 10=copy-paste ready action plan)",
    },
    {
        "name": "commercial_value",
        "label": "Commercial Value",
        "description": "Would a business pay for this output? Does it save time, reduce risk, or create revenue?",
        "scale": "1-10 (1=no business value, 10=worth paying a consultant for)",
    },
    {
        "name": "freshness",
        "label": "Current Relevance",
        "description": "Does the response reflect current market conditions, pricing, regulations, and tools (2026)?",
        "scale": "1-10 (1=outdated info, 10=clearly current and relevant)",
    },
    {
        "name": "clarity",
        "label": "Clarity",
        "description": "How clear, well-structured, and easy to follow is the response?",
        "scale": "1-10 (1=confusing, 10=crystal clear)",
    },
    {
        "name": "assumptions_stated",
        "label": "Assumptions Stated",
        "description": "Does the response clearly state what it's assuming vs what it knows? Are confidence levels indicated?",
        "scale": "1-10 (1=presents guesses as facts, 10=clearly separates known vs assumed)",
    },
    {
        "name": "overall",
        "label": "Overall Winner Quality",
        "description": "Overall, which response would a professional most want to receive?",
        "scale": "1-10 (1=useless, 10=exceptional professional output)",
    },
]

# Default to general dimensions for backward compatibility
DIMENSIONS = [
    {
        "name": "clarity",
        "label": "Clarity",
        "description": "How clear, well-structured, and easy to follow is the response?",
        "scale": "1-10 (1=confusing/disorganized, 10=crystal clear and perfectly structured)",
    },
    {
        "name": "depth",
        "label": "Depth",
        "description": "How deep and thorough is the analysis? Does it go beyond surface-level?",
        "scale": "1-10 (1=superficial/generic, 10=exceptionally deep and nuanced)",
    },
    {
        "name": "actionability",
        "label": "Actionability",
        "description": "How actionable and specific are the recommendations? Could someone execute on this immediately?",
        "scale": "1-10 (1=vague platitudes, 10=specific steps ready to execute)",
    },
    {
        "name": "reasoning",
        "label": "Reasoning Quality",
        "description": "How sound is the logical reasoning? Are trade-offs acknowledged? Are conclusions supported?",
        "scale": "1-10 (1=flawed logic/unsupported claims, 10=airtight reasoning with evidence)",
    },
    {
        "name": "usefulness",
        "label": "Overall Usefulness",
        "description": "If you were the person who asked this question, how useful would this response be to you?",
        "scale": "1-10 (1=useless, 10=exactly what I needed and more)",
    },
]

JUDGE_SYSTEM_PROMPT = """You are an expert evaluator performing a blind comparison of AI-generated responses.

You will be given a prompt and multiple anonymized responses labeled Response A, Response B, Response C, etc.
You do NOT know which AI system generated which response. Do NOT try to guess.

Your job is to evaluate each response on these dimensions:

{dimensions}

For each response, provide:
1. A score (1-10) for each dimension
2. A brief strength (1 sentence)
3. A brief weakness (1 sentence)

Then provide:
4. Your overall ranking from best to worst
5. A brief explanation of why #1 is the best (2-3 sentences)

IMPORTANT RULES:
- Be honest and critical. Not everything deserves a high score.
- Judge the CONTENT, not the formatting or style.
- If a response is generic/vague, score it low on depth and actionability even if it sounds polished.
- A shorter, specific response can beat a longer, generic one.

Respond in this exact JSON format:
{{
  "evaluations": {{
    "Response A": {{
      "clarity": <int>,
      "depth": <int>,
      "actionability": <int>,
      "reasoning": <int>,
      "usefulness": <int>,
      "strength": "<1 sentence>",
      "weakness": "<1 sentence>"
    }},
    ...for each response
  }},
  "ranking": ["Response X", "Response Y", ...],
  "explanation": "<2-3 sentences explaining why #1 is best>"
}}"""


JUDGE_COMMERCIAL_PROMPT = """You are a senior business consultant evaluating AI-generated responses for REAL-WORLD COMMERCIAL VALUE.

You will be given a prompt and multiple anonymized responses labeled Response A, Response B, Response C, etc.
You do NOT know which AI system generated which response. Do NOT try to guess.

You are judging these responses as if a PAYING CLIENT submitted this question.
The client is a business professional who needs answers they can act on TODAY.

Evaluate each response on these dimensions:

{dimensions}

For each response, provide:
1. A score (1-10) for each dimension
2. A brief strength (1 sentence)
3. A brief weakness (1 sentence)
4. Whether you detected any hallucinations or likely false claims (yes/no + detail)

Then provide:
5. Your overall ranking from best to worst
6. A brief explanation of why #1 is best for a REAL BUSINESS USER (2-3 sentences)

IMPORTANT RULES:
- Judge as a professional who needs CORRECT, USABLE answers — not impressive-sounding ones.
- Penalize heavily: made-up numbers, outdated info, vague advice disguised as strategy.
- Reward: specific tool names, realistic cost estimates, actual regulatory details, ready-to-use templates.
- A shorter, correct response beats a longer, hallucinated one.

Respond in this exact JSON format:
{{
  "evaluations": {{
    "Response A": {{
      "accuracy": <int>,
      "practical_usefulness": <int>,
      "actionability": <int>,
      "commercial_value": <int>,
      "freshness": <int>,
      "clarity": <int>,
      "assumptions_stated": <int>,
      "overall": <int>,
      "strength": "<1 sentence>",
      "weakness": "<1 sentence>",
      "hallucinations": "<none detected OR describe specific false claims>"
    }},
    ...for each response
  }},
  "ranking": ["Response X", "Response Y", ...],
  "explanation": "<2-3 sentences explaining why #1 is best for a real business>"
}}"""


def build_judge_system(commercial: bool = False):
    """Build the system prompt for judge models."""
    if commercial:
        dim_text = "\n".join(
            f"- {d['label']}: {d['description']} ({d['scale']})"
            for d in DIMENSIONS_COMMERCIAL
        )
        return JUDGE_COMMERCIAL_PROMPT.format(dimensions=dim_text)
    dim_text = "\n".join(
        f"- {d['label']}: {d['description']} ({d['scale']})"
        for d in DIMENSIONS
    )
    return JUDGE_SYSTEM_PROMPT.format(dimensions=dim_text)


def build_judge_prompt(prompt_text: str, anonymized_responses: dict[str, str]) -> str:
    """Build the user prompt for judge models.

    anonymized_responses: {"Response A": "...", "Response B": "...", ...}
    """
    parts = [f"## Original Prompt\n{prompt_text}\n"]
    for label, content in anonymized_responses.items():
        parts.append(f"## {label}\n{content}\n")
    parts.append("\nEvaluate all responses using the rubric. Respond in JSON only.")
    return "\n".join(parts)
