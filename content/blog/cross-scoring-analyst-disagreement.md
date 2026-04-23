---
title: Cross-scoring — why analyst disagreement is a feature, not a bug
slug: cross-scoring-analyst-disagreement
publish_date: 2026-07-08
meta_desc: Most AI decision tools hide disagreement. Phronesis surfaces it. Here is why the split matters more than the winner, and what to do when analysts disagree.
tags: methodology, disagreement, scoring, blind-jury, confidence
hero_keywords: cross scoring, analyst disagreement, jury split, confidence signal
hero_tag: METHODOLOGY
tool_focus: phronesis
author: IntellCluster
reading_time: 7
---

When we first put the [Phronesis](/phronesis) UI in front of users, a predictable thing happened. They loved the ranked output. They loved the confidence score. And then they got uncomfortable when the three analysts disagreed about the winner.

"Can you make the UI hide the split?" was an actual user request in the first month. "It undermines the recommendation."

We did not do that. The split is the recommendation. Hiding it would have defeated the point of building a multi-analyst tool in the first place. Here's the full argument for why analyst disagreement is a feature, how to read it, and what to do when the jury splits.

## What cross-scoring actually is

Cross-scoring is the technical name for what Phronesis does when it runs three blind analyst models on the same decision. Each analyst produces a per-dimension score for each option, independent of the others. The scores are then aggregated — averaged for the final score, Borda-counted for the rank, tracked for agreement.

The **cross** in cross-scoring is the reconciliation of three sets of scores across the same scoring surface. When the three cross cleanly — all three ranked Option A first — we call that unanimous. When the three diverge — two ranked A first, one ranked B first — we call that split.

Both outcomes are informative. Unanimous says: the option dominated across three very different priors. Split says: the option space is genuinely close, and your priors matter.

## Why most tools hide splits

Most AI tools that do structured comparison present a single answer. Some of them *are* running multiple internal calls and voting internally; the user never sees the vote. The reason is product-design pressure: a single confident answer feels more valuable, reviews better in demos, and sells better.

The cost is epistemic. When the tool hides the split, the user cannot distinguish:

- A decision where all priors agreed (robust winner)
- A decision where 2 of 3 priors agreed (probable winner, close call)
- A decision where 2 of 3 priors agreed *but one prior would have picked the runner-up* (genuinely ambiguous)
- A decision where the tool rolled a dice between two near-ties (basically random)

From the outside, all four look the same — a single answer with a confidence number. The splits-hidden architecture deletes exactly the information that would help the user calibrate their trust in the output.

Phronesis inverts this. We show the split explicitly. We report the agreement count. We tell you when the analysts disagreed on a specific dimension, not just on the overall winner. The UI burden is slightly higher. The epistemic value is dramatically higher.

## Reading the split

A Phronesis output has three agreement signals to look at:

1. **Overall winner agreement** — did all three analysts pick the same #1?
2. **Per-dimension agreement** — for each criterion, did the analysts score consistently?
3. **Score spread** — how far apart are the three scores for the winner?

Start with overall agreement. If unanimous, move to the weakness analysis and commit. If split, don't commit yet — the question isn't ready.

Next, look at per-dimension agreement. This is often the most actionable signal. If analysts agree on 5 of 6 dimensions and split on the 6th, you've found the crux. The decision depends on that one dimension, and the honest answer is "we need more information specifically about criterion X." That's a much cheaper thing to go learn than re-running the entire evaluation.

Finally, score spread. If the winner got 8.2, 8.3, and 8.1 from the three analysts, the confidence is high. If the winner got 6.5, 8.5, and 7.8, something weird is happening — one analyst thinks this option is bad, two think it's good. That spread should trigger a closer look at the bad score's weakness analysis.

## What causes splits

We've run the numbers across thousands of Phronesis runs. The most common causes of analyst split:

**Criteria that are value-laden.** "Best for creative freedom" is a criterion that produces splits reliably because the analysts interpret "creative freedom" through different priors. A Skeptic analyst reads it as "constraint-free"; a Pragmatist reads it as "within a framework." They score the same option differently.

**Options that are close on aggregate but tradeoff on specifics.** If Option A beats Option B on price and loses on reliability, with roughly balanced weights, the three analysts will split based on how they resolve the tradeoff. This is a real signal — the decision genuinely is a values call, and no tool can settle it for you.

**Criteria that depend on context the prompt didn't include.** "Best for a startup" produces splits because "startup" means different things (2-person, 20-person, 200-person). The analysts split based on which startup they mentally anchor on. The fix is to tighten the prompt, not to reconcile the split.

**Ambiguity in the options themselves.** If "AWS" is an option but you didn't specify which service set, the analysts may score it differently based on which services they prioritize. Split is a signal to re-specify the options.

## What to do when analysts split

Four moves, in rough order of preference:

### 1. Tighten the question

If the split is driven by prompt ambiguity, fix the prompt. Re-run. Most of the time, the split collapses and you get a clean winner. The first-round split paid for itself by exposing the ambiguous word.

### 2. Pull in the human tiebreaker

If the split is a real values tradeoff (reliability vs price, breadth vs depth), no amount of prompt tightening will resolve it. This is where a human with authority to make the values call earns their keep. Read the three analysts' scoring rationales, decide which tradeoff framing matches the team's actual values, and commit.

This sounds unsatisfying. It's the correct answer. The tool's job is not to tell you what you value. It's to surface *where* your values matter and give you structured language to discuss them.

### 3. Run a second pass with different weights

Sometimes the split is driven by the weights. If the analysts split 2–1, try swapping the weights on the contested dimension — e.g., if you weighted price 15%, bump to 25% and see what happens. If the split collapses at 25%, you've learned that the decision is sensitive to how much you care about price, which is actionable.

### 4. Accept the split

If the split is real, the question is real, and the decision will be close however you cut it. Accept that and pick. An analyst-split decision made deliberately is better than an analyst-split decision disguised as consensus. Document the split in the decision doc — future-you will thank you for the honesty when the outcome lands anywhere but clearly right.

## The confidence correlation

Here's the data that surprised us most in our own benchmark. When the three analysts agreed unanimously, their average self-reported confidence was 78%. When they split 2–1, it was 62%. When they split 1–1–1 (all three picked different winners), it was 48%.

Those numbers map cleanly to outcome quality. Decisions made on unanimous Phronesis runs correlated with "would decide again the same way" ratings at 83%. Decisions on 2–1 splits, 64%. Decisions on 1–1–1 splits, 51%.

Two takeaways. First, the agreement signal is genuinely predictive of decision quality — it's not just visual theater. Second, humans should trust unanimous outputs more than split outputs *by a lot*, and the tool gives you the information to do that.

## The "why not force agreement" question

A reasonable engineering question: why not have the analysts negotiate until they agree? That's how human juries work, after all.

Two reasons we don't.

**The negotiation collapses diversity.** If Analyst 3 changes their mind to match Analysts 1 and 2, you've lost the very signal you wanted — the genuinely different prior that produced the different ranking. You'd be back to a single-prior output with extra steps.

**Agreement-forcing is epistemically worse than honest disagreement.** A 3–0 agreement that required negotiation is weaker evidence than a 3–0 agreement that happened independently. By keeping the analysts blind to each other's scores, we preserve the independence that makes the agreement meaningful in the first place.

Phronesis's output is therefore *honest about uncertainty*. If the analysts split, the tool tells you they split. It doesn't pretend to be more confident than the evidence supports.

## The broader point

The most valuable thing an AI decision tool can do is not hand you a confident answer. It's to give you **calibrated uncertainty** — an honest signal of when the evidence supports strong action and when it doesn't. Analyst disagreement is the signal. Hiding it produces a tool that sells better and helps less.

So when you run a Phronesis decision and the analysts split, don't consider it a bug or a failure of the tool. The tool is working. It's telling you: **the decision is close, the evidence is mixed, the values call is yours, and you should treat the outcome with appropriate humility.**

That's a useful thing for a tool to say. It's the thing the spreadsheet never says.
