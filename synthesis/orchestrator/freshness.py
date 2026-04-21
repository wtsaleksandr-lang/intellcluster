"""
Freshness detection — classifies whether a prompt needs current/live information.

Runs automatically before research execution. No user input required.
"""

import re

# Explicit freshness keywords (case-insensitive)
_FRESHNESS_KEYWORDS = [
    r"\blatest\b", r"\bcurrent\b", r"\brecent\b", r"\btoday\b",
    r"\bthis week\b", r"\bthis month\b", r"\bthis year\b",
    r"\bright now\b", r"\bup to date\b", r"\bup-to-date\b",
    r"\bnow\b", r"\b2025\b", r"\b2026\b", r"\b2027\b",
    r"\bnews\b", r"\bupdate[sd]?\b", r"\btrend(?:s|ing)\b",
    r"\bprice[sd]?\b", r"\bpricing\b", r"\bcost[s]?\b",
    r"\bregulation[s]?\b", r"\bpolicy\b", r"\bpolicies\b",
    r"\bwho is winning\b", r"\bmarket share\b",
    r"\bnew release[s]?\b", r"\bnew model[s]?\b", r"\bjust launched\b",
    r"\bchanged\b", r"\bchanges\b", r"\bafter.*update\b",
    r"\bcompare current\b", r"\bcurrent state\b",
    r"\bwhat.*happening\b", r"\bwhat.*going on\b",
    r"\bavailable now\b", r"\bbest.*right now\b",
    r"\brecently\b", r"\blast quarter\b", r"\bQ[1-4]\s*20\d{2}\b",
]

# Contextual freshness phrases (partial match patterns)
_FRESHNESS_CONTEXT = [
    r"compare.*competitors.*now",
    r"current.*competitor",
    r"best.*tools.*for",
    r"best.*platform.*for",
    r"best.*software.*for",
    r"top.*apps.*for",
    r"what.*are.*using",
    r"market.*size.*today",
    r"how.*much.*does.*cost",
    r"latest.*strategy",
    r"after.*recent",
    r"since.*update",
    r"current.*pricing",
    r"stock.*price",
    r"share.*price",
    r"revenue.*quarter",
    r"latest.*vs.*previous",
    r"new.*regulation",
    r"law.*changed",
    r"compliance.*update",
    r"interest.*rate",
    r"inflation.*rate",
]

# Categories that inherently lean toward freshness
_FRESHNESS_CATEGORIES = {
    "competitor_market_research",
    "deep_research",
}

# Categories that almost never need freshness
_NO_FRESHNESS_CATEGORIES = {
    "product_offer_design",
    "funnel_conversion",
    "ai_systems_automation",
}


def detect_freshness(prompt: str, category: str = "") -> str:
    """Classify freshness need for a prompt.

    Returns one of:
    - "required"     — prompt clearly needs current/live information
    - "helpful"      — freshness would improve quality but isn't critical
    - "not_needed"   — static reasoning is fine
    """
    text = prompt.lower()
    keyword_hits = 0
    context_hits = 0

    for pattern in _FRESHNESS_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            keyword_hits += 1

    for pattern in _FRESHNESS_CONTEXT:
        if re.search(pattern, text, re.IGNORECASE):
            context_hits += 1

    # Strong signal: multiple keyword hits or context matches
    if keyword_hits >= 3 or context_hits >= 2:
        return "required"

    if keyword_hits >= 1 or context_hits >= 1:
        # Category can push it higher
        if category in _FRESHNESS_CATEGORIES:
            return "required"
        return "helpful"

    # Category-level default
    if category in _FRESHNESS_CATEGORIES:
        return "helpful"

    if category in _NO_FRESHNESS_CATEGORIES:
        return "not_needed"

    return "not_needed"


# Prompt augmentation based on freshness level

FRESHNESS_REQUIRED_INSTRUCTION = (
    "\n\n## IMPORTANT: Current Information Required\n"
    "This request requires the most current, up-to-date information available.\n"
    "- Use the latest publicly available data, not just training knowledge\n"
    "- Prefer recent, reliable sources over older references\n"
    "- If you have web browsing capability, use it to verify current facts\n"
    "- Clearly note when information may be outdated\n"
    "- Include dates and timeframes where relevant\n"
)

FRESHNESS_HELPFUL_INSTRUCTION = (
    "\n\n## Note: Current Information Preferred\n"
    "Where possible, use recent and current information rather than relying solely "
    "on older training data. Note any information that may have changed recently.\n"
)


def get_freshness_instruction(freshness: str) -> str:
    """Get the prompt augmentation text for a freshness level."""
    if freshness == "required":
        return FRESHNESS_REQUIRED_INSTRUCTION
    elif freshness == "helpful":
        return FRESHNESS_HELPFUL_INSTRUCTION
    return ""
