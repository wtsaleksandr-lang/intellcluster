"""
Stripe integration — creates Checkout Sessions for subscriptions and credit packs,
handles webhooks for successful payments.

Graceful degradation: if Stripe keys not set, functions return None/skip so the
UI can fall back to the waitlist.

Required env vars:
- STRIPE_SECRET_KEY
- STRIPE_PUBLISHABLE_KEY
- STRIPE_WEBHOOK_SECRET
- Price IDs per plan (see shared/pricing.py PLANS / CREDIT_PACKS env_ref fields)

SETUP STEPS (MANUAL):
1. Create Stripe account at https://stripe.com
2. In Stripe Dashboard → Products → Create three subscription products:
     - Starter: $9/mo ($84/yr)
     - Pro: $19/mo ($180/yr)
   For each, create a Price with the correct interval. Copy the price_... IDs.
3. Create three one-time Credit Pack products:
     - Pack 5 ($5, 30 credits)
     - Pack 15 ($15, 120 credits)
     - Pack 30 ($30, 300 credits)
   Copy the price_... IDs.
4. Paste all price IDs into .env under STRIPE_PRICE_* vars.
5. Set up webhook endpoint in Stripe Dashboard pointing to:
     https://intellcluster.com/api/stripe/webhook
   Enable events: checkout.session.completed, customer.subscription.updated,
                  customer.subscription.deleted, invoice.payment_succeeded
   Copy signing secret to STRIPE_WEBHOOK_SECRET.
"""

import os
from typing import Optional

from shared.pricing import PLANS, CREDIT_PACKS, get_stripe_price_id, stripe_configured

# Lazy import — stripe is optional during early development
_stripe = None


def _get_stripe():
    global _stripe
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
            _stripe = stripe
        except ImportError:
            return None
    return _stripe


def create_subscription_checkout(
    plan_id: str,
    billing: str,
    customer_email: Optional[str],
    success_url: str,
    cancel_url: str,
) -> Optional[str]:
    """Create a Stripe Checkout Session for a subscription plan.
    Returns checkout URL, or None if not configured.
    """
    if not stripe_configured():
        return None

    plan = PLANS.get(plan_id)
    if not plan or plan["id"] == "free":
        return None

    env_var = plan.get("stripe_price_monthly_env") if billing == "monthly" else plan.get("stripe_price_annual_env")
    price_id = get_stripe_price_id(env_var) if env_var else None
    if not price_id:
        return None

    stripe = _get_stripe()
    if not stripe:
        return None

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            subscription_data={"trial_period_days": 7},
            allow_promotion_codes=True,
        )
        return session.url
    except Exception as e:
        print(f"[stripe] checkout error: {e}")
        return None


def create_credit_pack_checkout(
    pack_id: str,
    customer_email: Optional[str],
    success_url: str,
    cancel_url: str,
) -> Optional[str]:
    """Create a Stripe Checkout Session for a one-time credit pack."""
    if not stripe_configured():
        return None

    pack = CREDIT_PACKS.get(pack_id)
    if not pack:
        return None

    env_var = pack.get("stripe_price_env")
    price_id = get_stripe_price_id(env_var) if env_var else None
    if not price_id:
        return None

    stripe = _get_stripe()
    if not stripe:
        return None

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
            metadata={"pack_id": pack_id, "credits": pack["credits"]},
            allow_promotion_codes=True,
        )
        return session.url
    except Exception as e:
        print(f"[stripe] checkout error: {e}")
        return None


def verify_webhook_signature(payload: bytes, sig_header: str) -> Optional[dict]:
    """Verify and parse a Stripe webhook. Returns event dict or None if invalid."""
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return None
    stripe = _get_stripe()
    if not stripe:
        return None
    try:
        return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        print(f"[stripe webhook] invalid: {e}")
        return None


def handle_webhook_event(event: dict) -> None:
    """Process a validated webhook event.

    Idempotent by design — `record_purchase` dedupes on Stripe event.id so
    webhook retries can't double-credit. Sends a branded receipt email once
    per unique event.
    """
    from shared.analytics import log_event
    from shared.tracking.purchases import record_purchase
    from shared.email import receipt as _send_receipt

    event_id = event.get("id", "")
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        mode = data.get("mode")
        email = (data.get("customer_details") or {}).get("email") or data.get("customer_email")
        amount = int(data.get("amount_total") or 0)
        currency = data.get("currency") or "usd"
        metadata = data.get("metadata") or {}

        if mode == "subscription":
            plan_id = metadata.get("plan_id") or metadata.get("plan")
            log_event("stripe_subscription_started", {
                "email": email,
                "subscription_id": data.get("subscription"),
                "customer": data.get("customer"),
                "plan_id": plan_id,
            })
            entry = record_purchase(
                event_id=event_id,
                email=email,
                kind="subscription",
                amount=amount,
                currency=currency,
                plan_id=plan_id,
                stripe_customer=data.get("customer"),
                stripe_subscription=data.get("subscription"),
            )
            if entry and email:
                try:
                    _send_receipt(email, "subscription", amount, currency, plan_id=plan_id)
                except Exception as e:
                    print(f"[stripe] receipt email failed: {e}")

        elif mode == "payment":
            credits = int(metadata.get("credits", 0) or 0)
            pack_id = metadata.get("pack_id")
            log_event("stripe_credits_purchased", {
                "email": email,
                "credits": credits,
                "pack_id": pack_id,
            })
            entry = record_purchase(
                event_id=event_id,
                email=email,
                kind="credit_pack",
                amount=amount,
                currency=currency,
                credits=credits,
                pack_id=pack_id,
                stripe_customer=data.get("customer"),
            )
            if entry and email:
                try:
                    _send_receipt(email, "credit_pack", amount, currency, credits=credits, pack_id=pack_id)
                except Exception as e:
                    print(f"[stripe] receipt email failed: {e}")

    elif event_type == "customer.subscription.updated":
        log_event("stripe_subscription_updated", {"subscription_id": data.get("id")})

    elif event_type == "customer.subscription.deleted":
        log_event("stripe_subscription_cancelled", {"subscription_id": data.get("id")})

    elif event_type == "invoice.payment_succeeded":
        log_event("stripe_invoice_paid", {"amount": data.get("amount_paid"), "customer": data.get("customer")})
