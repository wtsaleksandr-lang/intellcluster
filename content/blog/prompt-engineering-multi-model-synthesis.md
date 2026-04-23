---
title: Prompt engineering for multi-model research synthesis
slug: prompt-engineering-multi-model-synthesis
publish_date: 2026-05-27
meta_desc: Writing prompts for a single LLM is a different skill from writing prompts for an orchestrator. Here is what changes and why.
tags: prompt-engineering, orchestration, synthesis, multi-model, technique
hero_keywords: prompt engineering, orchestration, model diversity, research briefs
hero_tag: TECHNIQUE
tool_focus: synthesis
author: IntellCluster
reading_time: 9
---

If you've been writing prompts for ChatGPT or Claude for the last two years, you've converged on a style. Role preamble, explicit output format, a handful of worked examples, a request to "think step by step." That style is good. It was purpose-built for the single-model era.

It is the wrong style for an orchestrator.

Prompting a system like [Synthesis](/synthesis) — five models running in parallel, merged by a strategist layer — requires an opposite discipline. You are no longer writing for a single confident voice that needs to be focused. You are writing for five voices that will diverge, and then for a strategist that needs to reconcile them. The prompt moves that work in the single-model world actively hurt you here.

Here is what changes.

## 1. Stop over-specifying the output format

In single-model prompting, you specify the output format early and rigidly: "Respond in JSON with keys `answer`, `confidence`, `sources`." This works because you're shaping one model's output to plug directly into your code.

In orchestrated research, the output is consumed by a human reading a brief, and the merge layer does the formatting. Over-specifying output format has two bad effects:

- The five models produce formally similar but semantically shallow outputs. The structure smooths over the interesting divergence.
- The merge layer can't work with rigidly structured inputs as well as it can with essay-shaped ones, because essays carry the reasoning that makes the reconciliation possible.

The move: **let the models write prose.** Ask for a brief, not a schema. Let the merge layer impose the structure. If you need structured data at the end, add a post-merge extraction step — don't front-load it into the model prompts.

## 2. Stop asking for a single answer

A single-model prompt ends with "what is the best option?" An orchestrator prompt ends with "what are the strongest arguments for each option, and what would make each one correct?"

The mindset shift: you are **not asking five models to converge**. You are asking five models to **cover the answer space**. Their job is to surface different framings, different counter-arguments, different risks. The strategist layer's job is to reconcile.

Prompt the models as if they were five different domain experts giving you independent takes, not five copies of the same assistant competing to give you the same answer.

## 3. Plant intentional disagreement

A great trick: include a sentence in the prompt that invites disagreement with a stated position. "A common view is that X. Evaluate this claim and explain where it holds and where it doesn't."

Without this, five models will all hedge toward the socially safe position. With this, you force each of them to stake out a position on the dimension that matters most, and the resulting diversity is what the merge layer can actually reconcile into a useful output.

This is counter-intuitive. In single-model prompting, you try to *prevent* the model from adopting a contrarian position that might be wrong. In orchestrated prompting, you *want* contrarian positions — because you have four other models to pressure-test them. Diversity of views is the feature, not the bug.

## 4. Use the category signal

Synthesis lets you pick a category — strategy, architecture, research, competitive, risk. This isn't UI decoration. The category routes the prompt through a different orchestration shape (different phase structure, different merge weights, different strategist persona).

The practical advice: **pick the category that matches the shape of the answer you want**, not the shape of the question you are asking. A "what's the right architecture for this feature?" question might feel like strategy, but the answer you want is structured architecturally — so pick architecture. An "evaluate these three market entry options" question might feel like competitive analysis, but if the deliverable is a ranked recommendation, pick strategy.

When the answer shape and the orchestration shape align, the output quality jumps. When they don't, you get a brief that is informative but awkwardly structured.

## 5. Use expert mode selectively

Synthesis's expert mode swaps the model roster for stronger, more expensive models. It is not universally better. It is specifically better for:

- Domain-dense questions where the weaker models hallucinate (medical, legal, obscure technical)
- Long-horizon planning where reasoning chains need to be longer
- Questions where the brief will be consumed by a skeptical expert reader who can spot shallow answers

For most commercial research tasks — competitive analysis, pricing, basic strategy — standard mode produces outputs indistinguishable from expert mode at a third the latency and cost. Default to standard; switch to expert when the ceiling matters more than the throughput.

## 6. Write the brief you want, then reverse-engineer the prompt

The single best prompting trick for orchestrators is:

1. Imagine the ideal 500-word brief the tool would produce on your question.
2. Write the section headings of that brief.
3. Ask the orchestrator for a brief with those sections.

This works because it shifts your cognitive load from "what should I ask" (open-ended, anxiety-producing) to "what do I want the output to look like" (specific, answerable). Four sections of bullet-precise guidance in the prompt beat 20 paragraphs of context every time.

Example. Bad prompt: "Help me understand the competitive landscape for no-code CRM tools."

Good prompt: "I need a brief with four sections: (1) the three dominant product shapes in no-code CRM, (2) the two strongest entrants in each shape, (3) the strategic tradeoffs between the shapes from a buyer's perspective, (4) one clear recommendation for a 15-person sales team with moderate technical capability."

The second prompt constrains the output shape while leaving the reasoning open. That's the sweet spot for orchestration.

## 7. Accept that the orchestrator is slower — and design for that

A single Claude call returns in 4–14 seconds. A Synthesis orchestrator run returns in 28–60 seconds. That's 4× slower. If you treat the orchestrator like a chat assistant and hit it with every question, you will hate the latency.

The design shift: **orchestrated research is an asynchronous tool, not a conversational one.** Kick off the run, do something else, come back. We have users who fire off three Synthesis runs in the morning — one for each meaningful research question of the week — and read the briefs with their coffee an hour later. That workflow is the right one. Treating Synthesis like ChatGPT is treating a restaurant like a vending machine.

In the Synthesis UI we show per-phase progress and per-model status specifically so you can gauge whether it's worth waiting. If a run is going to take 45 seconds, we let you see the five models working in parallel and the strategist layer thinking. Not theater — it's the shape of the work.

## 8. Iterate on the merge, not the model

Here's a move almost nobody makes: if the first brief isn't quite what you wanted, **don't re-prompt from scratch**. Instead, take the brief and ask Synthesis a follow-up that operates on the merged output: "Given this brief, what are the three most important counter-arguments?" or "Summarize this brief for a skeptical CFO."

The merged output is itself a fixed point. Asking questions about it is a cheaper, faster, higher-signal operation than re-running the whole orchestration. The five-model output is the expensive surface; your follow-up questions are the cheap access layer on top.

## 9. Attach sources when you have them

Synthesis (like most orchestrators) works better when you give it anchors. If you have a PDF, a URL, or a document fragment that contains authoritative information about the topic, attach it. The models will weigh your material heavily; the strategist will cite it in the brief.

This shifts the quality ceiling from "what do these five models know about your niche topic" to "what can these five models do with your domain knowledge." For anything proprietary — your company's data, an internal doc, a niche industry — attaching sources is the single biggest quality lever.

## 10. Treat the brief as a draft, not a deliverable

A Synthesis brief is 60–90% of the way to the deliverable you need. The remaining 10–40% is your context, your judgment, and the parts of the question you didn't ask. Don't ship the raw brief. Read it, annotate it, challenge the weakest claim, and rewrite the conclusions with your own framing.

This is not a weakness of the tool. It's the correct division of labor. The orchestrator compresses 5 models' worth of coverage into a structured brief faster than you could; your job is to supply the judgment the orchestrator can't have.

## The broader point

Prompt engineering for a single model is a conversation skill. Prompt engineering for an orchestrator is a **editor's skill** — you are directing a small team of specialists toward a brief you can shape.

The teams that get the most out of Synthesis (and orchestrators like it) aren't writing better single-model prompts. They are writing with an editor's mindset: what are the sections, who is the reader, where does diversity of perspective matter, where does it not, what does the ideal output look like.

If you treat the orchestrator like a chatbot, you will be disappointed. If you treat it like a small research team you are briefing, the results compound.
