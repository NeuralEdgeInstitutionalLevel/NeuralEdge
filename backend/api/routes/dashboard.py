"""
NeuralEdge AI - Dashboard Routes

GET /summary       -- equity, PnL, win rate, Sharpe, open positions count
GET /equity-curve  -- daily equity data points
GET /positions     -- current open positions
GET /trades        -- trade history (paginated)
GET /signals       -- recent signals (paginated)
"""
import logging
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from core.permissions import require_tier
from db.models.daily_snapshot import DailySnapshot
from db.models.signal import Signal
from db.models.trade import Trade
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class DashboardSummary(BaseModel):
    equity_usd: float
    total_pnl_usd: float
    total_pnl_pct: float
    today_pnl_usd: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    open_positions: int
    sharpe_30d: float | None
    max_drawdown_30d: float | None
    avg_trade_pnl: float
    best_trade_pnl: float
    worst_trade_pnl: float


class EquityPoint(BaseModel):
    date: date
    equity_usd: float
    daily_pnl_usd: float
    daily_pnl_pct: float


class EquityCurveResponse(BaseModel):
    points: list[EquityPoint]
    period: str
    total_points: int


class PositionResponse(BaseModel):
    id: int
    pair: str
    direction: str
    entry_price: float
    amount: float
    size_usd: float
    unrealized_pnl: float | None = None
    opened_at: datetime
    signal_confidence: float | None = None

    model_config = {"from_attributes": True}


class PositionListResponse(BaseModel):
    positions: list[PositionResponse]
    count: int


class TradeResponse(BaseModel):
    id: int
    pair: str
    direction: str
    entry_price: float
    exit_price: float | None
    amount: float
    size_usd: float
    pnl_usd: float | None
    pnl_pct: float | None
    fees_usd: float
    status: str
    exit_reason: str | None
    opened_at: datetime
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class PaginatedTradesResponse(BaseModel):
    trades: list[TradeResponse]
    page: int
    per_page: int
    total: int
    total_pages: int


class SignalResponse(BaseModel):
    id: int
    pair: str
    direction: str
    confidence: float
    magnitude: float | None
    entry_price: float
    sl_price: float | None
    tp_price: float | None
    regime: str | None
    alpha_prob: float | None
    lgbm_prob: float | None
    meta_prob: float | None
    uncertainty: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedSignalsResponse(BaseModel):
    signals: list[SignalResponse]
    page: int
    per_page: int
    total: int
    total_pages: int


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------
@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Dashboard overview metrics",
    dependencies=[Depends(require_tier("starter"))],
)
async def dashboard_summary(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated performance metrics for the dashboard."""
    # Total trades stats (closed trades only for PnL)
    closed_stats = await db.execute(
        select(
            func.count(Trade.id).label("total"),
            func.sum(case((Trade.pnl_usd > 0, 1), else_=0)).label("wins"),
            func.sum(case((Trade.pnl_usd <= 0, 1), else_=0)).label("losses"),
            func.coalesce(func.sum(Trade.pnl_usd), 0.0).label("total_pnl"),
            func.coalesce(func.avg(Trade.pnl_usd), 0.0).label("avg_pnl"),
            func.coalesce(func.max(Trade.pnl_usd), 0.0).label("best_pnl"),
            func.coalesce(func.min(Trade.pnl_usd), 0.0).label("worst_pnl"),
        ).where(
            Trade.user_id == user.id,
            Trade.status == "closed",
        )
    )
    stats = closed_stats.one()

    total_trades = stats.total or 0
    winning_trades = stats.wins or 0
    losing_trades = stats.losses or 0
    total_pnl = float(stats.total_pnl or 0)
    avg_pnl = float(stats.avg_pnl or 0)
    best_pnl = float(stats.best_pnl or 0)
    worst_pnl = float(stats.worst_pnl or 0)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    # Open positions count
    open_result = await db.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == user.id,
            Trade.status == "open",
        )
    )
    open_positions = open_result.scalar() or 0

    # Today's PnL
    today = date.today()
    today_result = await db.execute(
        select(func.coalesce(func.sum(Trade.pnl_usd), 0.0)).where(
            Trade.user_id == user.id,
            Trade.status == "closed",
            func.date(Trade.closed_at) == today,
        )
    )
    today_pnl = float(today_result.scalar() or 0)

    # Latest equity snapshot
    snap_result = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.user_id == user.id)
        .order_by(desc(DailySnapshot.date))
        .limit(1)
    )
    latest_snap = snap_result.scalar_one_or_none()

    equity_usd = latest_snap.equity_usd if latest_snap else 0.0
    sharpe_30d = latest_snap.sharpe_30d if latest_snap else None
    max_dd_30d = latest_snap.max_dd_30d if latest_snap else None

    # Total PnL percentage (relative to first recorded equity)
    first_snap = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.user_id == user.id)
        .order_by(DailySnapshot.date.asc())
        .limit(1)
    )
    first = first_snap.scalar_one_or_none()
    initial_equity = first.equity_usd if first and first.equity_usd > 0 else equity_usd
    total_pnl_pct = (
        ((equity_usd - initial_equity) / initial_equity * 100)
        if initial_equity > 0
        else 0.0
    )

    return DashboardSummary(
        equity_usd=equity_usd,
        total_pnl_usd=total_pnl,
        total_pnl_pct=round(total_pnl_pct, 2),
        today_pnl_usd=today_pnl,
        win_rate=round(win_rate, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        open_positions=open_positions,
        sharpe_30d=sharpe_30d,
        max_drawdown_30d=max_dd_30d,
        avg_trade_pnl=round(avg_pnl, 4),
        best_trade_pnl=round(best_pnl, 4),
        worst_trade_pnl=round(worst_pnl, 4),
    )


# ---------------------------------------------------------------------------
# GET /equity-curve
# ---------------------------------------------------------------------------
@router.get(
    "/equity-curve",
    response_model=EquityCurveResponse,
    summary="Daily equity curve data",
    dependencies=[Depends(require_tier("starter"))],
)
async def equity_curve(
    period: str = Query("30d", regex="^(7d|30d|90d|180d|1y|all)$"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return daily equity snapshots for charting."""
    # Calculate start date
    period_days = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "180d": 180,
        "1y": 365,
    }

    query = select(DailySnapshot).where(
        DailySnapshot.user_id == user.id
    )

    if period != "all":
        days = period_days.get(period, 30)
        start_date = date.today() - timedelta(days=days)
        query = query.where(DailySnapshot.date >= start_date)

    query = query.order_by(DailySnapshot.date.asc())

    result = await db.execute(query)
    snapshots = result.scalars().all()

    points = [
        EquityPoint(
            date=snap.date,
            equity_usd=snap.equity_usd,
            daily_pnl_usd=snap.daily_pnl_usd,
            daily_pnl_pct=snap.daily_pnl_pct,
        )
        for snap in snapshots
    ]

    return EquityCurveResponse(
        points=points,
        period=period,
        total_points=len(points),
    )


# ---------------------------------------------------------------------------
# GET /positions
# ---------------------------------------------------------------------------
@router.get(
    "/positions",
    response_model=PositionListResponse,
    summary="Current open positions",
    dependencies=[Depends(require_tier("starter"))],
)
async def open_positions(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all currently open positions for the user."""
    result = await db.execute(
        select(Trade)
        .where(Trade.user_id == user.id, Trade.status == "open")
        .order_by(Trade.opened_at.desc())
    )
    trades = result.scalars().all()

    positions = []
    for t in trades:
        # Fetch signal confidence if linked
        signal_conf = None
        if t.signal_id:
            sig_result = await db.execute(
                select(Signal.confidence).where(Signal.id == t.signal_id)
            )
            sig_row = sig_result.one_or_none()
            if sig_row:
                signal_conf = sig_row.confidence

        positions.append(
            PositionResponse(
                id=t.id,
                pair=t.pair,
                direction=t.direction,
                entry_price=t.entry_price,
                amount=t.amount,
                size_usd=t.size_usd,
                unrealized_pnl=None,  # Populated via WebSocket in real-time
                opened_at=t.opened_at,
                signal_confidence=signal_conf,
            )
        )

    return PositionListResponse(positions=positions, count=len(positions))


# ---------------------------------------------------------------------------
# GET /trades
# ---------------------------------------------------------------------------
@router.get(
    "/trades",
    response_model=PaginatedTradesResponse,
    summary="Paginated trade history",
    dependencies=[Depends(require_tier("starter"))],
)
async def trade_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    pair: str | None = Query(None, description="Filter by pair (e.g. BTC/USDT)"),
    status_filter: str | None = Query(
        None, alias="status", description="Filter by status (open, closed)"
    ),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated trade history with optional pair/status filters."""
    base_query = select(Trade).where(Trade.user_id == user.id)

    if pair:
        base_query = base_query.where(Trade.pair == pair.upper())
    if status_filter:
        base_query = base_query.where(Trade.status == status_filter)

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    result = await db.execute(
        base_query.order_by(Trade.opened_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    trades = result.scalars().all()

    trade_responses = [
        TradeResponse(
            id=t.id,
            pair=t.pair,
            direction=t.direction,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            amount=t.amount,
            size_usd=t.size_usd,
            pnl_usd=t.pnl_usd,
            pnl_pct=t.pnl_pct,
            fees_usd=t.fees_usd,
            status=t.status,
            exit_reason=t.exit_reason,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
        )
        for t in trades
    ]

    total_pages = max(1, math.ceil(total / per_page))

    return PaginatedTradesResponse(
        trades=trade_responses,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# GET /signals
# ---------------------------------------------------------------------------
@router.get(
    "/signals",
    response_model=PaginatedSignalsResponse,
    summary="Recent signals (paginated)",
    dependencies=[Depends(require_tier("starter"))],
)
async def recent_signals(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    pair: str | None = Query(None, description="Filter by pair"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated signal history.

    Pro users see all pairs they have access to.
    """
    base_query = select(Signal)

    if pair:
        base_query = base_query.where(Signal.pair == pair.upper())

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    result = await db.execute(
        base_query.order_by(Signal.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    signals = result.scalars().all()

    signal_responses = [
        SignalResponse(
            id=s.id,
            pair=s.pair,
            direction=s.direction,
            confidence=s.confidence,
            magnitude=s.magnitude,
            entry_price=s.entry_price,
            sl_price=s.sl_price,
            tp_price=s.tp_price,
            regime=s.regime,
            alpha_prob=s.alpha_prob,
            lgbm_prob=s.lgbm_prob,
            meta_prob=s.meta_prob,
            uncertainty=s.uncertainty,
            created_at=s.created_at,
        )
        for s in signals
    ]

    total_pages = max(1, math.ceil(total / per_page))

    return PaginatedSignalsResponse(
        signals=signal_responses,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
    )
