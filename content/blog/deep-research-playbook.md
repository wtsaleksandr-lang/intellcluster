---
title: Deep research playbook — Synthesis vs ChatGPT vs Perplexity vs Claude
slug: deep-research-playbook
publish_date: 2026-10-07
meta_desc: A honest comparison of four deep-research AI tools. When each wins, when each loses, and the workflow we recommend for different research types.
tags: deep-research, synthesis, comparison, chatgpt, perplexity, claude
hero_keywords: deep research tools, synthesis vs perplexity, chatgpt deep research, research playbook
hero_tag: COMPARISON
tool_focus: synthesis
author: IntellCluster
reading_time: 10
---

The deep-research AI category was invented by Perplexity, extended by ChatGPT, contested by Claude, and is now crowded with entrants. [Synthesis](/synthesis) is one of them. This post is the comparison you'd want us to write if we weren't the vendor — an honest account of when each tool wins, when each loses, and how we'd structure research work across them.

We'll be critical of ourselves where it's warranted. The category is early, and every tool has weak spots.

## What "deep research" actually means

"Deep research" is a marketing term as much as a product category. The underlying capability is: take a research question, spend 30 seconds to several minutes on it (vs chat's 5–10 seconds), and produce a structured document that's more thorough than any single chat message could be.

The mechanisms vary:

- **Perplexity:** one strong model + web search, optimized for citation
- **ChatGPT deep research mode:** iterative search + reasoning + writing, single frontier model
- **Claude Research (Claude.ai research features):** one strong model + web search + tool use
- **Synthesis:** five different models in parallel + strategist merge, no default web search

Four different architectures. Four different strengths. Let's break down the usage patterns.

## The category leaders' strengths

### Perplexity — for web-current, cited research

Perplexity's core thesis is web search done by an LLM with citations. The output is a well-structured brief with every claim anchored to a source URL. It's the tool to reach for when:

- You need the answer to include primary sources you can click through to
- The answer depends on recent (<3 months) information
- You're researching a topic where knowing *who* said something matters as much as what was said

Weaknesses: Perplexity's answer quality depends on the quality of its search results. For niche topics where the search results are thin, the brief is thin. Perplexity also tends to surface-level on complex analytical questions — it's great at factual synthesis, less strong at reasoning.

### ChatGPT deep research — for long-horizon investigative work

OpenAI's deep research mode is the heavyweight of the category. It'll spend 5–30 minutes on a question, iteratively searching, reasoning, and composing. The output is longer and more thorough than Perplexity's typical brief. It's the tool to reach for when:

- The research question is genuinely complex (multi-part, open-ended)
- You need a document length of 2000+ words with substantive depth
- You have the latency budget (the long wall-clock time is the core trade-off)

Weaknesses: ChatGPT deep research can over-produce. A question that deserved a 1200-word brief becomes a 3500-word document with sections you didn't need. The tool is also single-model — you're getting GPT's prior with extra compute, not diverse priors.

### Claude Research — for nuanced analytical writing

Claude's research capabilities shine on questions that benefit from careful, balanced argumentation. Claude's strength is prose quality and counter-argument consideration. It's the tool to reach for when:

- The output will be read by a skeptical expert who notices shallow reasoning
- The question has multiple legitimate framings and you want balanced coverage from one voice
- Writing quality matters for how the deliverable lands

Weaknesses: Claude's tool use is still maturing. Web search works but isn't as tight as Perplexity's integration. Claude is also expensive at scale; cost-per-research-brief is higher than competitors.

### Synthesis — for diversity-of-prior research

Our own pitch: multi-model orchestration. Five different models in parallel, merged by a strategist layer. Synthesis is the tool to reach for when:

- The question has genuinely multiple legitimate framings and you want *different* models to surface them
- You don't need current web data (Synthesis doesn't search the web by default)
- You want a brief that explicitly flags where models disagreed
- The output benefits from being written by a strategist that has five perspectives to reconcile

Weaknesses we should name: Synthesis doesn't search the web natively. For current-event topics, we lose to Perplexity. Our briefs can feel less "connected to external reality" than citation-heavy tools. We're working on web search integration; it's not shipped.

## The matrix, honestly

| Use case | Best tool | Second best |
|---|---|---|
| Current events / news research | Perplexity | ChatGPT DR |
| Long investigative research (10+ pages) | ChatGPT DR | Synthesis (expert) |
| Balanced argumentation / writing quality | Claude | Synthesis |
| Multi-framing strategic research | **Synthesis** | ChatGPT DR |
| Competitive landscape (established companies) | Perplexity | Synthesis |
| Fact-dense survey with citations | Perplexity | ChatGPT DR |
| Architectural / technical tradeoffs | **Synthesis** | Claude |
| Prompt-sensitive, iterative work | Claude | ChatGPT |
| Low-latency short research | Claude | Perplexity |
| Expensive-call, high-stakes research | Synthesis (expert) | ChatGPT DR |

Bolded = the tool clearly wins. Others = reasonable alternatives with different trade-offs.

## A real-research workflow

Here's the workflow I personally use (I'm a user of all four). The punchline is that no single tool is right for everything; the practice is learning which question goes to which tool.

**Morning triage:** I write down the research questions I need to answer this week. Usually 3–5 items.

**Per-question routing:**

- Is this about recent events? → Perplexity
- Is this a thorough, high-stakes investigation? → ChatGPT deep research
- Is this about multi-framing strategy or architecture? → Synthesis
- Is this about nuanced writing or argument? → Claude

**Parallel fires:** I fire off all four if the questions split. The latency is substantial for ChatGPT DR and Synthesis (30s–15min). Firing in parallel and reading later is the right rhythm.

**Cross-check on important claims:** If any brief makes a load-bearing claim — a number, a specific event, a competitive positioning — I verify in a second tool. Different tools will catch different types of errors.

**Synthesize across briefs:** For the most important questions, I'll take two briefs from different tools and ask Claude to compare them. "These two briefs reached different conclusions — which is more defensible and why?" The meta-analysis surfaces confidence issues.

This workflow treats deep research as a portfolio of tools, not a single bet. Takes longer upfront to learn which tool fits which shape. Produces dramatically better research output once the muscle memory forms.

## Where we're losing and what we're fixing

Since we said we'd be honest, here's where Synthesis currently underperforms:

### Web data gap

Synthesis runs on the five models' training data. When you ask about 2026 events, we lean on whatever cutoff each model has. For news-current topics, we're objectively behind Perplexity.

Fix in progress: web search integration. Target Q2 2026. The architecture challenge is that our merge layer is designed for text-only inputs; wiring in retrieval changes the prompt design at every phase.

### Latency tail

When one of the five models is slow (Gemini/DeepSeek hit capacity spikes), Synthesis is slow. The tail latency is meaningful — we've seen 120+ second runs when the network is unfavorable.

Fix in progress: smarter fallback — if one model is delayed beyond 60 seconds, we proceed with the other four and note the omission in the brief. Expected Q1.

### Citation tracking

Our briefs reference claims from different models but don't trace claims back to specific model outputs. For users who want provenance, this is a gap.

Fix in progress: claim-level attribution in the strategist layer. This is harder than it sounds because the strategist re-phrases and merges; maintaining attribution through paraphrase is an active research area.

### Cost

Expert mode is pricey ($0.25–0.60 per run). For users running 50 briefs/week, this adds up.

Fix in progress: cheaper expert models as the frontier moves. No specific mitigation from us; the industry trend is our friend here.

## Pricing comparison

Rough 2026 pricing (list, not negotiated):

- **Perplexity Pro:** $20/month, unlimited queries
- **ChatGPT Plus with Deep Research:** $20/month, ~120 deep research queries/month
- **Claude Pro:** $20/month, research features included
- **Synthesis (our Pro plan):** $29/month, 100 runs/month, includes Phronesis

Cost per deep research brief, marginal:

- Perplexity: effectively zero (flat rate)
- ChatGPT DR: ~$0.17 (120 queries / $20)
- Claude Research: effectively zero (flat rate)
- Synthesis: ~$0.29 (100 runs / $29)

If you run < 30 research briefs per month, any of these works. Above 50/month, the cost calculus shifts toward flat-rate tools unless orchestration or diversity of models matters for your specific use case.

## The honest recommendation

If you're going to use just one deep-research tool, the honest recommendation depends on your work:

- **Journalists, analysts, researchers:** Perplexity. Citations and web currency are your job.
- **Strategists, consultants, PMs:** ChatGPT deep research. Long-form investigation and depth are what you need.
- **Writers, editors, communicators:** Claude. Writing quality is the thing.
- **Engineers, architects, multi-model-curious teams:** Synthesis. Diversity of priors on technical questions pays off.

If you're willing to use multiple tools, use all four — the portfolio approach is genuinely better than any single-tool workflow, and the total cost is still under $100/month.

## The broader point

The deep-research category is two years old as a distinct product category. It's still finding its shape. Each tool is strong on different dimensions. None is best at everything. The users who get the most value are the ones who stop treating "AI research tool" as a single-slot item in their stack and start treating it as a portfolio.

This is not the "one tool to rule them all" story the market wants. It's the honest story. The tools are complements more than substitutes, the total spend is low enough to justify multiple subscriptions, and the research quality uplift from using the right tool for each question is substantial.

For Synthesis specifically: we're strong on multi-framing strategic questions, technical architecture decisions, and orchestrated briefs where diversity of priors matters. We're working on closing our weaknesses. [Try it](/synthesis) — free for five runs — and see where it fits in your portfolio.
