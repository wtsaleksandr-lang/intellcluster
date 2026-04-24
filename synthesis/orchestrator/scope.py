"""
Scope helpers — parse, default, and format the PE-extracted Scope object.

A Scope tells downstream agents what the user actually wants *about*:
who it's for, when, where, and why. Scope is always additive — missing
fields degrade gracefully to None and the agents behave as before.
"""

from __future__ import annotations

import re
from typing import Any

from synthesis.orchestrator.types import Scope


# The decision-intent is the one field we try to normalise (short, closed
# verb set), because it's the one downstream agents can branch on cleanly.
_KNOWN_INTENTS = (
    "buy", "build", "compare", "understand",
    "validate", "investigate", "plan",
)


def _clean_str(v: Any, max_len: int = 120) -> str | None:
    """Normalise a model-supplied scope string.

    - Strip, collapse whitespace
    - Reject obvious placeholder words ("null", "none", "n/a", "unknown")
    - Cap length so a runaway model can't pollute the context
    """
    if v is None:
        return None
    if not isinstance(v, str):
        v = str(v)
    s = v.strip()
    if not s:
        return None
    low = s.lower()
    if low in {"null", "none", "n/a", "na", "unknown", "not specified", "not applicable", "-"}:
        return None
    s = re.sub(r"\s+", " ", s)[:max_len]
    return s or None


def _normalise_intent(v: Any) -> str | None:
    """Map loosely-worded intents onto the known set.

    Falls through to the cleaned string if we can't map it — we prefer
    preserving PE nuance over forcing a bucket.
    """
    cleaned = _clean_str(v, max_len=40)
    if not cleaned:
        return None
    low = cleaned.lower().strip(".,;:")
    for known in _KNOWN_INTENTS:
        if known == low or known in low.split():
            return known
    # Soft aliases
    aliases = {
        "purchase": "buy", "buying": "buy", "acquire": "buy", "procure": "buy",
        "develop": "build", "building": "build", "implement": "build",
        "compare": "compare", "evaluate": "compare", "versus": "compare", "vs": "compare",
        "explain": "understand", "learn": "understand", "research": "understand",
        "verify": "validate", "vet": "validate", "check": "validate",
        "analyze": "investigate", "analyse": "investigate", "diagnose": "investigate",
        "strategy": "plan", "roadmap": "plan",
    }
    for alias, target in aliases.items():
        if alias in low:
            return target
    return cleaned   # Preserve PE's phrase — better than losing it.


def parse_scope(raw: Any) -> Scope:
    """Parse a dict-like (or anything) into a Scope. Always returns a Scope.

    Any missing/invalid field becomes None — never raises.
    """
    if not isinstance(raw, dict):
        return Scope()
    return Scope(
        timeframe=_clean_str(raw.get("timeframe")),
        region=_clean_str(raw.get("region")),
        audience=_clean_str(raw.get("audience"), max_len=160),
        decision_intent=_normalise_intent(raw.get("decision_intent")),
    )


def format_scope_for_prompt(scope: Scope, prefix: str = "## Scope") -> str:
    """One-liner-per-field compact block for agent context.

    Returns "" when scope is empty so we don't inject noise.
    """
    if scope.is_empty():
        return ""
    lines = [prefix]
    if scope.audience:
        lines.append(f"- Audience: {scope.audience}")
    if scope.decision_intent:
        lines.append(f"- Intent:   {scope.decision_intent}")
    if scope.timeframe:
        lines.append(f"- When:     {scope.timeframe}")
    if scope.region:
        lines.append(f"- Where:    {scope.region}")
    return "\n".join(lines)


def augment_query_with_scope(query: str, scope: Scope) -> str:
    """Enrich a search query with scope signals if they add useful targeting.

    Only appends region + timeframe (audience/intent rarely help search
    engines). Skips if the query already contains the hint word.
    """
    if scope.is_empty() or not query:
        return query

    additions: list[str] = []
    low = query.lower()

    if scope.region and scope.region.lower() not in low:
        # Short region codes feel natural appended; "global" is filler.
        if scope.region.lower() != "global":
            additions.append(scope.region)

    if scope.timeframe:
        tf = scope.timeframe.strip()
        # If the query already contains a 4-digit year OR "current"/"latest",
        # the scope timeframe won't add signal — skip.
        has_year = bool(re.search(r"\b20\d{2}\b", query))
        has_tense = any(w in low for w in ("current", "latest", "recent", "today"))
        if not has_year and not has_tense:
            # Extract year if present in timeframe, else fall back to phrase.
            year_match = re.search(r"\b20\d{2}\b", tf)
            if year_match:
                additions.append(year_match.group())
            elif len(tf) <= 40:
                additions.append(tf)

    if not additions:
        return query
    out = (query + " " + " ".join(additions)).strip()
    return out[:400]


# ────────── Prompt-engineer schema fragment ──────────

SCOPE_SCHEMA_FRAGMENT = """
  "scope": {
    "timeframe": "when the user cares about (e.g. 'Q4 2026', 'current state', 'last 12 months', 'all-time'). null if not inferable.",
    "region":    "geographic focus (e.g. 'US', 'EU', 'global'). null if not inferable.",
    "audience":  "who the answer is FOR (e.g. 'solo founders', 'enterprise DevOps leads'). null if not inferable.",
    "decision_intent": "one of: buy | build | compare | understand | validate | investigate | plan. null if not inferable."
  }"""


SCOPE_EXTRACTION_INSTRUCTIONS = """
## Scope Extraction
Before deciding phases, EXTRACT the implicit scope of the request:
  - timeframe: when the user cares about
  - region:    geographic focus
  - audience:  who the answer is for
  - decision_intent: the user's core verb (use one of: buy | build | compare | understand | validate | investigate | plan)

Only fill a field if the prompt CLEARLY signals it. Use null when unsure —
do NOT invent audience or region. Be honest about ambiguity."""
