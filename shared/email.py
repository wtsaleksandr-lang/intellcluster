"""
Email helpers. Uses SMTP if configured, otherwise prints to stdout.
Non-blocking — never raises on send failure (logs and continues).
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USERNAME") and os.environ.get("SMTP_PASSWORD"))


def send_email(to: str, subject: str, body: str, html: Optional[str] = None) -> bool:
    """Send an email. Returns True on success (or dev-mode print), False on failure."""
    sender = os.environ.get("SMTP_FROM", "noreply@intellcluster.com")

    if not _smtp_configured():
        # Dev mode: print
        print(f"[email DEV] TO: {to}")
        print(f"[email DEV] FROM: {sender}")
        print(f"[email DEV] SUBJECT: {subject}")
        print(f"[email DEV] BODY:\n{body}")
        return True

    try:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to
        msg["Subject"] = subject
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


def waitlist_confirmation(email: str, plan: str) -> bool:
    """Send waitlist signup confirmation."""
    subject = f"You're on the IntellCluster {plan.title()} waitlist"
    body = f"""Hi,

Thanks for joining the IntellCluster {plan.title()} waitlist.

We'll email you as soon as billing opens — typically we give at least 7 days' notice before the first charge.

In the meantime, you can use IntellCluster free at https://intellcluster.com:
- Phronesis — compare options and rank them with multi-analyst consensus
- Synthesis — deep research across 5 frontier AI models

Any questions? Just reply to this email.

— The IntellCluster team
"""
    return send_email(email, subject, body)
