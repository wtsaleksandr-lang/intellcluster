"""
Email helpers.

Uses SMTP if SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD env vars are set, otherwise
prints the payload to stdout (dev mode). Never raises on send failure — logs
and returns False so the caller can decide whether to surface to the user.

All customer-facing templates share a single HTML shell (`_html_shell`) so
the branding stays consistent across welcome / receipt / outcome reminder
emails without duplicating the layout in each template.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


DEFAULT_FROM = "IntellCluster <hello@intellcluster.com>"
SUPPORT_ADDR = "support@intellcluster.com"
SITE_URL_DEFAULT = "https://intellcluster.com"


def _smtp_configured() -> bool:
    return bool(
        os.environ.get("SMTP_HOST")
        and os.environ.get("SMTP_USERNAME")
        and os.environ.get("SMTP_PASSWORD")
    )


def _site_url() -> str:
    return (os.environ.get("SITE_URL") or SITE_URL_DEFAULT).rstrip("/")


def send_email(to: str, subject: str, body: str, html: Optional[str] = None,
               reply_to: Optional[str] = None) -> bool:
    """Send an email. Returns True on success (or dev-mode print), False on failure."""
    sender = os.environ.get("SMTP_FROM", DEFAULT_FROM)

    if not _smtp_configured():
        print(f"[email DEV] TO: {to}")
        print(f"[email DEV] FROM: {sender}")
        print(f"[email DEV] SUBJECT: {subject}")
        if reply_to:
            print(f"[email DEV] REPLY-TO: {reply_to}")
        print(f"[email DEV] BODY:\n{body}")
        return True

    try:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")

        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        username = os.environ["SMTP_USERNAME"]
        password = os.environ["SMTP_PASSWORD"]

        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port) as server:
            server.starttls(context=ctx)
            server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[email ERROR] {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# HTML shell — single source of truth for branded email layout
# ══════════════════════════════════════════════════════════════════════

def _html_shell(preheader: str, inner_html: str, cta_label: str | None = None,
                cta_url: str | None = None) -> str:
    """Wraps inner HTML in a navy-branded email layout. Keep inline CSS —
    many email clients strip <style> blocks."""
    cta_block = ""
    if cta_label and cta_url:
        cta_block = f"""
        <tr><td align="left" style="padding:8px 32px 24px;">
          <a href="{cta_url}" style="display:inline-block;padding:12px 22px;background:#FF5600;color:#ffffff;
             text-decoration:none;border-radius:6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
             font-size:14px;font-weight:500;">{cta_label}</a>
        </td></tr>"""
    site = _site_url()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>IntellCluster</title>
</head>
<body style="margin:0;padding:0;background:#020917;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#020917;">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560" style="max-width:560px;background:#0a1122;border:1px solid rgba(255,255,255,0.10);border-radius:12px;">
      <tr><td style="padding:24px 32px 8px;border-bottom:1px solid rgba(255,255,255,0.05);">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td align="left" style="font-family:Georgia,serif;font-size:22px;color:#ffffff;letter-spacing:-0.4px;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#FF5600;vertical-align:middle;margin-right:8px;"></span>
              <a href="{site}" style="color:#ffffff;text-decoration:none;">IntellCluster</a>
            </td>
            <td align="right" style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:rgba(255,255,255,0.40);letter-spacing:1.2px;text-transform:uppercase;">
              FIELD NOTE
            </td>
          </tr>
        </table>
      </td></tr>
      <tr><td style="padding:28px 32px 8px;font-size:15px;line-height:1.65;color:#e6edf3;">
        {inner_html}
      </td></tr>{cta_block}
      <tr><td style="padding:16px 32px 24px;border-top:1px solid rgba(255,255,255,0.05);font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:rgba(255,255,255,0.40);letter-spacing:1.2px;text-transform:uppercase;">
        <a href="{site}" style="color:rgba(255,255,255,0.55);text-decoration:none;">intellcluster.com</a>
        &nbsp;&middot;&nbsp;
        <a href="{site}/privacy" style="color:rgba(255,255,255,0.55);text-decoration:none;">Privacy</a>
        &nbsp;&middot;&nbsp;
        <a href="mailto:{SUPPORT_ADDR}" style="color:rgba(255,255,255,0.55);text-decoration:none;">Support</a>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════
# Customer-facing templates
# ══════════════════════════════════════════════════════════════════════

def waitlist_confirmation(email: str, plan: str) -> bool:
    """Send waitlist signup confirmation."""
    site = _site_url()
    plan_title = plan.title()
    subject = f"You're on the IntellCluster {plan_title} waitlist"
    body = f"""Hi,

Thanks for joining the IntellCluster {plan_title} waitlist.

We'll email you as soon as billing opens for {plan_title} — typically with at
least 7 days' notice before the first charge. No surprises.

In the meantime, you can use the free tier at {site}:

  * Phronesis — rank decisions with a blind three-analyst jury
  * Synthesis — five models in parallel, merged into one research brief

Any questions? Just reply — a human answers.

— The IntellCluster team
"""
    inner = f"""
<p style="margin:0 0 14px;font-size:18px;color:#ffffff;">You're on the {plan_title} waitlist.</p>
<p style="margin:0 0 14px;">Thanks for signing up. We'll email you as soon as {plan_title} billing opens — with at least 7 days' notice before the first charge.</p>
<p style="margin:0 0 6px;">In the meantime, the free tier runs at <a href="{site}" style="color:#FF5600;">intellcluster.com</a>:</p>
<ul style="padding-left:20px;margin:4px 0 14px;color:rgba(255,255,255,0.78);">
  <li style="margin-bottom:4px;"><strong style="color:#ffffff;">Phronesis</strong> — rank decisions with a blind three-analyst jury</li>
  <li><strong style="color:#ffffff;">Synthesis</strong> — five models in parallel, merged into one research brief</li>
</ul>
<p style="margin:0 0 8px;">Any questions? Just reply to this email.</p>
<p style="margin:0 0 4px;color:rgba(255,255,255,0.55);font-size:13px;">— The IntellCluster team</p>
"""
    html = _html_shell(
        preheader=f"You're on the {plan_title} waitlist. We'll email before billing opens.",
        inner_html=inner,
        cta_label="Try the free tier",
        cta_url=site,
    )
    return send_email(email, subject, body, html=html)


def receipt(email: str, kind: str, amount_cents: int, currency: str,
            credits: int | None = None, plan_id: str | None = None,
            pack_id: str | None = None) -> bool:
    """Receipt after a successful Stripe payment.
    `kind` is 'subscription' or 'credit_pack'."""
    site = _site_url()
    amount_str = f"{currency.upper()} {amount_cents/100:.2f}"
    if kind == "subscription":
        plan_label = (plan_id or "subscription").replace("_", " ").title()
        subject = f"Receipt — IntellCluster {plan_label} activated"
        summary = f"Your {plan_label} subscription is now active. You'll see new limits the next time you open Phronesis or Synthesis."
        detail_row = f"<strong>Plan:</strong> {plan_label}"
    else:
        subject = f"Receipt — {credits or ''} IntellCluster credits added"
        pack_label = (pack_id or "credit pack").replace("_", " ").title()
        summary = f"Your top-up of <strong>{credits} credits</strong> has been added to your account. Credits from top-ups do not expire."
        detail_row = f"<strong>Pack:</strong> {pack_label}"

    body = f"""Hi,

Thanks for your purchase. Receipt below:

  Amount: {amount_str}
  {detail_row.replace('<strong>', '').replace('</strong>', '')}

You can manage your subscription or view past invoices anytime at
{site}/pricing — Stripe handles all billing on our behalf.

Any questions? Just reply to this email.

— The IntellCluster team
"""
    inner = f"""
<p style="margin:0 0 14px;font-size:18px;color:#ffffff;">Payment received.</p>
<p style="margin:0 0 14px;">{summary}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;margin:14px 0;">
  <tr><td style="padding:14px 16px;">
    <div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:rgba(255,255,255,0.40);letter-spacing:1.2px;text-transform:uppercase;margin-bottom:6px;">RECEIPT</div>
    <div style="margin-bottom:4px;"><span style="color:rgba(255,255,255,0.55);">Amount:</span> <strong style="color:#ffffff;">{amount_str}</strong></div>
    <div>{detail_row}</div>
  </td></tr>
</table>
<p style="margin:14px 0 6px;color:rgba(255,255,255,0.72);">Manage billing or download invoices anytime from the Stripe customer portal.</p>
<p style="margin:0 0 4px;color:rgba(255,255,255,0.55);font-size:13px;">— The IntellCluster team</p>
"""
    html = _html_shell(
        preheader=f"Receipt — {amount_str}",
        inner_html=inner,
        cta_label="Open IntellCluster",
        cta_url=site,
    )
    return send_email(email, subject, body, html=html)


def outcome_reminder(email: str, question: str, winner: str, run_id: str,
                     days_since: int) -> bool:
    """Ask a user how their Phronesis decision worked out. Sent ~14 days after."""
    site = _site_url()
    subject = f"How did it go? ({days_since} days since your decision)"
    body = f"""Hi,

{days_since} days ago you ran a decision on Phronesis:

  Question: {question[:200]}
  Our verdict: {winner[:120]}

If you've acted on it (or decided not to), a 30-second outcome rating helps us
calibrate the tool and helps you track your own decision quality over time.

Rate this outcome: {site}/phronesis/result/{run_id}

No reply needed if you'd rather skip. We only send these on substantive runs.

— The IntellCluster team
"""
    inner = f"""
<p style="margin:0 0 14px;font-size:18px;color:#ffffff;">How did this decision work out?</p>
<p style="margin:0 0 12px;color:rgba(255,255,255,0.78);">It's been {days_since} days since you ran this one:</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:rgba(255,86,0,0.08);border-left:3px solid #FF5600;border-radius:4px;margin:14px 0;">
  <tr><td style="padding:14px 16px;">
    <div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:#FF5600;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:6px;">YOUR QUESTION</div>
    <div style="color:rgba(255,255,255,0.85);margin-bottom:10px;">{question[:240]}</div>
    <div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:#FF5600;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:6px;">OUR VERDICT</div>
    <div style="color:#ffffff;font-weight:600;">{winner[:200]}</div>
  </td></tr>
</table>
<p style="margin:14px 0 10px;">A 30-second outcome rating helps us calibrate the tool — and helps you track your own decision quality over time.</p>
<p style="margin:0 0 4px;color:rgba(255,255,255,0.55);font-size:13px;">No reply needed if you'd rather skip.</p>
"""
    html = _html_shell(
        preheader=f"How did your Phronesis decision work out, {days_since} days later?",
        inner_html=inner,
        cta_label="Rate this outcome",
        cta_url=f"{site}/phronesis/result/{run_id}",
    )
    return send_email(email, subject, body, html=html)


def welcome(email: str, plan: str = "free") -> bool:
    """Welcome email after signup (works for free plan onboarding too)."""
    site = _site_url()
    subject = "Welcome to IntellCluster"
    body = f"""Hi,

Welcome to IntellCluster.

Two tools, one standard of rigor:

  * Phronesis ({site}/phronesis) — rank options with a blind three-analyst jury
  * Synthesis ({site}/synthesis) — five models in parallel, merged into one brief

If you're new, start with a decision you already made and see how the blind
jury scores it. The agreement signal is usually more useful than the winner.

Every Wednesday we publish a new field note on decision science and multi-model
AI: {site}/blog

Any questions? Just reply — a human answers.

— The IntellCluster team
"""
    inner = f"""
<p style="margin:0 0 14px;font-size:18px;color:#ffffff;">Welcome to IntellCluster.</p>
<p style="margin:0 0 14px;">Two tools, one standard of rigor:</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:14px 0;">
  <tr>
    <td style="padding:14px 16px;background:rgba(255,86,0,0.08);border-left:3px solid #FF5600;border-radius:4px;vertical-align:top;">
      <div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:#FF5600;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:4px;">PHRONESIS</div>
      <strong style="color:#ffffff;">Decision intelligence.</strong>
      <div style="color:rgba(255,255,255,0.72);margin-top:4px;font-size:13px;">Three blind AI analysts rank your options on weighted criteria.</div>
      <a href="{site}/phronesis" style="color:#FF5600;text-decoration:none;font-size:12px;font-family:'JetBrains Mono',monospace;letter-spacing:1px;text-transform:uppercase;">Open →</a>
    </td>
  </tr>
  <tr><td style="height:10px;"></td></tr>
  <tr>
    <td style="padding:14px 16px;background:rgba(56,189,248,0.08);border-left:3px solid #38bdf8;border-radius:4px;vertical-align:top;">
      <div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:#38bdf8;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:4px;">SYNTHESIS</div>
      <strong style="color:#ffffff;">Multi-model research.</strong>
      <div style="color:rgba(255,255,255,0.72);margin-top:4px;font-size:13px;">Five models run in parallel, merged into one research brief.</div>
      <a href="{site}/synthesis" style="color:#38bdf8;text-decoration:none;font-size:12px;font-family:'JetBrains Mono',monospace;letter-spacing:1px;text-transform:uppercase;">Open →</a>
    </td>
  </tr>
</table>
<p style="margin:14px 0 6px;">New here? Start with a decision you already made — compare how the blind jury scores it to what you remember deciding.</p>
<p style="margin:0 0 6px;">Every Wednesday we publish a new field note at <a href="{site}/blog" style="color:#FF5600;">/blog</a>.</p>
<p style="margin:0 0 4px;color:rgba(255,255,255,0.55);font-size:13px;">— The IntellCluster team</p>
"""
    html = _html_shell(
        preheader="Two AI tools. One standard of rigor. Start with a decision you already made.",
        inner_html=inner,
        cta_label="Open IntellCluster",
        cta_url=site,
    )
    return send_email(email, subject, body, html=html)


# ══════════════════════════════════════════════════════════════════════
# Auth — magic link
# ══════════════════════════════════════════════════════════════════════


def magic_link(email: str, link: str) -> bool:
    """Send a passwordless sign-in link. Valid for 15 minutes."""
    site = _site_url()
    subject = "Your IntellCluster sign-in link"
    body = f"""Hi,

Click the link below to sign in to IntellCluster. It's valid for 15 minutes
and can only be used once from the device that requested it.

  {link}

If you didn't request this, ignore the email — no account is created.

— The IntellCluster team
"""
    inner = f"""
<p style="margin:0 0 14px;font-size:18px;color:#ffffff;">Sign in to IntellCluster</p>
<p style="margin:0 0 14px;">Click the button below to sign in. The link is valid for <strong style="color:#ffffff;">15 minutes</strong>.</p>
<p style="margin:14px 0 10px;font-size:13px;color:rgba(255,255,255,0.55);">If you didn't request this, just ignore it — no account gets created.</p>
<p style="margin:0 0 4px;font-family:'JetBrains Mono',Consolas,monospace;font-size:11px;color:rgba(255,255,255,0.40);word-break:break-all;">Or paste this URL into your browser:<br><span style="color:rgba(255,255,255,0.55);">{link}</span></p>
"""
    html = _html_shell(
        preheader="Your 15-minute sign-in link for IntellCluster.",
        inner_html=inner,
        cta_label="Sign in →",
        cta_url=link,
    )
    return send_email(email, subject, body, html=html)


# ══════════════════════════════════════════════════════════════════════
# Admin notification templates
# ══════════════════════════════════════════════════════════════════════

def admin_contact_notification(name: str, email: str, reason: str, message: str) -> bool:
    """Notify the team when someone submits the contact form."""
    to = os.environ.get("ADMIN_INBOX") or SUPPORT_ADDR
    subject = f"[Contact] {reason}: {name}"
    body = f"""New contact form submission.

Name: {name}
Email: {email}
Reason: {reason}

Message:
{message}

— IntellCluster contact form
"""
    inner = f"""
<p style="margin:0 0 8px;font-size:16px;color:#ffffff;">New contact form submission.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;margin:12px 0;">
  <tr><td style="padding:14px 16px;">
    <div style="margin-bottom:6px;"><strong>Name:</strong> {name}</div>
    <div style="margin-bottom:6px;"><strong>Email:</strong> <a href="mailto:{email}" style="color:#FF5600;">{email}</a></div>
    <div style="margin-bottom:6px;"><strong>Reason:</strong> {reason}</div>
  </td></tr>
</table>
<div style="font-family:'JetBrains Mono',Consolas,monospace;font-size:10px;color:rgba(255,255,255,0.40);letter-spacing:1.2px;text-transform:uppercase;margin-bottom:6px;">MESSAGE</div>
<div style="white-space:pre-wrap;color:rgba(255,255,255,0.85);">{message}</div>
"""
    html = _html_shell(
        preheader=f"{name}: {message[:80]}",
        inner_html=inner,
    )
    return send_email(to, subject, body, html=html, reply_to=email)
