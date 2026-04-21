"""
Global context injected into every agent prompt.
"""

from datetime import datetime, timezone

GLOBAL_CONTEXT = """## Current Context
- Current date: {current_date}
- Treat this as the present time
- Do NOT shift timeline unless explicitly instructed
- If the user references a year, treat it as current context unless clearly stated otherwise
- Clearly separate: current facts vs projections vs assumptions"""


def get_global_context() -> str:
    now = datetime.now(timezone.utc)
    return GLOBAL_CONTEXT.format(
        current_date=now.strftime("%B %Y"),
    )
