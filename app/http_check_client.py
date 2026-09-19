import logging
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10


async def check_http_endpoint(
    url: str,
    expected_status: int = 200,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """
    Perform an HTTP GET against `url` and report whether it's up.

    `transport` is a test-only hook (httpx.MockTransport) - production callers
    never pass it, so httpx uses its normal network transport.

    Returns: {
        'url': str,
        'is_up': bool,
        'status_code': int | None,
        'response_time_ms': float | None,
        'error_message': str | None,
    }
    """
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds, follow_redirects=True, transport=transport
        ) as client:
            response = await client.get(url)
        response_time_ms = (time.monotonic() - start) * 1000
        is_up = response.status_code == expected_status
        return {
            "url": url,
            "is_up": is_up,
            "status_code": response.status_code,
            "response_time_ms": round(response_time_ms, 1),
            "error_message": None if is_up else f"Unexpected status code {response.status_code}",
        }
    except Exception as e:
        response_time_ms = (time.monotonic() - start) * 1000
        logger.warning(f"HTTP check failed for {url}: {e}")
        return {
            "url": url,
            "is_up": False,
            "status_code": None,
            "response_time_ms": round(response_time_ms, 1),
            "error_message": str(e),
        }


def get_http_check_severity(is_up: bool) -> str:
    """Map an HTTP check result to incident severity."""
    return "low" if is_up else "critical"
