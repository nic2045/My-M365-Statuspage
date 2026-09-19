import asyncio
import logging
import socket
import ssl
import subprocess
from datetime import UTC, datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _extract_hostname(input_str: str) -> str:
    """Extract hostname from a string that might be a URL or just a hostname."""
    if not input_str:
        return ""

    input_str = input_str.strip()
    if input_str.startswith(("http://", "https://")):
        parsed = urlparse(input_str)
        return parsed.hostname or parsed.netloc or input_str

    return input_str.split("/")[0].split(":")[0]


async def get_certificate_expiration(hostname: str) -> dict[str, object]:
    """
    Fetch TLS certificate from hostname and return detailed expiration info.
    Returns: {
        'hostname': str,
        'expires_at': datetime,
        'valid_from': datetime,
        'days_remaining': int,
        'status': 'ok' | 'warning_30' | 'warning_7' | 'expired',
        'common_name': str,
        'issuer': str,
        'serial_number': str,
    }
    """
    hostname = _extract_hostname(hostname)

    loop = asyncio.get_event_loop()
    try:
        def _get_cert() -> dict[str, object]:
            # Use openssl to fetch certificate info (most reliable method)
            cmd = f"echo '' | openssl s_client -servername {hostname} -connect {hostname}:443 -showcerts 2>/dev/null"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                raise ValueError(f"openssl failed: {result.stderr}")

            output = result.stdout
            cert = {
                "issuer": [[(("commonName", "Unknown"),)]],
                "subject": [[(("commonName", hostname),)]],
                "notAfter": "",
                "notBefore": "",
                "serialNumber": "Unknown",
            }

            # Parse only the first certificate (server cert), stop at first PEM block
            for line in output.split('\n'):
                if '-----BEGIN CERTIFICATE-----' in line:
                    break  # Stop after first certificate metadata

                line_stripped = line.strip()
                if line_stripped.startswith('i:'):
                    # Format: i:O = Anthropic, CN = Egress Gateway SDS Issuing CA (production)
                    issuer_str = line_stripped[2:].strip()
                    if 'CN = ' in issuer_str:
                        cn = issuer_str.split('CN = ')[-1].split(',')[0]
                        cert["issuer"] = [[(("commonName", cn),)]]
                elif line_stripped.startswith('s:'):
                    # Format: s:CN = pyur.com
                    subject_str = line_stripped[2:].strip()
                    if 'CN = ' in subject_str:
                        cn = subject_str.split('CN = ')[-1].split(',')[0]
                        cert["subject"] = [[(("commonName", cn),)]]
                elif line_stripped.startswith('v:'):
                    # Format: v:NotBefore: Sep 19 23:26:46 2026 GMT; NotAfter: Oct 19 23:27:46 2026 GMT
                    v_str = line_stripped[2:].strip()
                    if 'NotBefore:' in v_str and 'NotAfter:' in v_str:
                        before_part = v_str.split('NotBefore:')[1].split(';')[0].strip()
                        after_part = v_str.split('NotAfter:')[1].strip()
                        cert["notBefore"] = before_part
                        cert["notAfter"] = after_part

            if not cert["notAfter"]:
                raise ValueError("Could not extract certificate expiration date")

            return cert

        cert = await loop.run_in_executor(None, _get_cert)
        if not cert:
            raise ValueError("Failed to retrieve certificate")

        # Parse expiration date from cert
        expires_str = cert.get("notAfter", "")
        expires_at = datetime.strptime(expires_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)

        valid_from_str = cert.get("notBefore", "")
        valid_from = datetime.strptime(valid_from_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)

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

        # Extract issuer
        issuer_list = cert.get("issuer", [])
        issuer_dict = dict(x[0] for x in issuer_list) if issuer_list else {}
        issuer = issuer_dict.get("commonName", "Unknown")

        # Extract serial number
        serial_number = str(cert.get("serialNumber", "Unknown"))

        return {
            "hostname": hostname,
            "expires_at": expires_at,
            "valid_from": valid_from,
            "days_remaining": days_remaining,
            "status": status,
            "common_name": common_name,
            "issuer": issuer,
            "serial_number": serial_number,
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
