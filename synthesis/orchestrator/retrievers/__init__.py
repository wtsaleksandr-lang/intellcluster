"""
Retriever sub-package — one module per search provider.

Every provider exposes the same async interface:

    async def search(query: str, max_results: int) -> list[RawResult]
    def is_configured() -> bool

Providers NEVER raise — on failure they log and return []. The
orchestrator in `synthesis.orchestrator.retrieval` fan-outs across all
configured providers in parallel and rank-fuses the results.
"""

from synthesis.orchestrator.retrievers import tavily, brave
from synthesis.orchestrator.retrievers.base import RawResult


__all__ = ["tavily", "brave", "RawResult", "list_configured_providers"]


def list_configured_providers() -> list[str]:
    """Return the names of providers with a usable key set."""
    out = []
    if tavily.is_configured():
        out.append("tavily")
    if brave.is_configured():
        out.append("brave")
    return out
