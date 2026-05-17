"""Async notification dispatch: Email (SMTP / MS Graph) and MS Teams webhooks."""
from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.app_settings import EmailSettings, get_email_settings
from app.config import settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ── Email ─────────────────────────────────────────────────────────────────────

def _build_email(cfg: EmailSettings, to: str, subject: str, html_body: str, text_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_from or cfg.smtp_user or cfg.graph_from_address
    msg["To"] = to
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


async def _send_via_smtp(cfg: EmailSettings, to: str, subject: str, html_body: str, text_body: str) -> bool:
    if not cfg.smtp_host:
        return False
    try:
        import aiosmtplib

        msg = _build_email(cfg, to, subject, html_body, text_body)
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user or None,
            password=cfg.smtp_pass or None,
            start_tls=cfg.smtp_tls,
        )
        logger.info("Email (SMTP) sent to %s: %s", to, subject)
        return True
    except Exception:
        logger.exception("Failed to send SMTP email to %s", to)
        return False


async def _get_graph_token() -> str | None:
    """Acquire Graph token with client_credentials (Mail.Send permission)."""
    from app.app_settings import get_azure_settings  # noqa: PLC0415
    from app.database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        az = await get_azure_settings(db)
    if not az.is_configured:
        logger.error("Azure AD not configured – cannot acquire Graph token")
        return None
    try:
        import msal  # noqa: PLC0415

        msal_app = msal.ConfidentialClientApplication(
            az.client_id,
            authority=f"https://login.microsoftonline.com/{az.tenant_id}",
            client_credential=az.client_secret,
        )
        result = msal_app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            logger.error("MSAL token acquisition failed: %s", result.get("error_description"))
            return None
        return result["access_token"]
    except Exception:
        logger.exception("Failed to acquire Graph token")
        return None


async def _send_via_graph(cfg: EmailSettings, to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send email via Microsoft Graph /users/{from}/sendMail.

    Requires Mail.Send application permission on the Azure AD app and admin
    consent. The cfg.graph_from_address must be a real mailbox in the tenant.
    """
    if not cfg.graph_from_address:
        return False
    token = await _get_graph_token()
    if not token:
        return False
    url = f"https://graph.microsoft.com/v1.0/users/{cfg.graph_from_address}/sendMail"
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body or text_body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": False,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            if r.status_code in (200, 202):
                logger.info("Email (Graph) sent to %s: %s", to, subject)
                return True
            logger.error("Graph sendMail failed %s: %s", r.status_code, r.text[:200])
            return False
    except Exception:
        logger.exception("Failed to send Graph email to %s", to)
        return False


async def _load_cfg() -> EmailSettings:
    async with AsyncSessionLocal() as db:
        return await get_email_settings(db)


async def send_email(to: str, subject: str, html_body: str, text_body: str) -> bool:
    """Dispatch one email via the currently-configured method."""
    cfg = await _load_cfg()
    if cfg.auth_method == "none" or not cfg.is_configured:
        logger.debug("Email not configured (method=%s) — skipping send to %s", cfg.auth_method, to)
        return False
    if cfg.auth_method == "graph_oauth2":
        return await _send_via_graph(cfg, to, subject, html_body, text_body)
    return await _send_via_smtp(cfg, to, subject, html_body, text_body)


async def send_test_email(to: str) -> tuple[bool, str]:
    """Used by admin UI to validate the configured method. Returns (ok, message)."""
    cfg = await _load_cfg()
    if cfg.auth_method == "none":
        return False, "Versandmethode ist auf 'Deaktiviert' gesetzt."
    if not cfg.is_configured:
        return False, "Konfiguration unvollständig — bitte Pflichtfelder ausfüllen."
    subject = "M365 Statuspage – Test-E-Mail"
    html = "<p>Diese Testnachricht bestätigt, dass dein E-Mail-Versand funktioniert.</p>"
    text = "Diese Testnachricht bestätigt, dass dein E-Mail-Versand funktioniert.\n"
    ok = await send_email(to, subject, html, text)
    if ok:
        method = "Microsoft Graph (OAuth2)" if cfg.auth_method == "graph_oauth2" else "SMTP"
        return True, f"Test-E-Mail via {method} an {to} verschickt."
    return False, "Versand fehlgeschlagen – siehe Server-Log."


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
