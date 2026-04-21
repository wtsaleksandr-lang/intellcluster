"""
Consensus Extractor — Pre-processes research outputs before strategist.

Analyzes model outputs to identify:
- High consensus (3+ models agree)
- Medium consensus (2 models agree)
- Unique insights (1 model only)
- Contradictions (models disagree)
- Overall agreement score (0-1)

Uses a lightweight AI call + deterministic analysis.
Does NOT delete or filter insights — all are forwarded with metadata.
"""

import json
import re

from synthesis.config import settings
from synthesis.orchestrator.providers import call_with_role_fallback
from shared.providers.base import ModelResult


EXTRACTOR_SYSTEM = """You are a consensus analysis engine. You receive outputs from {model_count} AI research models that all answered the same question.

Your job is to identify patterns across their responses. Respond ONLY in this JSON format:

{{
  "themes": [
    {{
      "theme": "<short description of the insight/recommendation>",
      "mentioned_by": <number of models that mentioned this>,
      "models": ["<model names>"],
      "strength": "high_consensus" | "medium_consensus" | "unique",
      "representative_quote": "<best single sentence from any model>"
    }}
  ],
  "contradictions": [
    {{
      "point": "<what they disagree about>",
      "side_a": {{"position": "<position>", "models": ["<models>"]}},
      "side_b": {{"position": "<position>", "models": ["<models>"]}},
      "context": "<why this disagreement matters>"
    }}
  ],
  "agreement_score": <0.0 to 1.0 — how much the models broadly agree>
}}

Rules:
- A theme mentioned by 3+ models is "high_consensus"
- A theme mentioned by 2 models is "medium_consensus"
- A theme mentioned by 1 model is "unique"
- PRESERVE all themes — do not discard minority insights
- If models use different words but say the same thing, group them as ONE theme
- agreement_score: 0.0 = total disagreement, 1.0 = complete alignment
- Keep theme descriptions SHORT (under 20 words)
- Be precise about which models said what"""


EXTRACTOR_USER = """Question: {question}

{model_outputs}

Analyze all {model_count} model responses. Identify consensus themes, unique insights, and contradictions. Respond in JSON only."""


async def extract_consensus(
    question: str,
    model_results: list[ModelResult],
    tier: str = "standard",
) -> dict:
    """Extract consensus patterns from research model outputs.

    Returns structured consensus data for the strategist.
    Uses cheapest available model for the extraction call.
    """
    # Build model outputs text
    output_parts = []
    for r in model_results:
        if r.status == "success" and r.response_content:
            # Truncate to keep within token limits
            content = r.response_content[:2500]
            output_parts.append(f"### {r.model_name}\n{content}")

    if len(output_parts) < 2:
        # Not enough outputs to analyze consensus
        return _single_model_result(model_results)

    model_count = len(output_parts)
    system = EXTRACTOR_SYSTEM.format(model_count=model_count)
    user = EXTRACTOR_USER.format(
        question=question[:1000],
        model_outputs="\n\n".join(output_parts),
        model_count=model_count,
    )

    # Use cost-efficient tier for extraction — this is a lightweight task
    extraction_tier = "cost_efficient" if tier != "expert" else "standard"

    result, provider_used = await call_with_role_fallback(
        role="strategist",  # reuse strategist role for routing
        prompt=user,
        system=system,
        tier=extraction_tier,
    )

    if result.status != "success" or not result.response_content:
        # Fallback: return basic deterministic analysis
        return _deterministic_fallback(model_results)

    # Parse JSON from response
    try:
        text = result.response_content
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
            # Validate structure
            data.setdefault("themes", [])
            data.setdefault("contradictions", [])
            data.setdefault("agreement_score", 0.5)
            data["provider_used"] = provider_used
            data["model_count"] = model_count
            return data
    except (json.JSONDecodeError, KeyError):
        pass

    return _deterministic_fallback(model_results)


def _single_model_result(model_results: list[ModelResult]) -> dict:
    """Fallback when only 0-1 models succeeded."""
    successful = [r for r in model_results if r.status == "success" and r.response_content]
    return {
        "themes": [{
            "theme": "Single model analysis (no consensus possible)",
            "mentioned_by": 1,
            "models": [successful[0].model_name] if successful else [],
            "strength": "unique",
            "representative_quote": "",
        }] if successful else [],
        "contradictions": [],
        "agreement_score": 0.0 if not successful else 1.0,
        "model_count": len(successful),
        "provider_used": "none",
    }


def _deterministic_fallback(model_results: list[ModelResult]) -> dict:
    """Basic deterministic consensus when AI extraction fails."""
    successful = [r for r in model_results if r.status == "success" and r.response_content]
    return {
        "themes": [{
            "theme": f"Raw analysis from {r.model_name}",
            "mentioned_by": 1,
            "models": [r.model_name],
            "strength": "unique",
            "representative_quote": (r.response_content or "")[:100],
        } for r in successful],
        "contradictions": [],
        "agreement_score": 0.5,
        "model_count": len(successful),
        "provider_used": "deterministic_fallback",
    }


def format_consensus_for_strategist(consensus: dict) -> str:
    """Format consensus data as text for the strategist prompt."""
    parts = []

    score = consensus.get("agreement_score", 0.5)
    count = consensus.get("model_count", 0)
    parts.append(f"## Consensus Analysis ({count} models, agreement: {score:.0%})\n")

    # High consensus
    high = [t for t in consensus.get("themes", []) if t.get("strength") == "high_consensus"]
    if high:
        parts.append("### High Consensus (3+ models agree)")
        for t in high:
            models = ", ".join(t.get("models", []))
            parts.append(f"- [{t.get('mentioned_by', 0)}/{count}] {t['theme']} ({models})")
        parts.append("")

    # Medium consensus
    med = [t for t in consensus.get("themes", []) if t.get("strength") == "medium_consensus"]
    if med:
        parts.append("### Medium Consensus (2 models agree)")
        for t in med:
            models = ", ".join(t.get("models", []))
            parts.append(f"- [{t.get('mentioned_by', 0)}/{count}] {t['theme']} ({models})")
        parts.append("")

    # Unique insights
    unique = [t for t in consensus.get("themes", []) if t.get("strength") == "unique"]
    if unique:
        parts.append("### Unique Insights (1 model only — preserve if valuable)")
        for t in unique:
            models = ", ".join(t.get("models", []))
            parts.append(f"- {t['theme']} ({models})")
        parts.append("")

    # Contradictions
    contras = consensus.get("contradictions", [])
    if contras:
        parts.append("### Contradictions (requires resolution)")
        for c in contras:
            sa = c.get("side_a", {})
            sb = c.get("side_b", {})
            parts.append(f"- **{c.get('point', '')}**")
            parts.append(f"  Side A ({', '.join(sa.get('models', []))}): {sa.get('position', '')}")
            parts.append(f"  Side B ({', '.join(sb.get('models', []))}): {sb.get('position', '')}")
        parts.append("")

    return "\n".join(parts)
