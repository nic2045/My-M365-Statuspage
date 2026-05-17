"""Async notification dispatch: Email (SMTP) and MS Teams webhooks."""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_email(to: str, subject: str, html_body: str, text_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


async def send_email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send one email. Returns True on success, False on failure."""
    if not settings.SMTP_HOST:
        logger.debug("SMTP_HOST not configured — skipping email to %s", to)
        return False
    try:
        import aiosmtplib  # optional dependency

        msg = _build_email(to, subject, html_body, text_body)
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASS or None,
            start_tls=settings.SMTP_TLS,
        )
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


async def send_confirmation_email(email: str, confirm_url: str) -> bool:
    subject = "Statuspage – E-Mail-Adresse bestätigen"
    html = f"""
<p>Bitte bestätige deine E-Mail-Adresse, um Benachrichtigungen zu erhalten:</p>
<p><a href="{confirm_url}">{confirm_url}</a></p>
<p>Falls du dich nicht angemeldet hast, ignoriere diese E-Mail.</p>
"""
    text = f"Bitte bestätige deine E-Mail-Adresse:\n{confirm_url}\n"
    return await send_email(email, subject, html, text)


async def send_incident_notification(
    subscribers: list[str],
    subject: str,
    incident_title: str,
    service_name: str,
    description: str,
    status_url: str,
    unsubscribe_urls: dict[str, str],
) -> None:
    """Send incident notification to a list of confirmed subscriber emails."""
    for email in subscribers:
        unsub_url = unsubscribe_urls.get(email, "")
        html = f"""
<h2 style="margin:0 0 8px">M365 Dienststatus – {subject}</h2>
<p><strong>Dienst:</strong> {service_name}</p>
<p><strong>Meldung:</strong> {incident_title}</p>
{f'<p>{description}</p>' if description else ''}
<p><a href="{status_url}">Statusseite öffnen</a></p>
<hr style="margin:16px 0">
<p style="font-size:12px;color:#666">
  <a href="{unsub_url}">Abmelden</a>
</p>
"""
        text = (
            f"M365 Dienststatus – {subject}\n"
            f"Dienst: {service_name}\n"
            f"Meldung: {incident_title}\n"
            f"{description or ''}\n\n"
            f"Statusseite: {status_url}\n"
            f"Abmelden: {unsub_url}\n"
        )
        await send_email(email, f"[M365 Status] {subject}", html, text)


# ── MS Teams ─────────────────────────────────────────────────────────────────

async def send_teams_notification(
    incident_title: str,
    service_name: str,
    status: str,
    description: str,
    status_url: str,
) -> None:
    """Post an Adaptive Card to all configured Teams webhooks."""
    if not settings.teams_webhook_list:
        return

    status_colors = {
        "operational": "Good",
        "degraded": "Warning",
        "interrupted": "Attention",
    }
    color = status_colors.get(status, "Default")

    card_payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "M365 Dienststatus",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": color,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Dienst", "value": service_name},
                                {"title": "Meldung", "value": incident_title},
                            ],
                        },
                        *(
                            [{"type": "TextBlock", "text": description, "wrap": True}]
                            if description
                            else []
                        ),
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Statusseite öffnen",
                            "url": status_url,
                        }
                    ],
                },
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        for url in settings.teams_webhook_list:
            try:
                r = await client.post(url, json=card_payload)
                r.raise_for_status()
                logger.info("Teams notification sent to webhook")
            except Exception:
                logger.exception("Failed to post Teams notification to %s", url)
