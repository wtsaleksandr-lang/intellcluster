---
title: From OKRs to concrete decisions — closing the strategy gap
slug: okrs-to-concrete-decisions
publish_date: 2026-09-16
meta_desc: OKRs tell you what to achieve, not how to decide. Here is how teams translate strategic objectives into weekly concrete decisions — with tooling, not theater.
tags: okrs, strategy, product, execution, decision-framework
hero_keywords: okrs, strategy execution, operational decisions, objective alignment
hero_tag: STRATEGY
tool_focus: phronesis
author: IntellCluster
reading_time: 8
---

Every well-run company has an OKR process. Quarterly objectives, key results, company-wide alignment meetings. Every company that runs OKRs also has the problem: objectives live at one level of abstraction, daily work lives at another, and the bridge between them is usually missing.

"Grow ARR by 30%" is an objective. It does not tell your sales team which segments to prioritize this week. "Launch in two new markets" is an objective. It does not tell your product team whether to build the admin tooling for market A or market B first.

This is the **strategy gap** — the cliff between strategic intent and operational decisions. Most teams fill it with meeting hours, shared docs, and hope. Here's how to fill it with structure instead.

## What the strategy gap actually is

At the objective level (OKRs), you have directional statements. At the execution level, you have specific, discrete decisions: which customer to prioritize, which feature to ship, which vendor to pick, which hire to make. The gap between the two is where most misalignment happens.

Concretely: teams inherit an objective, hold a planning meeting, leave with vague "we should do X" commitments, and then in the next week face a specific decision that doesn't cleanly map to X. They decide anyway, usually based on individual preference. A month later the team notices they're drifting from the objective. By quarter end, the objective is half-hit not because the work was wrong but because the decisions weren't *connected* to the objective.

The fix is not more planning meetings. The fix is a **decision protocol** that connects each operational choice to the strategic frame.

## The three layers

A coherent strategy-to-execution structure has three layers:

**Layer 1: Objectives.** The quarterly OKRs. Abstract, directional, ~5 items.

**Layer 2: Decision criteria.** The weighted criteria the team will use to evaluate choices this quarter, derived from the objectives. This is the layer most teams skip, and it's the most important one.

**Layer 3: Concrete decisions.** The individual decisions made during the quarter, evaluated against the criteria from Layer 2.

If Layer 2 is missing, Layer 3 decisions are made against implicit criteria that vary by who's making the decision. If Layer 2 is explicit and shared, Layer 3 decisions get made consistently across the team, and the cumulative effect is a quarter's worth of work that actually adds up to the objectives.

## Deriving Layer 2 from Layer 1

Here's a concrete process for moving from OKRs to decision criteria.

Take each objective and ask: "What attributes make a choice *better at serving this objective*?" Write those as explicit criteria. Then assign weights based on relative priority.

Example. Objective: "Reduce time-to-first-value for new customers from 14 days to 7 days."

Derived criteria for any product decision in this quarter:

- Does this shorten onboarding flow? (weight: 30%)
- Does this reduce manual setup for customers? (weight: 25%)
- Does this improve the first-use experience? (weight: 15%)
- Does this reduce tickets from new customers? (weight: 15%)
- Does this cost us less than $X to implement? (weight: 10%)
- Does this risk existing customer workflows? (weight: 5%, negative weight)

Now every product decision this quarter — build this feature, fix that bug, investigate this design — gets evaluated against the same criteria. The criteria derive from the OKR. Decisions made consistently against the criteria aggregate into OKR achievement.

## Layer 3: the decision workflow

With Layer 2 in place, each operational decision becomes a structured evaluation. The workflow:

1. **State the question.** "Should we ship the self-serve signup flow redesign now or after the onboarding improvement?"
2. **List options.** At least two. For this example: "Ship signup redesign first / Ship onboarding improvement first / Ship neither, work on something else."
3. **Evaluate against the shared criteria.** The weights are already set; apply them to each option.
4. **Run the compare.** Use [Phronesis](/phronesis) with the criteria you set at Layer 2. Three blind analysts score each option; you get a ranking with confidence.
5. **Act.** Commit to the decision with confidence calibrated to the output.

The critical point: the criteria don't change between decisions. They were set at the quarter kickoff and stay fixed for 12 weeks. This prevents the most common drift pattern — reweighting criteria on a per-decision basis to rationalize the decision you already preferred.

## The "alignment meeting" that isn't

Most alignment meetings are arguments about Layer 2 that pretend to be arguments about Layer 3. The team is stuck on whether to ship feature A or feature B, but the actual disagreement is about whether customer acquisition or customer retention is more important this quarter. That's a Layer 2 disagreement. Until it's resolved at Layer 2, Layer 3 debates will keep getting stuck.

If your Layer 3 meetings are long and circular, the problem is probably at Layer 2. Specifically:

- The criteria weren't explicit at the start of the quarter
- The weights weren't debated and committed
- New criteria are sneaking in that weren't there before
- People are using different implicit weights in their heads

The fix is to pause the Layer 3 argument, surface the Layer 2 disagreement, resolve *that* in a separate meeting, then come back to Layer 3 with the actual decision criteria aligned. This feels slower. It's dramatically faster than continuing to argue Layer 3 without Layer 2 alignment.

## The weekly decision log

Teams that run this structure well typically maintain a weekly decision log: every significant decision made this week, the criteria they were evaluated against, the ranking, and the outcome. The log has four uses:

- **Alignment check.** At the end of each week, is the team's decision pattern consistent with the OKR? If 80% of decisions favored Option A patterns, and Option A patterns don't serve the OKR, the team has drifted.
- **Onboarding tool.** New hires read the log and learn the company's decision-making style faster than from any onboarding doc.
- **Retrospective input.** At end of quarter, the log is the raw material for what worked and what didn't.
- **Audit trail.** For regulated contexts, this is the audit evidence auditors actually want.

Maintaining the log costs one person 30 minutes a week. The return compounds across the quarter and beyond.

## Where Phronesis plugs in

If you're already doing structured decisions, Phronesis is a tool that fits this workflow naturally:

- The criteria set up at Layer 2 is reusable across the quarter — save it as a template, reuse for every Layer 3 decision.
- Each decision produces a standardized output (ranking, confidence, agreement level).
- The outputs can be exported to your decision log in JSON or PDF format, with the metadata attached.
- The tool makes Layer 3 decisions 5–10× faster than an unstructured meeting while producing documents that survive audit.

What Phronesis doesn't do: set the objectives, derive the criteria from the objectives, or align the team on weights. Those are human work, and should stay human work. The tool handles the mechanical compare; humans handle the strategic derivation.

## The "we don't have time for this" objection

Structured decision protocols look like overhead. They don't feel like work, and under deadline pressure they get cut first. The pattern:

- Week 1 of quarter: criteria set, first decisions evaluated carefully, team feels great
- Week 4: pressure builds, "we don't have time for the structure, just ship"
- Week 8: decisions are being made unstructured, drift starts
- Week 12: retrospective reveals the OKRs weren't hit because the decisions weren't aligned

The objection is understandable but wrong. Structured decisions take 10 minutes each. Unstructured alignment meetings take hours. The math doesn't favor skipping structure; it favors making structure cheap enough to use under pressure.

Phronesis's per-decision runtime is 30–90 seconds. The criteria are already set. The evaluation is blind and consistent. It's *faster* than the alternative, not slower. The "no time" objection reflects a mental model from the pre-tool era.

## An example quarter

Let's walk through a compressed example.

**Company:** Mid-stage SaaS, 80 people, 15 engineers, $8M ARR.

**Quarterly OKR:** "Grow paying customers from 450 to 600 (33% increase)."

**Layer 2 criteria (derived and committed in week 1):**

- Does this decision move new-signup conversion rate? (25%)
- Does this decision increase activation (first-week retention)? (25%)
- Does this decision reduce time-to-first-value? (20%)
- Does this decision improve trial-to-paid conversion? (20%)
- Does this decision risk existing customer satisfaction? (10%, negative weight)

**Layer 3 decisions during the quarter (sample):**

- Week 2: Feature A vs Feature B for next sprint. Phronesis ranks A > B; confidence 72%; unanimous on time-to-value dimension.
- Week 5: Hire a product-led-growth PM or another AE? Phronesis ranks PM > AE; confidence 68%; split on "risk to existing customer satisfaction."
- Week 8: Refactor onboarding or add a new integration? Phronesis ranks refactor > integration; confidence 84%; unanimous.
- Week 11: Offer a holiday discount or launch a new upper-tier plan? Phronesis ranks discount > new tier; confidence 56%; analysts split.

Each decision has a documented ranking tied back to the criteria tied back to the OKR. At end-of-quarter retro, the team can trace: which decisions moved the needle? Which didn't? Where did we drift?

## The broader point

OKRs are a planning framework. They don't make decisions for you. Translating OKRs into decisions requires a Layer 2 — explicit weighted criteria — and a Layer 3 — a consistent evaluation protocol for every non-trivial choice.

Most teams have Layer 1. Almost none have Layer 2 written down. A few have Layer 3 as a protocol rather than a meeting. The ones that have all three consistently hit their OKRs not because their objectives are better, but because their operational decisions actually connect to their objectives.

Build the bridge. Set the criteria in week 1. Run the decisions through a tool that makes the evaluation fast and consistent. Log everything. At the end of the quarter, you'll have OKR achievement that actually explains itself, and a decision archive that compounds across quarters.

That's the difference between companies that execute on their plans and companies that plan, execute, and then wonder what happened.
