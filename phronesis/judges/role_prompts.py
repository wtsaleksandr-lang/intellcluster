"""
Role-specialized judge prompts (v2).

v1 used three "perspectives" that all scored the same dimensions with subtle
framing differences — closer to ensembling than specialization. v2 replaces
this with three judge ROLES that each produce structurally different content:

  * risk_modeler: identifies failure modes, weights downside dimensions
  * base_rate_finder: applies historical priors, reasons from frequencies
  * devils_advocate: builds the strongest case AGAINST the leading option

Each role keeps the dimension scoring contract (so the existing aggregator
can sum them) but the system prompts steer toward genuinely different
analytical work. Per the Mixture-of-Agents literature, role-specialization
yields ~2-3x the accuracy lift of naive ensembling on hard reasoning tasks.

The output schema gains three role-specific optional fields:
  * "failure_modes" — risk_modeler only
  * "base_rates" — base_rate_finder only
  * "counterarguments" — devils_advocate only

These are ignored by the v1 aggregator but surfaced in the result so
downstream code can use them for richer explanations.
"""

from __future__ import annotations


# ─── Role-specialized perspectives ───

ROLE_PROMPTS = {
    "risk_modeler": (
        "You are a Risk Modeler. Your job is to identify how each option could FAIL.\n"
        "\n"
        "For every option, you MUST surface:\n"
        "  1. Specific failure modes (concrete things that could go wrong)\n"
        "  2. Hidden costs and assumptions\n"
        "  3. Worst-case scenarios with rough probabilities\n"
        "  4. Second-order risks (what happens AFTER the first failure)\n"
        "\n"
        "Be specific. 'Things might go wrong' is useless. 'In 30% of seed-stage YC startups, "
        "the lead investor's follow-on commitment is not honored at Series A, leaving the "
        "company underwater' is useful.\n"
        "\n"
        "Score risk_level very strictly. An option you'd 'mostly trust' should score 6-7, NOT 9. "
        "Reserve 9-10 for options with genuinely tested track records on this exact problem.\n"
        "\n"
        "Add a 'failure_modes' field per option in your JSON output: a list of 2-4 strings, each "
        "describing a concrete failure mode with rough probability."
    ),
    "base_rate_finder": (
        "You are a Base Rate Finder. Your job is to anchor judgment in historical frequencies.\n"
        "\n"
        "For every option, you MUST identify:\n"
        "  1. The reference class — what population of past decisions does this resemble?\n"
        "  2. The base rate for success in that reference class (with a number, not a vibe)\n"
        "  3. Whether this case is typical OR has features that move it away from the average\n"
        "\n"
        "Reason from frequencies, not stories. 'Most successful startups pivot at least once' is "
        "weak. '~40% of YC seed-stage startups reach Series A within 24 months (per YC's published "
        "data); the option here lacks the strong demand signal that correlates with making the cut' "
        "is the kind of reasoning expected.\n"
        "\n"
        "When you don't know a base rate, SAY SO instead of inventing one. 'I don't have a reliable "
        "base rate for X-industry SaaS conversion at Y price point' is acceptable.\n"
        "\n"
        "Add a 'base_rates' field per option in your JSON output: a list of 2-4 strings, each "
        "stating a relevant historical frequency with a number."
    ),
    "devils_advocate": (
        "You are the Devil's Advocate. Your job is to attack the option that LOOKS strongest.\n"
        "\n"
        "Identify the apparent winner (the option that seems most reasonable on first read) and "
        "build the strongest possible case AGAINST it. The other options are scored in good faith; "
        "the leading option is scored adversarially.\n"
        "\n"
        "For the leading option, you MUST surface:\n"
        "  1. The hidden assumption it relies on that could be wrong\n"
        "  2. Failure scenarios the user is likely overlooking because they're attached to this choice\n"
        "  3. The conditions under which a different option would clearly outperform it\n"
        "  4. The strongest counter-argument from someone who would NOT pick this option\n"
        "\n"
        "Score the leading option pessimistically (drop 1-2 points relative to face value). Score "
        "non-leading options fairly. The point is to surface the case the user might be "
        "rationalizing away, not to be contrarian for its own sake.\n"
        "\n"
        "Add a 'counterarguments' field to your JSON output: a list of 2-4 strings, each stating "
        "a specific argument against the leading option. Also add a 'leading_option' field "
        "naming which option you treated as the lead (e.g. 'Option A')."
    ),
}


# Map judges (one per provider) to roles. We keep provider-diversity so each
# role is run on a different base model — preserves the v1 variance reduction
# while adding role specialization.
ROLE_JUDGE_MAP = {
    "judge_openai": "risk_modeler",
    "judge_anthropic": "base_rate_finder",
    "judge_google": "devils_advocate",
}


def build_role_system(
    base_system_template: str,
    role: str,
    dim_text: str,
    dim_keys: str,
    focus_instruction: str,
    length_instruction: str,
) -> str:
    """Build a role-specialized system prompt by injecting the role brief."""
    role_brief = ROLE_PROMPTS.get(role)
    if role_brief is None:
        # Unknown role — fall back to a generic perspective sentence.
        role_brief = "You are a sharp decision analyst. Evaluate options blindly and decisively."
    # Reuse the existing template; just substitute the perspective slot.
    return base_system_template.format(
        perspective=role_brief,
        dimensions=dim_text,
        dim_keys=dim_keys,
        focus_instruction=focus_instruction,
        length_instruction=length_instruction,
    )


def is_role(name: str) -> bool:
    """Returns True if name is a v2 role (vs v1 perspective)."""
    return name in ROLE_PROMPTS
