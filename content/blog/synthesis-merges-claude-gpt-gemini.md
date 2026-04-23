---
title: How Synthesis merges Claude, GPT, and Gemini into one answer
slug: synthesis-merges-claude-gpt-gemini
publish_date: 2026-07-29
meta_desc: A behind-the-scenes look at how Synthesis runs five models in parallel and reconciles their outputs into a single coherent research brief.
tags: synthesis, architecture, orchestration, merge-strategy, product
hero_keywords: claude gpt gemini, model orchestration, merge strategy, multi-model
hero_tag: PRODUCT
tool_focus: synthesis
author: IntellCluster
reading_time: 8
---

The hardest part of running a multi-model orchestrator is not calling five models. Calling five models is a for-loop. The hardest part is turning five answers into one coherent brief that reads like one author wrote it.

We get asked how we do it. Here's the architecture behind [Synthesis](/synthesis), written up with enough detail that you could build something similar yourself if you wanted to.

## The five models, and why those five

Synthesis runs five models in parallel on every standard-mode request:

- **GPT-4o-mini** (or GPT-4o in expert mode) — OpenAI prior, best on structured reasoning and formatting
- **Claude Haiku** (or Sonnet in expert mode) — Anthropic prior, best on nuanced writing and balanced argument
- **Gemini 2.5 Flash** — Google prior, best on factual breadth and recent data
- **DeepSeek Chat** — Different architecture, surprisingly strong on technical reasoning
- **Grok-3** — Different training cutoff, different political priors, adds genuine diversity

The specific five matter less than the *diversity* of the five. The goal is priors that disagree in useful ways. Five copies of GPT-4 would produce more internally consistent output and significantly worse research — because the whole point of orchestration is that the union of priors covers more of the answer space than any one prior.

We tested single-vendor five-model setups (five OpenAI models of varying size, five Anthropic models of varying size) and they underperformed the cross-vendor setup by ~15% on the same benchmarks. Vendor diversity is the load-bearing variable.

## The three-phase pipeline

A Synthesis run is not a single five-way call followed by a merge. It's three phases, each with different strategic intent:

### Phase 1: Parallel independent generation

Each of the five models receives the user's question plus a framing prompt that is *different per model*. Not different wording of the same request — genuinely different framings.

- GPT gets "produce a structured brief"
- Claude gets "produce a balanced argument with explicit counter-considerations"
- Gemini gets "produce a factual survey with emphasis on recent developments"
- DeepSeek gets "produce a technical analysis with emphasis on tradeoffs"
- Grok gets "produce a contrarian perspective"

The per-model prompt engineering is where the diversity gets amplified. If we asked all five for "a brief," we'd get five similar briefs. By asking them for genuinely different deliverables, we force the output space to spread.

The five calls run in parallel. Wall-clock time for Phase 1 is the slowest of the five (typically 15–25 seconds for Gemini or DeepSeek, which are the tail latency).

### Phase 2: Strategist extraction and reconciliation

The five outputs go to a "strategist" model — a single Claude Sonnet call that has access to all five outputs and is asked to extract:

- The claims that appear in 4+ outputs (high-agreement claims)
- The claims that appear in 2–3 outputs (medium-agreement)
- The claims that appear in 1 output (novel perspectives)
- Contradictions between the outputs (important signal)
- Structural framings that emerged (the taxonomies the different models imposed)

This phase is the "editor" pass. It doesn't write the final brief — it produces an intermediate representation of what the five models collectively have to say, organized by agreement level.

The strategist's prompt explicitly instructs it to **preserve minority perspectives** that look interesting even if only one model raised them. This is the single most important piece of prompt engineering in the entire pipeline. Without it, the strategist collapses to the safe consensus and the orchestration value evaporates.

### Phase 3: Synthesis and writing

The intermediate representation goes back to the strategist for a final writing pass. This pass produces the brief the user sees.

The prompt at this stage:

- Organize by a taxonomy that emerged from Phase 2 (or the one the user specified)
- Lead with the high-agreement claims (executive summary)
- Follow with the medium-agreement claims (main body)
- Include novel perspectives in a clearly-labeled section (counter-considerations)
- Flag contradictions explicitly rather than resolving them silently
- Write in one voice — don't leave seams between model outputs

The output is a single brief. The reader can't tell it came from five models. That's the goal.

## Why the three-phase structure matters

A naive orchestrator would be one phase: call five models, ask one of them (or a sixth) to merge. That works, but the output reads like Frankenstein's brief — sections don't connect, contradictions sneak through, the tone shifts every paragraph.

The three-phase structure separates **generation** (Phase 1), **analysis** (Phase 2), and **writing** (Phase 3). Each phase has one job. The strategist model in Phase 2 is not asked to write a brief — it's asked to produce a structured intermediate representation. The strategist in Phase 3 is not asked to analyze — it's asked to write from the already-analyzed material.

Splitting the work along those axes produces dramatically better output than trying to do all three at once. This is a generalizable insight for building orchestrators: **separate the cognitive modes**, don't ask a single call to generate + analyze + write.

## The streaming architecture

A full Synthesis run takes 30–90 seconds depending on mode and question complexity. That's too long to show a blank screen. So the UI streams every intermediate event:

- `phases_info`: the taxonomy the strategist identified
- `strategist`: each phase's output as it completes
- `model_start` / `model_end`: per-model lifecycle
- `decision`: the final merged brief
- `done`: pipeline complete

The user sees five models working in parallel during Phase 1 (each with its own progress indicator), then sees the strategist's extraction, then sees the final brief write itself. Not theater — it's the actual shape of the work, and showing it changes the perceived latency dramatically.

The streaming also lets users bail early. If the user sees that the pipeline is headed in a direction they don't want, they can stop, adjust the prompt, and restart without burning the full 90 seconds.

## Why we don't train a "synthesis model"

A question we get: why run five separate models and merge, instead of training a single model on synthesized multi-model output?

Three reasons.

**Diversity is the feature.** A trained-single model would lose the cross-vendor prior diversity that makes orchestration work. The merged output would drift back to a single prior.

**Vendor diversity is insurance.** If Anthropic changes policy, OpenAI raises prices, Google deprecates Gemini — Synthesis still works. A single-vendor trained model is hostage to that vendor.

**The frontier moves.** In 2024 the best model was GPT-4. In 2025 it was Claude Sonnet. In 2026 it's... Synthesis picks dynamically, and the benefits of running the current leaders compound. A trained model is frozen.

The cost is real — five API calls are more expensive than one call to our own model. But the diversity and resilience arguments are strong enough that we don't plan to vertically integrate here.

## Expert mode — when to use the stronger roster

Standard mode uses the "mini" or "haiku" tier across all five models. Expert mode swaps in the flagship tier (GPT-4o, Claude Sonnet 4.6, etc.). The cost ratio is roughly 5× higher. The quality delta is real but not uniform:

- **Domain-dense topics:** expert mode is materially better. Technical architecture, legal reasoning, medical.
- **Strategic questions:** expert mode is slightly better, mostly in the nuance of counter-arguments.
- **Factual survey questions:** expert mode is no better than standard. The "bigger" models don't have more facts — they're just better at reasoning.
- **Creative questions:** expert mode is sometimes worse because the flagships hedge more.

The recommendation: default to standard. Switch to expert when the ceiling of the output matters more than the throughput.

## The "small model" gamble

One thing people don't expect: Synthesis at standard mode often beats a single call to GPT-4o or Claude Sonnet. Smaller models merged beat one bigger model, in our benchmarks.

The intuition: a single frontier model has one prior, however strong. Five smaller models with different priors cover more of the answer space. The coverage advantage compounds faster than the raw-capability advantage, up to the point where the smaller models stop being smart enough to be useful (around the 7B parameter range).

This is why Synthesis in standard mode uses mini/haiku tier models, not tiny models. The models have to be *competent* on each individual call for the merge to produce competent output. Below a competence threshold, the diversity argument breaks down — five outputs of mediocre reasoning don't add up to one output of good reasoning.

## Where the merge layer still struggles

Honest list of open problems:

**Numerical reconciliation.** When the five models produce different numbers for a claim, the strategist has to pick one or report a range. Neither is great. We're experimenting with prompting the strategist to flag numerical divergence explicitly.

**Citation tracking.** The five models don't cite their sources consistently. The merge layer can't surface "3 of 5 models said this" at claim resolution. We're working on claim-level provenance but it's not shipped.

**Cost.** Five models at expert tier is pricey. We subsidize this on our Pro tier and it's a real line item. Scaling costs on orchestration is a structural problem the whole space is working on.

**Latency tail.** The tail latency is dominated by whichever model is slowest on that query. We've seen 120+ second runs when Gemini or DeepSeek hit capacity issues. We cap at 30 minutes and fail gracefully, but the long-tail latency is real.

## The broader point

Multi-model orchestration is not a clever trick; it's an architectural stance. You bet on vendor diversity, prompt specialization per model, and a disciplined multi-phase pipeline. In exchange you get research quality that beats any single frontier model on the shape of problem that matters for real decisions.

The architecture above is not secret. If you wanted to build a competing orchestrator, this is the blueprint. What's hard isn't the architecture — it's the prompt engineering on the per-model prompts, the strategist extraction prompt, and the writing prompt. Those took us six months of iteration. That's where the actual IP lives, and it doesn't fit in a blog post.

If you want to use the finished product, [Synthesis](/synthesis) is free for five runs before paywall. If you want to build your own, the blueprint is above.
