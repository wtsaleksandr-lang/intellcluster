---
title: Hiring decision templates — senior engineer, PM, and designer
slug: hiring-decision-templates
publish_date: 2026-08-05
meta_desc: Most hiring decisions are gut-feel theater dressed up as analysis. Here are three weighted-criteria templates for senior roles, and how to run them blind.
tags: hiring, templates, decision-framework, recruiting, leadership
hero_keywords: hiring decisions, senior engineer, product manager, designer templates
hero_tag: TEMPLATES
tool_focus: phronesis
author: IntellCluster
reading_time: 9
---

Hiring is the single most expensive decision most companies make, per dollar of consequence. A bad senior hire costs $200k–$500k directly (salary, severance, replacement) and multiples more in team damage. A great senior hire compounds for years. And yet the average hiring process is theatrically rigorous on the front end (five interviews, a take-home, a panel) and terrifyingly casual on the decision itself — a 45-minute debrief where the loudest voice wins.

Here are three weighted-criteria templates for senior roles, plus how to run the debrief through [Phronesis](/phronesis) so the decision survives scrutiny.

## Why hiring debriefs fail

A standard debrief has four structural problems.

**The first speaker anchors.** Whoever says "I thought she was strong" first sets the tone. The next speakers either agree (cascade) or feel obliged to find a contrarian position. Neither is evaluation.

**Recent interviews dominate memory.** The panel remembers the final-round interview vividly and the first-round interview barely. Candidates evaluated in the same loop get scored against different reference points.

**Criteria are implicit.** Most debriefs don't start with a written criteria set. "Is she a culture fit?" is a criterion; what it means depends entirely on who's answering.

**The hiring manager has veto.** Which means everyone else's input is advisory at best. Why do the debrief at all if the decision is already made?

The fix is structural. Written criteria, individual scoring, blind-jury compare, then debate.

## Template 1: Senior Engineer

A weighted-criteria model for a senior individual-contributor engineer:

- **Technical depth in our stack** — 20%
- **Systems thinking and design judgment** — 20%
- **Code quality (from take-home or sample)** — 15%
- **Collaboration and communication** — 15%
- **Ownership and initiative (evidence from past work)** — 10%
- **Speed of execution (demonstrated throughput)** — 10%
- **Mentorship signal** — 5%
- **Culture add (not fit — add)** — 5%

Each panelist scores independently on a 1–10 scale with a written rationale. The scores are aggregated into a weighted final score per candidate.

Important notes on this template:

- **"Culture add" not "culture fit."** Culture fit is a legally risky criterion that often hides bias. Culture add is "what new thing does this person bring that we don't already have." Different question, better criterion.
- **"Technical depth" should be specific to your stack.** If you're evaluating a Go engineer to join a Go team, the criterion is Go depth, not generic software engineering. Specificity reduces the scoring spread and makes the criterion actually useful.
- **"Speed of execution" is hard to measure.** Use it cautiously. The best signal is usually the candidate's past work references — ask explicitly about throughput, not code quality.

## Template 2: Senior Product Manager

Different role, different criteria:

- **Product judgment (from portfolio cases)** — 25%
- **Strategic thinking (business model comprehension)** — 20%
- **Stakeholder management (from behavioral interviews)** — 15%
- **Data literacy (from take-home or analytics walkthrough)** — 10%
- **Technical fluency (can they work with engineers)** — 10%
- **Writing quality (from written exercise)** — 10%
- **Initiative and ownership (from past work)** — 10%

PMs are judged more on judgment and less on technical depth than engineers, which is why the top weight is product judgment. A common failure mode: weighting "technical fluency" too high because engineers on the panel want a PM who codes. That's usually the wrong tradeoff — you're hiring for product judgment, and technical fluency should be a threshold (above some bar), not a main criterion.

If you want to launch this with real seed data, Phronesis has a [hire-senior-pm template](/templates/hire-senior-pm) with these criteria pre-filled.

## Template 3: Senior Designer

Designers span specializations (product design, brand, UX research, design systems). The criteria differ, but a general template for a senior product designer:

- **Craft quality (from portfolio)** — 25%
- **Process and methodology (from case studies)** — 20%
- **Product sense (from critique exercise)** — 15%
- **Collaboration (from behavioral)** — 15%
- **Systems thinking (design systems, patterns)** — 10%
- **Writing and communication** — 10%
- **Strategic contribution** — 5%

The craft weight is higher than for PMs because craft is more directly load-bearing for designers. The process weight is high because the craft quality of the finished artifact can mislead — what you care about is whether the designer can reach that quality on your next problem, which is a process question.

A specific warning for designer hiring: **portfolios lie by omission.** Designers show their best work. The case study that explains *how* they got there — especially the parts where they were wrong and course-corrected — is the actually informative artifact. Weight portfolio craft at 25% and the case study at 20%; together they tell you 45% of what you need.

## Running the compare blind

Once you have 2–4 final-round candidates and the panel has submitted individual scores, run the compare through [Phronesis](/phronesis):

- **Question:** "Which candidate should we hire for [role]?"
- **Options:** Candidate A, Candidate B, Candidate C (labels redacted)
- **Criteria:** Your weighted criteria
- **Context:** The panel's aggregated scores per candidate per criterion (with the rationales stripped of identifying information)

Phronesis's three blind analysts will evaluate the weighted scoring and surface:

- The winner
- Per-dimension agreement (which candidate was strongest on which criterion)
- Confidence (how close the ranking is)
- Where the analysts split

The output is input to the debrief, not a replacement. But it's input that isn't anchored on the first speaker, doesn't suffer from recency bias, and reflects the criteria everyone agreed on upfront.

## The debrief protocol

After Phronesis has produced its output, run the debrief like this:

1. **10 minutes:** Hiring manager shares the Phronesis output. Reads the winner and the key disagreements.
2. **10 minutes:** Each panelist shares one observation that isn't in the structured scoring — a qualitative signal they want on the record.
3. **15 minutes:** Debate the split dimensions. Where the analysts disagreed is where the panel should spend its time.
4. **10 minutes:** Decision. The hiring manager makes the call with the panel's input fresh.

Total: 45 minutes. The decision is written in the same document as the scores. Three months later when you want to audit "how did we hire this person," the doc answers the question.

## The dimensions nobody weights

A short list of criteria that deserve weight but usually don't get it:

**Team dynamics.** How will this person change the balance of the team? Are they the 3rd senior engineer (great) or the 6th (redundant)? The team-composition question is almost never on the criteria list, and it matters a lot.

**Ramp time.** How long until this person is productive? Someone who can start contributing in 2 weeks is worth a real premium over someone who needs 2 months. For hiring into a crisis, ramp time is a major factor. For hiring into a growth role, ramp time matters less.

**Retention probability.** Senior hires who leave in year one are catastrophically expensive. References, career trajectory, and compensation expectations all feed into retention probability — but the criterion itself is rarely explicit.

**Seniority calibration.** Is this "senior engineer" on your level calibrated to your company's bar, or to their last company's? Titles don't port cleanly. If you hire a "staff engineer" from Big Tech who would be a "senior engineer" at your scale, the expectations will misalign expensively.

These criteria are hard to score. They're also the criteria that separate companies that reliably hire well from companies that roll the dice. Add at least one of them to your template.

## The written offer as a commitment device

Once you've decided, write the offer. Not just the comp numbers — write the expectations: what this person will own, what success looks like in 90 days, what success looks like in a year. Give it to the candidate and to the team.

This isn't just for the candidate. It's for you. A written offer forces you to commit to specifics. "We're hiring you to own the data platform" is a different offer than "we're hiring you for broad ownership." The first is a decision. The second is a procrastination.

Weak offers hide behind abstraction. Strong offers specify. And the act of writing the specific offer often surfaces decisions about scope and ownership that the hiring process glossed over.

## The exit-interview loop

A hiring-process improvement tip almost nobody implements: **exit-interview every new hire at the 6-month mark about the hiring process itself.** What was signal, what was noise, what did we miss about them that we should have caught, what did they experience that we should improve. The person who just lived through your process has the highest-signal feedback you'll ever get.

Feed the feedback back into the criteria template for the next hire in the same role. Six months of hiring later, your criteria template is markedly better than the industry default, because it's been tuned against actual outcomes.

## The broader point

Hiring is a decision problem. The companies that hire well are not the ones with better instincts — they're the ones with better protocols. Weighted criteria, individual scoring, blind-jury compare, structured debrief, written offer, outcome tracking. None of it is complicated. Most companies don't do it because the effort feels disproportionate to a single decision, and then compound the cost over every hire they make badly.

Use the templates above as starting points. Adjust the weights for your specific role. Run [Phronesis](/phronesis) on the final four. Spend 45 structured minutes on the debrief. Document the decision. Loop the outcome back into the process six months later.

Your hiring will measurably improve, and — just as important — you'll stop having the "how did we end up here?" conversation when a hire doesn't work out. The decision trail will tell you exactly how.
