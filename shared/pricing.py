"""
IntellCluster pricing configuration.
Centralized so frontend and backend stay in sync.

Credit economics:
- 1 credit = $0.10 retail
- Phronesis standard = 1 credit, deep = 3 credits
- Synthesis standard = 6 credits, expert = 15 credits
- Margins: ~5x on standard modes, ~3x on expert modes
"""

import os

# ─── Credit costs per action ───
CREDIT_COST = {
    ("phronesis", "quick"): 1,
    ("phronesis", "standard"): 1,
    ("phronesis", "deep"): 3,
    ("synthesis", "standard"): 6,
    ("synthesis", "expert"): 15,
}


# ─── Subscription plans ───
PLANS = {
    "free": {
        "id": "free",
        "name": "Free",
        "tagline": "Try it out",
        "monthly_price": 0,
        "annual_price": 0,
        "annual_discount_pct": 0,
        "credits_per_month": 20,    # 20 Phronesis OR ~3 Synthesis standard
        "features": [
            "20 credits / month",
            "Phronesis standard mode",
            "Synthesis standard mode (3 models)",
            "30-day history",
            "Basic shareable links",
        ],
        "limitations": [
            "No expert modes",
            "No permanent history",
            "No custom templates",
        ],
    },
    "starter": {
        "id": "starter",
        "name": "Starter",
        "tagline": "For solo power users",
        "monthly_price": 9,
        "annual_price": 84,          # $7/mo — save 22%
        "annual_discount_pct": 22,
        "credits_per_month": 150,    # 150 Phronesis OR 25 Synthesis standard
        "features": [
            "150 credits / month",
            "All Phronesis modes (incl. deep)",
            "Synthesis expert mode (5 models)",
            "Permanent history",
            "Custom templates",
            "PDF / CSV export",
        ],
        "limitations": [],
        "stripe_price_monthly_env": "STRIPE_PRICE_STARTER_MONTHLY",
        "stripe_price_annual_env": "STRIPE_PRICE_STARTER_ANNUAL",
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "tagline": "For serious decision-makers",
        "monthly_price": 19,
        "annual_price": 180,         # $15/mo — save 21%
        "annual_discount_pct": 21,
        "credits_per_month": 500,    # 500 Phronesis OR 83 Synthesis standard OR 33 Synthesis expert
        "features": [
            "500 credits / month",
            "Everything in Starter",
            "Outcome tracking + reminders",
            "Priority model access",
            "Team sharing (up to 3)",
            "API access (beta)",
            "Priority support",
        ],
        "highlighted": True,
        "stripe_price_monthly_env": "STRIPE_PRICE_PRO_MONTHLY",
        "stripe_price_annual_env": "STRIPE_PRICE_PRO_ANNUAL",
    },
}


# ─── Credit packs (no subscription) ───
CREDIT_PACKS = {
    "pack_5": {
        "id": "pack_5",
        "price_usd": 5,
        "credits": 30,
        "price_per_credit": 0.167,
        "tagline": "Try it",
        "stripe_price_env": "STRIPE_PRICE_CREDITS_5",
    },
    "pack_15": {
        "id": "pack_15",
        "price_usd": 15,
        "credits": 120,            # save 33%
        "price_per_credit": 0.125,
        "tagline": "Most popular",
        "highlighted": True,
        "stripe_price_env": "STRIPE_PRICE_CREDITS_15",
    },
    "pack_30": {
        "id": "pack_30",
        "price_usd": 30,
        "credits": 300,            # save 44%
        "price_per_credit": 0.100,
        "tagline": "Best value",
        "stripe_price_env": "STRIPE_PRICE_CREDITS_30",
    },
}


FREE_TRIAL_DAYS = 7  # Starter and Pro get 7-day trial


def get_stripe_price_id(env_var: str) -> str | None:
    """Return the Stripe price ID for a plan, or None if not configured."""
    val = os.environ.get(env_var, "").strip()
    return val if val else None


def stripe_configured() -> bool:
    """Check if Stripe keys are set."""
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PUBLISHABLE_KEY"))
