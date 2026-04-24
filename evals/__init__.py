"""
Synthesis golden-set evaluation harness.

Purpose
-------
Prevent silent quality regression as the Synthesis pipeline evolves.
Runs a curated set of prompts through the full pipeline, then scores
the resulting StructuredReport against deterministic + LLM judges that
check the correctness properties we care about:

  - citation validity        (every [N] points into retrieved sources)
  - structural completeness  (schema fields populated sensibly)
  - freshness alignment      (fresh-demanding prompts get recent sources)
  - confidence consistency   (the band matches its component scores)
  - factuality               (cited claims supported by source snippets)

This is NOT the `synthesis/evaluation/` module — that's a head-to-head
blind judge harness used for marketing/demonstration. This harness is
about catching regressions.

CLI
---
    python -m evals.runner --mock              # CI-safe, no API calls
    python -m evals.runner --real              # full sweep, costs ~$1-5
    python -m evals.runner --real --quick      # 3 prompts, ~$0.30
    python -m evals.runner --real --judge llm  # include factuality judge
"""
