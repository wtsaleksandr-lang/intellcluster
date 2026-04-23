---
title: A year of 52 decisions — what one framework changed
slug: year-of-52-decisions
publish_date: 2026-09-30
meta_desc: A year of running every meaningful decision through a structured framework. Here is what changed in our outcomes, our meetings, and our team culture.
tags: workflow, retrospective, decision-framework, phronesis, culture
hero_keywords: decision framework, annual retrospective, structured decisions, phronesis
hero_tag: WORKFLOW
tool_focus: phronesis
author: IntellCluster
reading_time: 9
---

A year ago our team committed to a specific experiment: every meaningful decision goes through a structured framework before we act. No exceptions for "obvious" decisions. No "just this once" bypasses. For 52 weeks, if it was a real decision, it got the full treatment.

52 weeks later, the experiment produced more change than I expected. Not in the decisions themselves — the winners were often what we would have picked anyway. In how we *made* the decisions, how our team worked together, and what we learned about ourselves. This is the retrospective.

## The framework, briefly

For context, the structure we used:

1. **Write the question** as a single answerable sentence.
2. **List options** (minimum three).
3. **Set weighted criteria** summing to 100%.
4. **Run [Phronesis](/phronesis)** for blind-jury evaluation.
5. **Debate the split** (if the analysts disagreed).
6. **Decide and document.**
7. **Set a review date** (typically 3 or 6 months).
8. **Revisit at the review date** with actual outcome.

Per decision: 15–30 minutes. Per year: roughly 20–30 hours across the team. Not a trivial overhead. The question was whether it paid back.

## The headline outcomes

**73 decisions logged in 52 weeks.** More than one per week on average — some weeks had three or four, some had zero. The distribution:

- Hiring decisions: 12
- Vendor/tool choices: 11
- Feature prioritization: 18
- Pricing and packaging: 6
- Organizational structure: 4
- Strategic direction: 7
- Technical architecture: 9
- Market/positioning: 6

Of the 73, we've reviewed outcomes on 48 (the ones where enough time has passed). Of those:

- **31 (65%)** outcomes matched our confidence at decision time (confidence in range of actual)
- **11 (23%)** were better than expected
- **6 (12%)** were worse than expected

65% calibration is better than the documented baseline for professional judgment (typically 50–55%). 23% positive surprise and 12% negative surprise is roughly balanced — we're not systematically pessimistic or optimistic about outcomes.

## What surprised me

Five things I didn't expect.

### 1. The decisions changed less than the debates did

I thought structured evaluation would overturn decisions we would have made intuitively. Mostly it didn't. Roughly 75% of the Phronesis winners matched what we would have picked without the framework.

What changed dramatically was the **debates**. Arguments that used to take 90-minute meetings ended in 20 minutes, because the structure forced the disagreement into the open early. You couldn't hide behind "I just have a feeling" — you had to put your feeling into the weights, and then defend the weights.

This is the biggest ROI of the framework, and it's not what I expected. The decisions aren't dramatically better. The *meetings around the decisions* are 2–3× faster, and the team's trust in the outcomes is higher because the process is visible.

### 2. Some decisions got made that otherwise wouldn't have

A subtle effect: when evaluation is cheap, you evaluate more things. Historically we'd defer decisions because the analysis felt disproportionate — "let's revisit in a month." With a 20-minute framework, the analysis isn't disproportionate. Decisions got made on schedule that would have drifted for another quarter.

Estimating loosely, I think we made 10–15 decisions this year that would have drifted in the unstructured version. A few of those turned out to be important — one was a pricing change that we'd been putting off for two quarters, and that moved ARR once we finally committed.

### 3. Disagreement got healthier

Before the experiment, disagreement on my team was compressed. People were polite. They agreed in meetings and then vented afterward. Not a great culture, but common.

The framework changed this specifically. When three blind analyst models split on a decision, it legitimized human disagreement — "even the AI disagrees with itself; it's fine if we disagree with each other." The framework made it socially safe to dissent, because dissent was a structural feature of the process, not a personal rebuke.

A year in, my team argues more than it used to. The arguments are tighter, cite the evaluation output, and resolve faster. Net effect: healthier disagreement culture.

### 4. The review practice was harder than expected

The part I thought would be easy — going back and grading our outcomes 3 or 6 months later — turned out to be the part with the most friction. Nobody wants to read a decision record from a decision that went badly. Our first quarterly review had a 40% completion rate; by Q4 we were up to 85% but it took deliberate culture work.

What helped: making the review a group activity, not an individual one. We sit together for 30 minutes at the end of each quarter and grade the decisions with outcomes known. Group accountability moves completion rates dramatically.

What didn't help: trying to grade every decision. We learned to grade the consequential ones (maybe 6–8 per quarter) and skip the routine ones. Calibration data comes from the ones where outcomes are observable and meaningful.

### 5. The framework exported to parts of work I didn't expect

I thought the framework would live in our product and strategic decisions. It ended up creeping into engineering (pair programming assignments, on-call rotation structure), operations (vendor selection, budget allocation), and even hiring feedback (candidate ranking after loops). The underlying skill — structured weighted comparison — is generic, and once the team had it, they applied it wherever comparison was the bottleneck.

By the middle of the year, I stopped having to prompt people to use the framework. They reached for it on their own because it was faster than the alternative.

## What didn't work

Honest list. The framework has real failure modes.

**Emergency decisions.** When a decision has to be made in 10 minutes — a production incident response, a customer escalation, a rapid-pivot opportunity — the framework is overhead. We learned to explicitly exempt emergencies and not feel guilty about it.

**Pure preference decisions.** Some decisions are values, not analyses. "What's our company's color palette?" is not a weighted-criteria problem. The framework adds nothing; intuition or taste does better. We learned to skip the framework when it's a tie from the start.

**Low-stakes decisions.** "Which SaaS tool for timesheet tracking?" The compare is not wrong, but the time cost outweighs the decision importance. We settled on a threshold: if the decision affects >$5k/year or >1 week of team time, run the framework. Below that, just pick.

**Decisions where one person has domain veto.** If the CFO has strong domain authority on a finance decision, running a group evaluation is theater. The CFO's opinion is the answer; the framework just dresses it up. We learned to respect expert authority and save the framework for decisions where multiple perspectives genuinely add.

## The cultural effect

This surprised me most. A year of structured decisions changes the texture of a team in ways that are hard to name but real:

**More explicit expectations.** Because we document decisions, the documentation becomes context for new hires. Someone joining today reads 73 decisions and understands how we think faster than from any culture doc.

**Less decision debt.** Old decisions get revisited systematically. Drift gets caught. We don't have the "wait, why did we do this?" conversations we used to.

**Higher trust.** Team members trust that decisions were made carefully, even when they disagree with the outcome. Trust compounds across dozens of decisions.

**Better onboarding.** New managers inherit a decision-making pattern. They don't have to invent one. The team doesn't have to re-learn how a new manager makes decisions.

**Reduced dependence on the founder/CEO.** This one is meaningful. If the framework produces good decisions consistently, the team stops needing the CEO to weigh in on every call. The CEO's calendar freed up. The team made decisions without waiting for approval. Velocity went up.

## The quantitative version

Where I can measure the effect, rough numbers:

- **Decision meeting time:** down ~35% (from team survey data)
- **"Undecided" status decisions carried over between quarters:** down from 12 at Q1 start to 3 at Q4 start
- **Decisions reversed within 6 months:** 8 (was 14 in the prior year; so down ~43%)
- **Team NPS on "decisions are made clearly":** up from 28 to 71 (yes, that's large; not all of it is the framework)
- **Time from "we should decide X" to "we decided X":** down median 60%

Causation is not clean for any of these — we made other changes too — but the direction and scale are consistent with the framework being a meaningful contributor.

## What I'd change for year two

Going into year two, three adjustments:

**Lighter protocol for small decisions.** The framework is overkill for half of what we use it on. I want a 5-minute micro-version for low-stakes choices that still produces some structure without the full ceremony.

**Better outcome-tracking tooling.** The review process is manual. Outcomes get logged in notes. A lightweight dashboard that surfaces "here are the decisions that have reached their review date and haven't been graded" would help.

**Cross-team decision visibility.** Right now each team's decisions live in their own folder. Seeing decisions across teams — especially adjacent teams whose decisions affect each other — would catch misalignment earlier.

## The broader point

A structured decision framework is not magic. It doesn't produce obviously better decisions on average. What it does — and this is the underrated effect — is **improve everything around the decisions**: the meeting efficiency, the team's disagreement culture, the onboarding experience, the reduction in decision debt, the trust in outcomes.

The ROI is real but diffuse. If you measure it by "did the framework pick differently than we would have?" you'll probably find limited difference, and conclude it's not worth the overhead. If you measure by meeting time, rework rates, decision debt, and team trust, the ROI is clear.

52 weeks in, I'd recommend the experiment to any team. Not because your decisions will get dramatically better, but because the rest of your operating rhythm will. And the decisions that do improve are often the ones that matter most — the high-stakes, high-ambiguity calls where structure pays off most.

The tool is [Phronesis](/phronesis). The framework is the structure above. The commitment is 52 weeks. The cost is 20–30 hours across the team for the year. The return, in our case, was one of the highest-leverage operational investments I've ever made.

Run your own experiment. I'll re-check mine in another year.
