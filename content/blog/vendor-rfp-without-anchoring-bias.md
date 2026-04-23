---
title: How to run a vendor RFP without anchoring bias
slug: vendor-rfp-without-anchoring-bias
publish_date: 2026-07-15
meta_desc: Most vendor RFPs are anchored by the first vendor to present. Here is a debiased RFP protocol that pairs structured evaluation with blind AI scoring.
tags: procurement, rfp, vendor-selection, anchoring-bias, methodology
hero_keywords: vendor rfp, anchoring bias, debiased procurement, blind scoring
hero_tag: METHODOLOGY
tool_focus: phronesis
author: IntellCluster
reading_time: 8
---

If you've run even a few vendor RFPs, you've felt the pattern. The first vendor does their pitch. They're polished. They set a tone, a vocabulary, a framing of what a "good solution" looks like. Every vendor that follows either conforms to that frame (looking like a weaker version of the first) or breaks it (looking like they didn't read the brief). Either way, the first vendor has already shaped the evaluation.

This is anchoring, and it costs organizations significant money in misattributed wins. Here's a debiased RFP protocol that accounts for it — paired with a blind-scoring step using [Phronesis](/phronesis) that removes the evaluator's own anchoring from the ranking.

## The anchoring cost

Classic research by Tversky and Kahneman found that numerical anchors shift estimates by 20–50% even when the anchor is obviously arbitrary. In vendor selection, anchoring isn't about a number — it's about the conceptual frame the first vendor plants.

A concrete example. Three vendors pitching a customer support platform. Vendor A opens with "modern support is agent-first — the tool should be judged on what the agent sees." Vendor B opens with "modern support is customer-first — the tool should be judged on what the customer experiences." Both framings are legitimate. The first one plants the evaluation criteria in a particular direction. Vendor B, going second, now has to fight the frame before they can pitch their solution — or conform to it and pretend their product is agent-first when it isn't.

The evaluator doesn't consciously notice. The final ranking comes out favoring whichever framing was established first, independent of which product is better.

## The five debiasing moves

The protocol below removes or compensates for the dominant anchors. It takes more upfront work than most procurement processes; it saves significant rework later.

### 1. Write the evaluation criteria before any vendor contact

This is non-negotiable. Before any vendor has pitched, demoed, or sent a PDF, the buying team writes the evaluation criteria with weights. No vendor input, no vendor reference documents, no vendor-sourced "things to consider."

If you write the criteria after seeing one vendor, the criteria are polluted by that vendor's framing. If you write them before, they reflect **your** priorities, which is what you want the evaluation to measure.

Minimum spec for this step: 6–10 criteria, each with a weight summing to 100, each with an explicit rubric of what "score 8" and "score 3" look like. The rubrics are the anti-anchoring device — they give the scorer a reference that isn't the last vendor they talked to.

### 2. Randomize vendor order

If three vendors are pitching, randomize who goes first. Different evaluators see different orders. This simple step cuts the "first vendor advantage" significantly because no single vendor gets the benefit of anchoring every evaluator.

For written RFPs, randomize the order in which evaluators read the responses. Google Sheets' random number function is enough.

### 3. Score async and blind

Once vendor materials are in, evaluators score independently and asynchronously. No group meeting until everyone has submitted scores. This prevents the loudest voice from anchoring the room during evaluation.

Better: redact the vendor names from the materials being scored. Call them Vendor 1, Vendor 2, Vendor 3. This is harder than it sounds for RFPs because logos and brand language leak everywhere, but it's doable for the qualitative responses. The score is more honest when the name isn't on it.

### 4. Run a blind-jury AI pass

After human scoring, feed the redacted vendor materials to [Phronesis](/phronesis) with the same criteria and weights. Three analyst models will score the options blindly — they have no name to anchor on, no relationship to leverage, no sunk cost in having championed one vendor earlier.

Compare the human ranking to the AI ranking. **Where they agree**, your confidence in the decision is high. **Where they diverge**, investigate. Usually the divergence reveals one of three things:

- A criterion the humans applied differently than the rubric specifies (this is a scoring discipline issue, fixable)
- A dimension where the AI weighted evidence differently than humans (this is informative — sometimes the AI is more right, sometimes less)
- An anchoring bias the humans didn't notice (this is the one the protocol was designed to catch)

### 5. Document the divergence before the meeting

Before the decision meeting, write a one-pager summarizing: where humans agreed, where humans disagreed, where the AI ranking matched, where it didn't. Distribute the one-pager. Now the meeting starts from a document of structured disagreement instead of a round-robin of opinions.

## What this protocol costs

Roughly, compared to a typical RFP:

- **Criteria writing:** +4 hours (most teams skip this step)
- **Randomization:** +10 minutes
- **Async scoring:** About the same duration as meeting-based scoring, but shifted to individual time
- **Phronesis pass:** 2 minutes of wall clock, ~$0.50 of API cost
- **Divergence doc:** +2 hours

So maybe 6–8 extra hours of calendar time for an RFP that was going to take 3+ weeks anyway. In exchange, you get a structured, auditable, bias-compensated decision that your CFO can look at and understand how it was made.

## The incumbency trap

One specific bias worth naming separately: **incumbency bias**. If you're running an RFP that includes your current vendor, the current vendor has an anchor no amount of randomization solves. Every evaluator already has a mental model of the product. Their mental model is usually a mixture of real features and idiosyncratic recent memories (a bad support ticket, a great release, a rep they like).

Two moves that help:

**Evaluate the incumbent against the criteria, not the memory.** Write out the incumbent's features against each rubric dimension. Score from the current state, not from the vendor's trajectory. "They've gotten so much better lately" is not a rubric dimension.

**Include a credible churn threat in the evaluation.** Before the RFP, decide what switch trigger you'd accept. If the new vendor scores 10% higher, do you switch? 20%? 30%? Decide the threshold in advance. If you don't, the incumbent will win any close call by default.

Vendors know this, which is why incumbents almost always offer a "renewal discount" when an RFP starts. That discount is specifically priced to make the switch threshold higher. Recognize it as an anchor and hold your threshold.

## Where the AI pass adds the most value

The blind-jury AI pass is most valuable in three scenarios:

**When evaluators have uneven domain expertise.** If one person on the evaluation team deeply understands the category and the others don't, their opinion anchors everyone else. A blind AI pass provides an external benchmark that's not anchored by the expert.

**When the stakes are high and the timeline is compressed.** Compressed timelines amplify bias because there's no time for the protocol to breathe. A 2-minute AI pass is the single highest-leverage anti-bias move under time pressure.

**When there's political weight behind one vendor.** Someone senior wants Vendor A. The protocol is supposed to evaluate fairly. A blind AI pass, reported in writing, gives you a document that's harder to argue with than your own opinion. It doesn't force the senior person to change their mind, but it makes the "because I say so" outcome more visible if it happens.

## A short script for the AI pass

Once your vendor materials are redacted and your criteria + weights are locked, the Phronesis input looks like:

- **Question:** "Which vendor best fits our requirements for [category]?"
- **Options:** "Vendor 1, Vendor 2, Vendor 3" (with the redacted content as attached context)
- **Criteria:** Your 6–10 weighted criteria, with rubrics attached as notes

Phronesis runs three analyst models, produces ranked output with per-dimension scores and confidence. The total run is under 2 minutes.

The output is input to your decision meeting, not the output of it. The humans still decide. But the decision meeting starts from a structured comparison instead of from scratch.

## What to do when humans and AI disagree

Don't assume the AI is right. Don't assume the humans are right. The disagreement is data.

Ask: *why* did we score this differently? Usually the answer is one of:

1. **The rubric was applied differently.** Fix by re-scoring with the rubric in front of you.
2. **The AI had less context than humans.** Some dimensions (e.g., "will this vendor be a good partner over 3 years") depend on relationship and gut feel that the AI can't access. Weight those appropriately.
3. **The humans had less objectivity than AI.** Some dimensions (e.g., "is the technical architecture scalable") should be more blind. Weight those toward the AI.
4. **The criteria were under-specified.** If the same criterion produced wildly different scores, the criterion's rubric wasn't tight enough.

Each answer points to a specific improvement. The disagreement is the debugging trace of your evaluation process.

## The broader point

Vendor RFPs are not rituals of pure analysis. They are social processes with real stakes, incumbent relationships, and compressed timelines. Anchoring isn't a flaw of weak evaluators — it's a structural feature of the process.

The fix is not to ask evaluators to try harder. The fix is to change the structure of the process so that anchoring gets compensated for rather than internalized. Write criteria first. Randomize order. Score async and blind. Add a blind-jury AI pass. Document divergence before the meeting.

Do this for your next three RFPs. Your decisions will get measurably better, and — just as important — your team will get better at *knowing* when a decision is robust versus when it's a coin flip dressed in rigor.

That epistemic calibration is worth more than any single good vendor choice. It's how you get better at the next five decisions, not just this one.
