"""Transactional email sending (verification, password reset) over SMTP.

Works with any SMTP provider (Alibaba DirectMail, Gmail, SendGrid, ...).
If ``smtp.host`` is empty, emails are suppressed and logged instead — useful
for local development where no SMTP credentials are configured.
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from .config import CONFIG

log = logging.getLogger("drone-api.email")

SMTP = CONFIG.get("smtp", {})


async def send_email(to: str, subject: str, body: str) -> None:
    if not SMTP.get("host"):
        log.warning("SMTP not configured; email to %s suppressed (subject: %r)", to, subject)
        return

    msg = EmailMessage()
    msg["From"] = SMTP.get("from") or SMTP.get("username", "")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=SMTP["host"],
        port=SMTP.get("port", 587),
        username=SMTP.get("username") or None,
        password=SMTP.get("password") or None,
        start_tls=SMTP.get("start_tls", True),
    )


def _frontend_link(path: str, token: str) -> str:
    base = CONFIG.get("frontend_base_url", "").rstrip("/")
    return f"{base}{path}?token={token}"


async def send_verification_email(to: str, token: str) -> None:
    link = _frontend_link("/verify-email", token)
    await send_email(
        to,
        "Verify your Drone Navigation account",
        "Welcome aboard, pilot!\n\n"
        f"Confirm your email address by opening this link:\n\n{link}\n\n"
        "If you did not register, you can ignore this message.",
    )


async def send_password_reset_email(to: str, token: str) -> None:
    link = _frontend_link("/reset-password", token)
    await send_email(
        to,
        "Reset your Drone Navigation password",
        "We received a password reset request for your account.\n\n"
        f"Choose a new password by opening this link:\n\n{link}\n\n"
        "If you did not request this, you can ignore this message.",
    )
