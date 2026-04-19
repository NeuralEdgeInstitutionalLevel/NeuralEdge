"""
NeuralEdge AI - Whop API Client

Handles webhook signature verification and membership validation
for the Whop billing integration.

Docs: https://dev.whop.com/reference
"""
import hashlib
import hmac
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_WHOP_API_BASE = "https://api.whop.com/api/v5"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------
def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify the HMAC-SHA256 signature on an incoming Whop webhook.

    Args:
        payload:   Raw request body bytes.
        signature: Value of the ``X-Whop-Signature`` header.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not settings.WHOP_WEBHOOK_SECRET:
        logger.error("WHOP_WEBHOOK_SECRET is not configured -- rejecting webhook")
        return False

    expected = hmac.new(
        settings.WHOP_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Async HTTP helpers
# ---------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    """Standard authorization headers for Whop API requests."""
    return {
        "Authorization": f"Bearer {settings.WHOP_API_KEY}",
        "Accept": "application/json",
    }


async def get_membership(membership_id: str) -> dict[str, Any]:
    """Fetch a membership object from Whop by its ID.

    Returns the full membership dict.
    Raises ``httpx.HTTPStatusError`` on 4xx/5xx responses.
    """
    url = f"{_WHOP_API_BASE}/memberships/{membership_id}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url, headers=_headers())
        response.raise_for_status()
        return response.json()


async def validate_membership(membership_id: str) -> bool:
    """Check whether a Whop membership is currently active/trialing.

    Returns True if the membership exists and has an active-like status,
    False otherwise (expired, cancelled, or API error).
    """
    try:
        membership = await get_membership(membership_id)
        status_value = membership.get("status", "")
        # Whop statuses: active, trialing, past_due, canceled, expired
        return status_value in ("active", "trialing")
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Whop membership validation failed for %s: HTTP %d",
            membership_id,
            exc.response.status_code,
        )
        return False
    except Exception:
        logger.exception("Unexpected error validating Whop membership %s", membership_id)
        return False
