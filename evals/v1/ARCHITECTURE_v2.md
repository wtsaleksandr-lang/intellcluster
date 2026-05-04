# IntellCluster Architecture v2 — Role Specialization

This document describes the architectural changes that v2 makes to v1, the rationale, and the expected accuracy/cost impact. Implementation only proceeds after the v1 baseline numbers are recorded.

---

## Phronesis v2 — Role-specialized judges

### Current (v1)
- 3 judges (one per provider) with the same rubric, scored independently
- Per-provider "perspective": general / skeptic / pragmatist (text-only difference in system prompt; same dimensions, same expected output)
- Aggregator averages scores; weights are uniform across judges

### v2 — Role specialization

Replace per-provider perspective with three judge ROLES, each with a distinct task. Each judge can be assigned to whichever provider is currently strongest for that role; provider diversity is preserved by mapping the three roles to three different providers when keys are available.

| Role | Charter | Expected output emphasis |
|---|---|---|
| **Risk Modeler** | Find ways each option fails. Identify downside scenarios, second-order risks, common failure modes. Score risk-related dimensions; provide explicit failure-mode list per option. | Risk dimensions weighted higher in this judge's score; explicit `failure_modes` field added to JSON. |
| **Base Rate Finder** | Apply historical priors. Identify the population of "decisions like this one" and what their typical outcomes were. Reason from frequencies, not stories. | All dimensions scored, but rationale must reference base rates (e.g. "X% of seed-stage YC startups reach Series B"). New `base_rates` field listing relevant historical frequencies. |
| **Devil's Advocate** | Only attack the apparently-leading option (heuristic: option with most positive criteria mentions in question, or first option as fallback). Build the strongest possible case AGAINST it. | Single-option focus. Output: counter-arguments, hidden assumptions, conditions under which the lead would lose. |

### Aggregator changes

Per-role score weighting on each dimension:

| Dimension type | Risk Modeler weight | Base Rate Finder weight | Devil's Advocate weight |
|---|---|---|---|
| Risk-coded (downside, security, compliance) | **2.0×** | 1.0× | 1.5× |
| Frequency-coded (likelihood, success rate) | 1.0× | **2.0×** | 1.0× |
| Other (cost, fit, simplicity) | 1.0× | 1.0× | 0.5× |

Devil's Advocate provides a single asymmetric adjustment: subtract `0.5 × (DA_score on leading option)` from that option's final aggregate. Equivalent to "give credit to the strongest counter-argument."

### Why this should beat v1

- v1's "perspectives" all evaluate the same way — three votes on the same rubric. The variance reduction is real but bounded.
- v2's roles produce **structurally different content**. Risk Modeler may surface a critical failure mode that none of the v1 perspectives would find because none of them were assigned to look for it.
- Per-published MoA literature, role specialization yields ~2–3× the accuracy lift of naive ensembling.

### Cost impact
- Same number of judge calls (3); same models; same approximate token budgets
- Slight increase in input tokens (longer role-specific system prompts) — ~5% per call
- Net cost per phronesis run: ~$0.008 → ~$0.0085 (negligible increase)

---

## Synthesis v2 — Role-specialized researchers + pre-DM verification

### Current (v1)
- 5 researchers running the SAME prompt in parallel (just on different models)
- Strategist phase synthesises 5 outputs into one
- Decision Maker writes the final report
- Verification runs AFTER the DM, scoring claim support but not modifying the report

### v2 — Role specialization

Replace the 5×same-prompt research fan-out with 5 specialized agents, each consuming the refined prompt + retrieved sources but with a different task:

| Agent | Charter | Output |
|---|---|---|
| **Searcher** | Source quality assessor. For each retrieved source: score relevance, recency, authority, and identify which claims it actually supports. | Per-source scorecard: `{url, relevance, recency_days, authority_tier, claims_supported[]}` |
| **Quantifier** | Extract every quantitative claim in the question's domain. Compute derived numbers, identify rates, cite specific figures. | List of `{claim, value, unit, source_id, confidence}` |
| **Skeptic** | For each apparent finding, identify what would need to be true for it to be wrong. Surface contested points, methodological weaknesses. | List of `{claim, weakness, contradicting_evidence}` |
| **Synthesizer** | Write coherent prose using ONLY claims from the verified-claim pool (output of pre-DM verification step). | Prose narrative, structured sections, citation IDs |
| **Citator** | Manage source attribution. Map every prose claim to a source ID. Flag uncited assertions. | Citation map + uncited-claim list |

Concurrency: Searcher + Quantifier + Skeptic run in parallel (independent passes over the source set). Their outputs feed the **pre-DM verification step**, which assembles a "verified claim pool" of claims that are (a) supported by Searcher's scoring AND (b) not contradicted by Skeptic's findings. Synthesizer then writes USING ONLY claims in that pool. Citator runs last to map citations.

### Pre-DM verification (replaces post-DM verification)

Verification today runs AFTER the DM has written the report. Risk: DM hallucinations can survive (the verifier only logs them, doesn't remove them).

v2: verification runs BEFORE the DM. Each candidate claim is checked against retrieved sources. Unsupported claims are dropped from the pool. The DM writes from a clean pool.

### Why this should beat v1
- v1's 5 researchers all answer the same question; their differences are model-specific noise. Aggregation reduces variance but doesn't add new information.
- v2's agents produce **structurally different outputs**. The Quantifier surfaces numbers that the v1 researchers might have buried in prose. The Skeptic finds weaknesses the v1 strategist would have averaged out.
- Hallucination drop: Synthesizer can only cite verified claims. Net hallucination rate should drop substantially (per RAG literature, citation-grounded generation halves hallucination on factual benchmarks).

### Cost impact
Per published MoA with role specialization: shifts from "5 expensive parallel calls + 1 strategist + 1 DM" to "5 cheap-ish specialized calls + 1 synthesizer + 1 citator."

| Step | v1 cost | v2 cost |
|---|---|---|
| 5 researchers (same prompt) | $0.10 | n/a |
| Searcher (gemini-flash) | n/a | $0.002 |
| Quantifier (gemini-flash) | n/a | $0.003 |
| Skeptic (sonnet — wants nuance) | n/a | $0.025 |
| Strategist (sonnet, multi-source synthesis) | $0.04 | n/a |
| Verification (post) | $0.006 | n/a (replaced) |
| Pre-DM verification (gemini-flash) | n/a | $0.005 |
| Synthesizer (sonnet, smaller input than v1 strategist) | n/a | $0.020 |
| Decision maker (sonnet) | $0.04 | n/a (Synthesizer subsumes it) |
| Citator (gemini-flash) | n/a | $0.002 |
| **Total** | **~$0.20** | **~$0.06** |

v2 should be cheaper while being more accurate. The cost reduction comes from sending a smaller payload to expensive models (Skeptic + Synthesizer) and offloading bulk work to Gemini Flash agents.

---

## Quick tier — single best model + rubric prompt

For "I just want a fast answer" use cases. Single Sonnet call with a rubric-flavored system prompt. Skips orchestration entirely.

- Cost: ~$0.005 per decision, ~$0.015 per research run
- Latency: 3-10s
- Expected accuracy: matches Sonnet-solo baseline (which is the literature's "single strong model" baseline)

This tier exists for honesty: most casual users get more value from a fast single-model answer than from a slow multi-agent council.

---

## Rollout plan

1. Implement Phronesis v2 first (smaller diff, easier to validate)
2. Re-run eval, compare to v1 baseline
3. If Phronesis v2 wins: proceed with Synthesis v2
4. Re-run eval again, compare both subsystems to v1 baseline
5. Quick tier last (smallest impact)
6. Generate `RESULTS.md` with all comparisons

If at any stage v2 doesn't beat v1, stop and diagnose before proceeding.
