import asyncio
import logging
import ssl
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


async def get_certificate_expiration(hostname: str) -> dict[str, object]:
    """
    Fetch TLS certificate from hostname and return expiration info.
    Returns: {
        'hostname': str,
        'expires_at': datetime,
        'days_remaining': int,
        'status': 'ok' | 'warning_30' | 'warning_7' | 'expired',
        'common_name': str,
    }
    """
    loop = asyncio.get_event_loop()
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        def _get_cert() -> dict[str, object]:
            with ssl.create_connection((hostname, 443), timeout=5) as conn:
                sock = context.wrap_socket(conn, server_hostname=hostname)
                cert = sock.getpeercert()
                sock.close()
            return cert

        cert = await loop.run_in_executor(None, _get_cert)
        if not cert:
            raise ValueError("Failed to retrieve certificate")

        # Parse expiration date from cert
        expires_str = cert.get("notAfter", "")
        expires_at = datetime.strptime(expires_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
        now = datetime.now(UTC)
        days_remaining = (expires_at - now).days

        # Determine status
        if days_remaining < 0:
            status = "expired"
        elif days_remaining < 7:
            status = "warning_7"
        elif days_remaining < 30:
            status = "warning_30"
        else:
            status = "ok"

        # Extract common name
        subject = dict(x[0] for x in cert.get("subject", []))
        common_name = subject.get("commonName", hostname)

        return {
            "hostname": hostname,
            "expires_at": expires_at,
            "days_remaining": days_remaining,
            "status": status,
            "common_name": common_name,
        }
    except Exception as e:
        logger.error(f"Failed to fetch certificate for {hostname}: {e}")
        raise


def get_certificate_status_display(status: str) -> str:
    """Map certificate status to display string."""
    status_map = {
        "ok": "OK",
        "warning_30": "Warning (30 days)",
        "warning_7": "Warning (7 days)",
        "expired": "Expired",
    }
    return status_map.get(status, "Unknown")


def get_certificate_severity(status: str) -> str:
    """Map certificate status to incident severity."""
    severity_map = {
        "ok": "low",
        "warning_30": "low",
        "warning_7": "high",
        "expired": "critical",
    }
    return severity_map.get(status, "medium")
