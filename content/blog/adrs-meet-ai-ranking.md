---
title: Architecture Decision Records (ADRs) meet AI ranking
slug: adrs-meet-ai-ranking
publish_date: 2026-09-23
meta_desc: Architecture Decision Records are a proven engineering practice. Pair them with AI-ranked evaluation and you get both rigor and speed. Here is how.
tags: engineering, architecture, adrs, decision-records, phronesis
hero_keywords: architecture decision records, adr, engineering decisions, ai ranking
hero_tag: ENGINEERING
tool_focus: phronesis
author: IntellCluster
reading_time: 7
---

Architecture Decision Records — ADRs — are one of the strongest decision-documentation practices the software engineering community has produced. The format is simple: one Markdown file per significant architectural decision, with sections for context, options, decision, and consequences. Thoughtworks popularized it, GitHub made it easy to store, and most serious engineering organizations now maintain an ADR repository.

ADRs solve one half of the decision problem: documentation. They don't solve the other half: evaluation. Most ADRs explain *what* was decided but give only cursory treatment to *how*. The "options considered" section is usually two paragraphs, not a structured comparison. The decision rationale is usually a single developer's opinion, not a multi-analyst compare.

Pair ADRs with AI-ranked evaluation and you get both: the documentation rigor that's made ADRs popular, plus the evaluation rigor that makes the decisions actually defensible.

## The ADR template, refreshed

A standard ADR has:

- **Title:** "ADR-042: Choose between PostgreSQL and MongoDB for event store"
- **Status:** Proposed / Accepted / Deprecated / Superseded
- **Context:** Why we're deciding, what's at stake
- **Options:** What we considered
- **Decision:** What we picked and why
- **Consequences:** What changes, what breaks

The standard format has been around for a decade. It works. Its limitation is that the "Options" and "Decision" sections rely on a human to do the comparison, and most humans either under-document it (single paragraph) or over-document it (ten pages of wandering prose).

Here's a refreshed template that plugs in AI-ranked evaluation:

- **Title**
- **Status**
- **Context**
- **Options Considered** (at least three)
- **Evaluation Criteria** (with weights, summing to 100)
- **Blind Jury Results** (Phronesis output attached)
- **Decision**
- **Rationale** (addressing dissent)
- **Consequences**
- **Review Date**

Two additions: **Evaluation Criteria** with explicit weights, and **Blind Jury Results** with the structured compare output. Both take 10 extra minutes to produce. Both dramatically improve the quality of the artifact.

## Why engineers undervalue structured evaluation

Engineers are typically comfortable with the documentation side of ADRs but resistant to the evaluation side. Three reasons:

**The "I know this space" reflex.** Engineers have strong priors about their tools. Evaluating PostgreSQL vs MongoDB feels redundant when you already know which you prefer. But "I know" is the same cognitive state that produces bias; the blind-jury evaluation specifically compensates for the prior.

**The "tools don't understand my codebase" objection.** True in the weak sense — a generic AI tool doesn't know your specific performance characteristics. Less true in the strong sense — the evaluation is mostly about generic tradeoffs (consistency, schema flexibility, operational complexity, community maturity) that apply to your codebase as much as anyone's. Attach your context as a constraint; the tool handles the rest.

**The time cost.** Engineers know ADRs are worth writing and still often skip them because they feel slow. Adding a structured evaluation step seems like more slowdown. It's actually faster than the unstructured alternative once the criteria are set up.

The fix is not to force engineers to do something they resist. It's to make the structured evaluation so lightweight that the resistance evaporates. A [Phronesis](/phronesis) run on the options takes 60 seconds. The output drops directly into the ADR as the "Blind Jury Results" section. Total added time: 2–3 minutes.

## A concrete ADR example

Let's walk through a real-shaped ADR for a decision I see teams make constantly: "Choose an event store."

### Title
ADR-042: Choose event store technology for order service

### Status
Accepted

### Context
We're building the order service for the e-commerce platform. Orders emit events (OrderCreated, OrderPaid, OrderShipped, OrderCancelled). We need persistence for these events that supports:
- High write throughput (projected 2k events/sec peak)
- Event replay capability
- At-least-once delivery semantics
- Reasonable operational complexity
- Integration with our existing stack (Kubernetes, Go, Postgres-heavy)

### Options Considered
1. **PostgreSQL with outbox pattern** — use our existing Postgres, add an outbox table with a Debezium CDC stream
2. **Kafka** — dedicated event store, tight fit for event-streaming semantics
3. **EventStoreDB** — purpose-built event sourcing database
4. **DynamoDB Streams** — managed AWS solution if we were cloud-locked (we're not, but flagged for completeness)

### Evaluation Criteria
- Operational burden (weight: 25%)
- Performance at projected scale (weight: 20%)
- Event-sourcing semantic fit (weight: 15%)
- Integration with existing stack (weight: 15%)
- Team familiarity (weight: 10%)
- Cost at projected scale (weight: 10%)
- Exit cost (weight: 5%)

### Blind Jury Results
Phronesis run: `phronesis-a73b9c2f`
- Winner: **PostgreSQL with outbox pattern**
- Confidence: 78%
- Analysts: Unanimous
- Per-dimension highlights:
  - Operational burden: Postgres unanimous (8.8/10) — we already run it
  - Event-sourcing fit: EventStoreDB leads (8.2/10) but Postgres close behind (7.5/10)
  - Performance at scale: Kafka leads (9.0/10); Postgres at 2k/sec is well within limits
  - Team familiarity: Postgres unanimous (9.5/10); we have no Kafka ops experience
  - Exit cost: Postgres leads (9.0/10) — data is in SQL, easily exported

### Decision
PostgreSQL with outbox pattern and Debezium CDC.

### Rationale (addressing dissent)
Three of our senior engineers initially advocated for Kafka based on its event-streaming fit. The blind-jury analysis surfaces that Kafka's advantages (event-sourcing semantic fit, peak performance) are real but don't compensate for our 0 team experience with Kafka operations and the 3-month ramp to production-readiness. Postgres at 2k/sec is not a stretch; we've tested at 5k/sec in staging. Revisit this decision if projected peak exceeds 10k/sec, at which point Kafka's performance advantage becomes load-bearing.

### Consequences
- Adds Debezium to our infrastructure stack (new component to operate)
- Couples event store to order service's Postgres (trade-off: simpler ops, some coupling risk)
- Event replay is slower than in a purpose-built event store (acceptable for current use cases)

### Review Date
2027-03-23 (6 months). Re-evaluate if throughput projections change materially.

---

That's a real ADR with real structure. The Blind Jury Results section is what most ADRs are missing. It took maybe 3 extra minutes to produce, and it makes the decision dramatically more defensible in the future "why did we pick Postgres over Kafka?" conversation.

## The "revisit in 6 months" move

One underused section of the refreshed ADR template: the Review Date. Most ADRs are written once and filed. Engineering context evolves; the decisions that were right in 2024 may not be right in 2026.

A 6-month review cadence keeps the ADR archive honest. At the review, re-run the Phronesis evaluation with updated context. If the ranking changes, either update the ADR with a new decision or document why the old decision still holds despite the changed context. Either outcome produces durable value.

The review is cheap because the criteria and options are already in the original ADR. You're not starting from scratch; you're updating the evaluation with new facts. 15 minutes per ADR review, twice a year. Engineering teams that do this systematically have dramatically better architectural decision quality over time, because they catch drift early.

## Where AI-ranked evaluation adds the most value

Three ADR types where the blind jury pays off most:

**Framework choice.** "Which frontend framework?" or "Which ORM?" These are high-emotion decisions where team preference is strong. The blind jury compensates.

**Technology migrations.** "Should we move off vendor X?" The incumbent has a massive anchor (existing familiarity, sunk cost). A neutral compare is especially valuable here.

**Cross-team standardization.** "Should we standardize on Language/Framework/DB X across teams?" These decisions affect many stakeholders; a documented structured evaluation survives the political headwinds better than a single team's opinion.

And where it adds less value:

**Tightly-scoped one-time decisions.** "Should this function be synchronous or async?" Too small, evaluation overhead exceeds value.

**Decisions with clear dominant criterion.** "Which cloud region to deploy in for our US-East customer base?" The criterion dominates; structured compare is overkill.

**Purely operational choices.** "Which log format?" "Which error-tracking tool?" Low-stakes, reversible, not worth the ceremony.

## The "no ADRs" failure mode

A specific anti-pattern: engineering teams that don't maintain ADRs at all. Every decision lives in Slack threads, JIRA tickets, and one person's head. Nine months later, nobody remembers why the event store is Postgres; the person who made the call left in July.

The cost is compounding technical debt. Decisions get revisited because nobody can find the original rationale. Revisiting without the original rationale produces incoherent architecture — this-era's engineers making local optimizations without the context of prior era's global optimization.

The fix is structural. Either:

1. Mandate ADRs for every architectural decision above a threshold (more overhead, more rigor)
2. Add ADRs as a pull-request requirement for any commit touching a core component
3. Hold a weekly "what decisions did we make" meeting to surface recent decisions for ADR-ification

Option 3 is the lightest and often the most effective. The meeting is 20 minutes a week. The output is 2–5 new ADRs per month. Over a year, the archive becomes a genuine engineering asset.

## The broader point

ADRs are the best solution we have for the engineering decision-documentation problem. Adding AI-ranked evaluation to the template closes the gap on the *evaluation* half that ADRs typically under-serve. The combination — structured document + structured compare — produces an artifact that's both rigorous in its analysis and durable as a historical record.

If your team already writes ADRs, add the Evaluation Criteria and Blind Jury Results sections. If your team doesn't write ADRs, start. The time cost is minimal; the compounding benefit across years is enormous.

Most engineering teams look back on three years of architectural decisions and can't reconstruct why half of them were made. Teams with well-maintained ADRs can — and that's the difference between an engineering culture that learns from itself and one that repeats itself.
