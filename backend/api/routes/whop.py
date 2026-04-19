"""
NeuralEdge AI - Whop Webhook Routes

POST /webhook  -- receive and process Whop billing events

Events handled:
  - membership.went_valid   -> activate subscription, upgrade user tier
  - membership.went_invalid -> deactivate subscription, downgrade to free
  - membership.updated      -> update tier if plan changed
  - payment.succeeded       -> log payment, extend period
  - payment.failed          -> flag subscription, notify user
"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from config import settings
from core.whop_client import verify_webhook_signature
from db.models.audit_log import AuditLog
from db.models.subscription import Subscription
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_tier(plan_id: str | None) -> str:
    """Map a Whop plan_id to our internal tier name.

    Falls back to 'starter' if the plan is unrecognized.
    """
    if plan_id is None:
        return "starter"
    return settings.WHOP_PLAN_MAP.get(plan_id, "starter")


def _apply_tier_limits(user: User, tier: str) -> None:
    """Set the user's pair and position limits based on their tier."""
    limits = settings.TIER_LIMITS.get(tier, settings.TIER_LIMITS["free"])
    user.tier = tier
    user.max_pairs = limits["max_pairs"]
    user.max_positions = limits["max_positions"]


async def _find_or_create_user(
    db: "AsyncSession",
    whop_user_id: str,
    email: str | None = None,
) -> User:
    """Look up a user by whop_user_id, or create a placeholder if missing."""
    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user_id)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    # Fallback: try by email if provided
    if email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is not None:
            user.whop_user_id = whop_user_id
            return user

    # Create placeholder user (password login disabled until they register)
    import uuid

    from core.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email=email or f"whop_{whop_user_id}@placeholder.neuraledge.ai",
        password_hash=hash_password(uuid.uuid4().hex),  # Random unusable password
        whop_user_id=whop_user_id,
        role="user",
        tier="free",
        is_active=True,
        is_email_verified=False,
        max_pairs=0,
        max_positions=0,
    )
    db.add(user)
    await db.flush()
    logger.info("Created placeholder user for Whop user %s", whop_user_id)
    return user


async def _upsert_subscription(
    db: "AsyncSession",
    user: User,
    membership_id: str,
    plan_id: str | None,
    sub_status: str,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> Subscription:
    """Create or update a subscription record for the membership."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.whop_membership_id == membership_id
        )
    )
    sub = result.scalar_one_or_none()

    tier = _resolve_tier(plan_id)

    if sub is None:
        import uuid

        sub = Subscription(
            id=uuid.uuid4(),
            user_id=user.id,
            whop_membership_id=membership_id,
            whop_plan_id=plan_id,
            tier=tier,
            status=sub_status,
            current_period_start=period_start,
            current_period_end=period_end,
            metadata_=metadata,
        )
        db.add(sub)
    else:
        sub.tier = tier
        sub.status = sub_status
        sub.whop_plan_id = plan_id
        if period_start:
            sub.current_period_start = period_start
        if period_end:
            sub.current_period_end = period_end
        if metadata:
            sub.metadata_ = metadata

    await db.flush()
    return sub


# ---------------------------------------------------------------------------
# POST /webhook
# ---------------------------------------------------------------------------
@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Whop billing webhook receiver",
)
async def whop_webhook(request: Request):
    """Receive and process Whop webhook events.

    Verifies the HMAC-SHA256 signature before processing any event.
    Returns 200 on success (even for unknown events) to prevent retries.
    """
    # Read raw body for signature verification
    body = await request.body()
    signature = request.headers.get("X-Whop-Signature", "")

    if not verify_webhook_signature(body, signature):
        logger.warning("Whop webhook signature verification FAILED")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    # Parse JSON payload
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    event_type: str = payload.get("event", "")
    data: dict[str, Any] = payload.get("data", {})

    logger.info("Whop webhook received: %s", event_type)

    # Get a database session manually (we already consumed the body)
    from db.session import async_session_factory

    async with async_session_factory() as db:
        try:
            if event_type == "membership.went_valid":
                await _handle_membership_valid(db, data, payload)
            elif event_type == "membership.went_invalid":
                await _handle_membership_invalid(db, data, payload)
            elif event_type == "membership.updated":
                await _handle_membership_updated(db, data, payload)
            elif event_type == "payment.succeeded":
                await _handle_payment_succeeded(db, data, payload)
            elif event_type == "payment.failed":
                await _handle_payment_failed(db, data, payload)
            else:
                logger.info("Unhandled Whop event type: %s", event_type)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Error processing Whop webhook: %s", event_type)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing webhook",
            )

    return {"status": "ok", "event": event_type}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------
async def _handle_membership_valid(
    db: "AsyncSession", data: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Membership activated -- upgrade user to the appropriate tier."""
    membership_id = data.get("id", "")
    whop_user_id = data.get("user_id", "")
    plan_id = data.get("plan_id")
    email = data.get("email")

    if not membership_id or not whop_user_id:
        logger.warning("membership.went_valid missing id or user_id")
        return

    user = await _find_or_create_user(db, whop_user_id, email)
    tier = _resolve_tier(plan_id)

    sub = await _upsert_subscription(
        db, user, membership_id, plan_id, sub_status="active"
    )

    # Upgrade user tier (always take the highest active tier)
    _apply_tier_limits(user, tier)
    user.is_active = True

    # Audit
    audit = AuditLog(
        user_id=user.id,
        action="subscription.activated",
        details={
            "tier": tier,
            "membership_id": membership_id,
            "plan_id": plan_id,
        },
    )
    db.add(audit)

    logger.info(
        "Subscription activated: user=%s tier=%s membership=%s",
        user.email, tier, membership_id,
    )


async def _handle_membership_invalid(
    db: "AsyncSession", data: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Membership deactivated -- downgrade user to free tier."""
    membership_id = data.get("id", "")
    whop_user_id = data.get("user_id", "")

    if not membership_id or not whop_user_id:
        logger.warning("membership.went_invalid missing id or user_id")
        return

    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning(
            "membership.went_invalid for unknown Whop user %s", whop_user_id
        )
        return

    # Mark subscription inactive
    sub_result = await db.execute(
        select(Subscription).where(
            Subscription.whop_membership_id == membership_id
        )
    )
    sub = sub_result.scalar_one_or_none()
    if sub is not None:
        sub.status = "inactive"

    # Check if user has any OTHER active subscriptions
    other_active = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            Subscription.whop_membership_id != membership_id,
        )
    )
    remaining = other_active.scalar_one_or_none()

    if remaining is not None:
        # User has another active subscription -- keep that tier
        _apply_tier_limits(user, remaining.tier)
    else:
        # No active subscriptions -- downgrade to free
        _apply_tier_limits(user, "free")

    # Audit
    audit = AuditLog(
        user_id=user.id,
        action="subscription.deactivated",
        details={"membership_id": membership_id, "new_tier": user.tier},
    )
    db.add(audit)

    logger.info(
        "Subscription deactivated: user=%s new_tier=%s membership=%s",
        user.email, user.tier, membership_id,
    )


async def _handle_membership_updated(
    db: "AsyncSession", data: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Membership updated -- plan may have changed (upgrade/downgrade)."""
    membership_id = data.get("id", "")
    whop_user_id = data.get("user_id", "")
    plan_id = data.get("plan_id")

    if not membership_id or not whop_user_id:
        logger.warning("membership.updated missing id or user_id")
        return

    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning(
            "membership.updated for unknown Whop user %s", whop_user_id
        )
        return

    new_tier = _resolve_tier(plan_id)
    old_tier = user.tier

    sub = await _upsert_subscription(
        db, user, membership_id, plan_id, sub_status="active"
    )
    _apply_tier_limits(user, new_tier)

    # Audit
    audit = AuditLog(
        user_id=user.id,
        action="subscription.updated",
        details={
            "old_tier": old_tier,
            "new_tier": new_tier,
            "membership_id": membership_id,
            "plan_id": plan_id,
        },
    )
    db.add(audit)

    logger.info(
        "Subscription updated: user=%s %s -> %s membership=%s",
        user.email, old_tier, new_tier, membership_id,
    )


async def _handle_payment_succeeded(
    db: "AsyncSession", data: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Payment succeeded -- log it and update period dates if available."""
    membership_id = data.get("membership_id", "")
    whop_user_id = data.get("user_id", "")
    amount = data.get("amount")
    currency = data.get("currency", "USD")

    if not whop_user_id:
        logger.warning("payment.succeeded missing user_id")
        return

    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user_id)
    )
    user = result.scalar_one_or_none()

    user_id = user.id if user else None

    # Update subscription period if we have a membership_id
    if membership_id:
        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.whop_membership_id == membership_id
            )
        )
        sub = sub_result.scalar_one_or_none()
        if sub is not None:
            sub.current_period_start = datetime.now(timezone.utc)
            # Parse period_end from data if available
            period_end_str = data.get("current_period_end")
            if period_end_str:
                try:
                    sub.current_period_end = datetime.fromisoformat(
                        period_end_str.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

    # Audit
    audit = AuditLog(
        user_id=user_id,
        action="payment.succeeded",
        details={
            "membership_id": membership_id,
            "amount": amount,
            "currency": currency,
            "whop_payment_id": data.get("id"),
        },
    )
    db.add(audit)

    logger.info(
        "Payment succeeded: user=%s amount=%s %s",
        user.email if user else whop_user_id, amount, currency,
    )


async def _handle_payment_failed(
    db: "AsyncSession", data: dict[str, Any], payload: dict[str, Any]
) -> None:
    """Payment failed -- flag subscription and log for follow-up."""
    membership_id = data.get("membership_id", "")
    whop_user_id = data.get("user_id", "")
    reason = data.get("failure_reason", "unknown")

    if not whop_user_id:
        logger.warning("payment.failed missing user_id")
        return

    result = await db.execute(
        select(User).where(User.whop_user_id == whop_user_id)
    )
    user = result.scalar_one_or_none()
    user_id = user.id if user else None

    # Mark subscription as past_due
    if membership_id:
        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.whop_membership_id == membership_id
            )
        )
        sub = sub_result.scalar_one_or_none()
        if sub is not None:
            sub.status = "past_due"

    # Audit
    audit = AuditLog(
        user_id=user_id,
        action="payment.failed",
        details={
            "membership_id": membership_id,
            "reason": reason,
            "whop_payment_id": data.get("id"),
        },
    )
    db.add(audit)

    logger.warning(
        "Payment FAILED: user=%s reason=%s membership=%s",
        user.email if user else whop_user_id, reason, membership_id,
    )
