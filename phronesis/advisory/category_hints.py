"""
Per-category criteria starter kits.

The Criteria Architect Agent is instructed to USE THESE AS GUIDANCE, not as
literal output. They exist because a generic "what criteria matter here?"
prompt tends to produce shallow generic criteria ("cost", "quality", "risk")
for categories where the field has well-known decision frameworks.

Each entry is a list of (criterion_name, typical_weight, rationale_template)
tuples. The Architect may:
  - Use some verbatim if the user's question matches closely
  - Specialize them (e.g. swap "total comp" for "total comp over 3 years")
  - Drop any that don't apply to this specific question
  - Add entirely new ones the kit missed
"""

from __future__ import annotations


CATEGORY_HINTS: dict[str, list[tuple[str, int, str]]] = {
    "career": [
        ("Total compensation over 3 years (cash + equity, risk-adjusted)", 9,
         "compensation trajectory, not just starting offer"),
        ("Skill growth + career narrative in 2-5 years", 9,
         "what the role sets you up for next"),
        ("Quality of team, manager, and engineering culture", 8,
         "strongest predictor of day-to-day experience"),
        ("Optionality (what does this role unlock vs close off)", 7,
         "one-way doors matter more than incremental upside"),
        ("Stress, health, and life fit", 7,
         "a role that breaks you undoes the career gain"),
        ("Location / commute / remote fit", 5,
         "daily friction compounds"),
    ],
    "purchase": [
        ("Total cost of ownership over realistic lifespan", 9,
         "headline price often hides the actual cost"),
        ("Fit for your actual workflow (not the reviewer's)", 9,
         "reviews judge generic use; you have a specific use case"),
        ("Longevity / repairability / resale value", 7,
         "durable purchases compound against per-year cost"),
        ("Opportunity cost of the money spent", 6,
         "what else does this budget buy?"),
        ("Reversibility (return window, resale market)", 5,
         "one-way doors deserve more scrutiny"),
    ],
    "business": [
        ("Time to first dollar of revenue", 9,
         "speed of validation beats perfection of plan"),
        ("Downside exposure if it fails (financial + career)", 9,
         "asymmetric payoff requires survivable downside"),
        ("Market pull (evidence of real demand, not intuition)", 8,
         "pull beats push every time"),
        ("Founder fit (skills, network, obsession)", 8,
         "execution is personal"),
        ("Capital burn rate + runway", 7,
         "cash constraints determine strategy windows"),
        ("Differentiation vs substitutes (why you?)", 7,
         "defensible edge, not just a feature"),
    ],
    "finance": [
        ("Expected return at your realistic time horizon", 8,
         "headline yield without horizon is marketing"),
        ("Downside risk in a bad scenario (worst 10%)", 9,
         "tail risk should drive position sizing"),
        ("Liquidity (how fast can you get out?)", 7,
         "illiquid bets compound reversal cost"),
        ("Tax treatment + complexity", 6,
         "after-tax is what matters"),
        ("Complexity tax (does this need ongoing attention?)", 6,
         "high-maintenance positions quietly underperform"),
        ("Correlation with the rest of your portfolio", 7,
         "a second bet on the same trend isn't diversification"),
    ],
    "vendor": [
        ("Feature fit for your specific use case (not the demo)", 9,
         "demos are optimised for their strongest features"),
        ("Switching cost if this turns out wrong", 8,
         "the price of being wrong > the price of being right"),
        ("Total cost of ownership at projected scale", 8,
         "per-seat pricing + usage tiers"),
        ("Support quality + response time", 6,
         "the tool you pick is the team you call at 2am"),
        ("Vendor financial viability + roadmap credibility", 6,
         "don't build on a dying platform"),
        ("Data portability (exit cost)", 7,
         "if you can't leave, you already lost negotiation"),
    ],
    "relocation": [
        ("Cost of living delta (after-tax, including healthcare)", 9,
         "quoted costs often miss taxes and healthcare"),
        ("Proximity to key relationships (family, friends, network)", 9,
         "social capital takes years to rebuild"),
        ("Career impact (job market depth, remote viability)", 8,
         "some cities close more doors than they open"),
        ("Lifestyle fit (climate, culture, pace, language)", 7,
         "daily life dominates the long-run experience"),
        ("Reversibility (visa / lease / dependencies)", 7,
         "immigration one-way doors carry hidden cost"),
        ("Healthcare and safety quality", 7,
         "systems matter more when you actually need them"),
    ],
    "strategic": [
        ("Expected value vs realistic probability of success", 9,
         "great outcomes × small probability ≠ smart strategy"),
        ("Downside if we're wrong (and how we'd know)", 9,
         "reversibility + kill criteria"),
        ("Resource cost (time, money, team attention)", 8,
         "opportunity cost of the alternatives this crowds out"),
        ("Fit with existing strengths and motion", 7,
         "strategies that fight the company's gravity lose"),
        ("Competitive response likelihood", 6,
         "your move triggers theirs"),
        ("Optionality created for future moves", 7,
         "does this open new doors or close them?"),
    ],
    "personal": [
        ("Alignment with your deeper values (not just preferences)", 9,
         "values-incongruent choices are draining even when 'correct'"),
        ("Effect on people close to you (stated + unstated)", 9,
         "personal decisions have second-party stakeholders"),
        ("Reversibility and regret potential", 8,
         "which direction gives you more freedom later?"),
        ("Short-term friction vs long-term outcome", 7,
         "present-you and future-you have different interests"),
        ("Honesty check (what would you tell a good friend to do?)", 7,
         "self-deception inflates on personal choices"),
    ],
    "exploratory": [
        ("Clarity this choice creates about what you actually want", 8,
         "exploratory decisions are signal-generators"),
        ("Information value: what do you learn from each path?", 8,
         "when you don't know, optimise for learning"),
        ("Reversibility (can you change course cheaply?)", 8,
         "exploration + reversibility = cheap lessons"),
        ("Downside floor if this goes nowhere", 7,
         "protect against worst cases; experiments fail"),
        ("Energy / momentum / excitement", 6,
         "motivation sustains exploration further than logic"),
    ],
}


def hint_block_for(category: str | None) -> str:
    """Render a prompt fragment the Criteria Architect can use as guidance."""
    key = (category or "exploratory").lower()
    entries = CATEGORY_HINTS.get(key, CATEGORY_HINTS["exploratory"])
    lines = [
        f'Category "{key}" commonly benefits from criteria like these. '
        f'Use them as a starting point — adapt, drop, or add based on '
        f"the user's specific question.",
        "",
    ]
    for name, weight, rationale in entries:
        lines.append(f"  - {name}  (typical weight ~{weight}) — {rationale}")
    return "\n".join(lines)
