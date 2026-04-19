"""
NeuralEdge AI - Subscription Routes

GET /status  -- current subscription details for authenticated user
GET /tiers   -- available tiers and their features/limits
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from config import settings
from db.models.subscription import Subscription
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class SubscriptionDetail(BaseModel):
    id: str
    tier: str
    status: str
    whop_plan_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionStatusResponse(BaseModel):
    user_tier: str
    is_active: bool
    max_pairs: int
    max_positions: int
    auto_execute: bool
    dashboard_access: bool
    subscriptions: list[SubscriptionDetail]


class TierInfo(BaseModel):
    name: str
    display_name: str
    max_pairs: int
    max_positions: int
    auto_execute: bool
    dashboard: bool
    price_monthly: int | None
    features: list[str]


class TiersResponse(BaseModel):
    tiers: list[TierInfo]


# ---------------------------------------------------------------------------
# Tier metadata (augments TIER_LIMITS with display data)
# ---------------------------------------------------------------------------
_TIER_DISPLAY = {
    "free": {
        "display_name": "Free",
        "price_monthly": 0,
        "features": [
            "View public track record",
            "Basic signal notifications",
        ],
    },
    "starter": {
        "display_name": "Starter",
        "price_monthly": 199,
        "features": [
            "3 trading pairs",
            "Signal-only mode (manual execution)",
            "Telegram signal alerts",
            "Basic performance stats",
            "Community Discord access",
        ],
    },
    "pro": {
        "display_name": "Pro",
        "price_monthly": 499,
        "features": [
            "All 24 trading pairs",
            "Auto-execution via API keys",
            "Full dashboard with equity curve",
            "Advanced risk controls",
            "Telegram + Discord alerts",
            "Priority support",
        ],
    },
    "elite": {
        "display_name": "Elite",
        "price_monthly": 999,
        "features": [
            "All 24 trading pairs",
            "Auto-execution with 12 max positions",
            "Full dashboard + real-time WebSocket",
            "Custom risk parameters",
            "Direct developer support",
            "Early access to new features",
            "Funded account program access",
        ],
    },
    "system": {
        "display_name": "Managed",
        "price_monthly": None,  # 20% performance fee
        "features": [
            "Fully managed trading",
            "24 pairs, 24 max positions",
            "Dedicated bot instance",
            "Custom strategy tuning",
            "Monthly performance reports",
            "20% performance fee (no fixed cost)",
        ],
    },
}


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
@router.get(
    "/status",
    response_model=SubscriptionStatusResponse,
    summary="Get current subscription status",
)
async def subscription_status(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's subscription details and tier limits."""
    # Fetch all subscriptions for this user (ordered by most recent)
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
    )
    subscriptions = result.scalars().all()

    tier_limits = settings.TIER_LIMITS.get(
        user.tier, settings.TIER_LIMITS["free"]
    )

    sub_details = [
        SubscriptionDetail(
            id=str(sub.id),
            tier=sub.tier,
            status=sub.status,
            whop_plan_id=sub.whop_plan_id,
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            cancel_at_period_end=sub.cancel_at_period_end,
            created_at=sub.created_at,
        )
        for sub in subscriptions
    ]

    return SubscriptionStatusResponse(
        user_tier=user.tier,
        is_active=user.is_active,
        max_pairs=user.max_pairs,
        max_positions=user.max_positions,
        auto_execute=tier_limits.get("auto_execute", False),
        dashboard_access=tier_limits.get("dashboard", False),
        subscriptions=sub_details,
    )


# ---------------------------------------------------------------------------
# GET /tiers
# ---------------------------------------------------------------------------
@router.get(
    "/tiers",
    response_model=TiersResponse,
    summary="List available subscription tiers",
)
async def list_tiers():
    """Return all available tiers with their limits and features.

    This endpoint is public (no auth required) for the pricing page.
    """
    tiers = []
    for tier_name, limits in settings.TIER_LIMITS.items():
        display = _TIER_DISPLAY.get(tier_name, {})
        tiers.append(
            TierInfo(
                name=tier_name,
                display_name=display.get("display_name", tier_name.title()),
                max_pairs=limits["max_pairs"],
                max_positions=limits["max_positions"],
                auto_execute=limits["auto_execute"],
                dashboard=limits["dashboard"],
                price_monthly=display.get("price_monthly"),
                features=display.get("features", []),
            )
        )

    return TiersResponse(tiers=tiers)
