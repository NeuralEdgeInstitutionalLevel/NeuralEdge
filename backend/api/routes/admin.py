"""
NeuralEdge AI - Admin Routes

All endpoints require admin role.

GET /users        -- all users with status, tier, revenue
GET /revenue      -- MRR, total users, active users, churn
GET /system/health -- bot health, error counts
GET /audit-log    -- security audit trail (paginated)
"""
import logging
import math
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import case, desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from core.permissions import require_admin
from db.models.audit_log import AuditLog
from db.models.bot_instance import BotInstance
from db.models.subscription import Subscription
from db.models.trade import Trade
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pricing for revenue calculations
# ---------------------------------------------------------------------------
_TIER_MONTHLY_PRICE = {
    "free": 0,
    "starter": 199,
    "pro": 499,
    "elite": 999,
    "system": 0,  # Performance fee, not MRR
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class AdminUserItem(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    tier: str
    is_active: bool
    is_email_verified: bool
    total_trades: int
    total_pnl: float
    created_at: datetime
    last_login_at: datetime | None
    subscription_status: str | None


class AdminUsersResponse(BaseModel):
    users: list[AdminUserItem]
    total: int
    page: int
    per_page: int
    total_pages: int


class RevenueResponse(BaseModel):
    mrr: float  # Monthly recurring revenue
    arr: float  # Annual recurring revenue
    total_users: int
    active_users: int
    paying_users: int
    free_users: int
    tier_breakdown: dict[str, int]  # tier -> count
    churn_30d: float  # Percentage of users who cancelled in last 30 days
    new_users_30d: int
    avg_revenue_per_user: float


class SystemHealthResponse(BaseModel):
    total_bot_instances: int
    running_bots: int
    stopped_bots: int
    errored_bots: int
    stale_bots: int  # No heartbeat in >5 min
    total_errors_24h: int
    total_trades_24h: int
    total_signals_24h: int
    uptime_pct: float | None
    last_check: datetime


class AuditLogItem(BaseModel):
    id: int
    user_id: str | None
    user_email: str | None
    action: str
    ip_address: str | None
    user_agent: str | None
    details: dict | None
    created_at: datetime


class PaginatedAuditLogResponse(BaseModel):
    logs: list[AuditLogItem]
    page: int
    per_page: int
    total: int
    total_pages: int


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------
@router.get(
    "/users",
    response_model=AdminUsersResponse,
    summary="List all users (admin only)",
    dependencies=[Depends(require_admin)],
)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    tier: str | None = Query(None),
    active_only: bool = Query(False),
    search: str | None = Query(None, description="Search by email"),
    db: AsyncSession = Depends(get_db),
):
    """Return all users with their status, tier, and trade summary."""
    base_query = select(User)

    if tier:
        base_query = base_query.where(User.tier == tier)
    if active_only:
        base_query = base_query.where(User.is_active == True)
    if search:
        base_query = base_query.where(User.email.ilike(f"%{search}%"))

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    result = await db.execute(
        base_query.order_by(User.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    users = result.scalars().all()

    user_items = []
    for u in users:
        # Get trade stats
        trade_stats = await db.execute(
            select(
                func.count(Trade.id),
                func.coalesce(func.sum(Trade.pnl_usd), 0.0),
            ).where(
                Trade.user_id == u.id,
                Trade.status == "closed",
            )
        )
        trade_row = trade_stats.one()
        total_trades = trade_row[0] or 0
        total_pnl = float(trade_row[1] or 0)

        # Get latest subscription status
        sub_result = await db.execute(
            select(Subscription.status)
            .where(Subscription.user_id == u.id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        sub_row = sub_result.one_or_none()
        sub_status = sub_row[0] if sub_row else None

        user_items.append(
            AdminUserItem(
                id=str(u.id),
                email=u.email,
                display_name=u.display_name,
                role=u.role,
                tier=u.tier,
                is_active=u.is_active,
                is_email_verified=u.is_email_verified,
                total_trades=total_trades,
                total_pnl=round(total_pnl, 2),
                created_at=u.created_at,
                last_login_at=u.last_login_at,
                subscription_status=sub_status,
            )
        )

    total_pages = max(1, math.ceil(total / per_page))

    return AdminUsersResponse(
        users=user_items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# GET /revenue
# ---------------------------------------------------------------------------
@router.get(
    "/revenue",
    response_model=RevenueResponse,
    summary="Revenue metrics (admin only)",
    dependencies=[Depends(require_admin)],
)
async def revenue_metrics(
    db: AsyncSession = Depends(get_db),
):
    """Return MRR, user counts, tier breakdown, and churn metrics."""
    # Total users
    total_result = await db.execute(select(func.count(User.id)))
    total_users = total_result.scalar() or 0

    # Active users
    active_result = await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )
    active_users = active_result.scalar() or 0

    # Tier breakdown
    tier_result = await db.execute(
        select(User.tier, func.count(User.id))
        .where(User.is_active == True)
        .group_by(User.tier)
    )
    tier_breakdown = {row[0]: row[1] for row in tier_result.all()}

    # Calculate MRR from active subscriptions
    paying_users = 0
    mrr = 0.0
    for tier_name, count in tier_breakdown.items():
        price = _TIER_MONTHLY_PRICE.get(tier_name, 0)
        if price > 0:
            paying_users += count
            mrr += count * price

    free_users = total_users - paying_users

    # Churn: users who had active subscriptions 30 days ago but don't now
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    churned_result = await db.execute(
        select(func.count(distinct(Subscription.user_id))).where(
            Subscription.status == "inactive",
            Subscription.updated_at >= thirty_days_ago,
        )
    )
    churned_count = churned_result.scalar() or 0

    # Active subscriptions 30 days ago (approximate)
    active_subs_30d = await db.execute(
        select(func.count(distinct(Subscription.user_id))).where(
            Subscription.created_at <= thirty_days_ago,
        )
    )
    base_subs = active_subs_30d.scalar() or 1  # Avoid division by zero
    churn_rate = (churned_count / base_subs * 100) if base_subs > 0 else 0.0

    # New users in last 30 days
    new_users_result = await db.execute(
        select(func.count(User.id)).where(
            User.created_at >= thirty_days_ago,
        )
    )
    new_users_30d = new_users_result.scalar() or 0

    arpu = (mrr / paying_users) if paying_users > 0 else 0.0

    return RevenueResponse(
        mrr=mrr,
        arr=mrr * 12,
        total_users=total_users,
        active_users=active_users,
        paying_users=paying_users,
        free_users=free_users,
        tier_breakdown=tier_breakdown,
        churn_30d=round(churn_rate, 2),
        new_users_30d=new_users_30d,
        avg_revenue_per_user=round(arpu, 2),
    )


# ---------------------------------------------------------------------------
# GET /system/health
# ---------------------------------------------------------------------------
@router.get(
    "/system/health",
    response_model=SystemHealthResponse,
    summary="System health overview (admin only)",
    dependencies=[Depends(require_admin)],
)
async def system_health(
    db: AsyncSession = Depends(get_db),
):
    """Return bot instance health, error counts, and activity metrics."""
    now = datetime.now(timezone.utc)
    stale_threshold = now - timedelta(minutes=5)
    twenty_four_hours_ago = now - timedelta(hours=24)

    # Bot instance stats
    bot_stats = await db.execute(
        select(
            func.count(BotInstance.id).label("total"),
            func.sum(case((BotInstance.status == "running", 1), else_=0)).label("running"),
            func.sum(case((BotInstance.status == "stopped", 1), else_=0)).label("stopped"),
            func.sum(case((BotInstance.status == "error", 1), else_=0)).label("errored"),
        )
    )
    bs = bot_stats.one()
    total_bots = bs.total or 0
    running_bots = int(bs.running or 0)
    stopped_bots = int(bs.stopped or 0)
    errored_bots = int(bs.errored or 0)

    # Stale bots (running but no heartbeat in >5 min)
    stale_result = await db.execute(
        select(func.count(BotInstance.id)).where(
            BotInstance.status == "running",
            BotInstance.last_heartbeat < stale_threshold,
        )
    )
    stale_bots = stale_result.scalar() or 0

    # Error count in last 24h (from audit logs)
    error_result = await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.action.like("%.error%"),
            AuditLog.created_at >= twenty_four_hours_ago,
        )
    )
    total_errors_24h = error_result.scalar() or 0

    # Trades in last 24h
    trades_24h_result = await db.execute(
        select(func.count(Trade.id)).where(
            Trade.opened_at >= twenty_four_hours_ago,
        )
    )
    total_trades_24h = trades_24h_result.scalar() or 0

    # Signals in last 24h
    from db.models.signal import Signal

    signals_24h_result = await db.execute(
        select(func.count(Signal.id)).where(
            Signal.created_at >= twenty_four_hours_ago,
        )
    )
    total_signals_24h = signals_24h_result.scalar() or 0

    # Uptime percentage (running / total * 100)
    uptime_pct = None
    if total_bots > 0:
        uptime_pct = round((running_bots / total_bots) * 100, 1)

    return SystemHealthResponse(
        total_bot_instances=total_bots,
        running_bots=running_bots,
        stopped_bots=stopped_bots,
        errored_bots=errored_bots,
        stale_bots=stale_bots,
        total_errors_24h=total_errors_24h,
        total_trades_24h=total_trades_24h,
        total_signals_24h=total_signals_24h,
        uptime_pct=uptime_pct,
        last_check=now,
    )


# ---------------------------------------------------------------------------
# GET /audit-log
# ---------------------------------------------------------------------------
@router.get(
    "/audit-log",
    response_model=PaginatedAuditLogResponse,
    summary="Security audit trail (admin only)",
    dependencies=[Depends(require_admin)],
)
async def audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    action: str | None = Query(None, description="Filter by action type"),
    user_id: str | None = Query(None, description="Filter by user ID"),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated audit log entries for security review."""
    import uuid as uuid_mod

    base_query = select(AuditLog)

    if action:
        base_query = base_query.where(AuditLog.action.ilike(f"%{action}%"))

    if user_id:
        try:
            uid = uuid_mod.UUID(user_id)
            base_query = base_query.where(AuditLog.user_id == uid)
        except ValueError:
            pass  # Ignore invalid UUID, return empty results

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    result = await db.execute(
        base_query.order_by(desc(AuditLog.created_at))
        .offset(offset)
        .limit(per_page)
    )
    logs = result.scalars().all()

    # Batch-load user emails for display
    user_ids = {log.user_id for log in logs if log.user_id is not None}
    user_email_map: dict[str, str] = {}
    if user_ids:
        users_result = await db.execute(
            select(User.id, User.email).where(User.id.in_(user_ids))
        )
        user_email_map = {
            str(row.id): row.email for row in users_result.all()
        }

    log_items = [
        AuditLogItem(
            id=log.id,
            user_id=str(log.user_id) if log.user_id else None,
            user_email=user_email_map.get(str(log.user_id)) if log.user_id else None,
            action=log.action,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]

    total_pages = max(1, math.ceil(total / per_page))

    return PaginatedAuditLogResponse(
        logs=log_items,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )
