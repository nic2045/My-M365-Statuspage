from urllib.parse import urlparse


def normalize_url(input_str: str) -> tuple[str, str]:
    """
    Normalize URL/hostname input for checks.

    Accepts flexible formats: hostname, hostname/, http://hostname, https://hostname, etc.
    Returns a tuple: (normalized_url, hostname)
    - normalized_url: https://hostname (for HTTP checks)
    - hostname: just the hostname (for certificate checks)
    """
    if not input_str or not input_str.strip():
        return "", ""

    input_str = input_str.strip()

    if not input_str.startswith(("http://", "https://")):
        input_str = f"https://{input_str}"

    parsed = urlparse(input_str)
    hostname = parsed.hostname or parsed.netloc or input_str

    normalized_url = f"https://{hostname}"

    return normalized_url, hostname
