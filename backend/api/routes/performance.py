"""
NeuralEdge AI - Public Performance Routes

GET /track-record  -- master bot equity curve (public, no auth)
GET /stats         -- Sharpe, win rate, max DD, total return (public)

These endpoints are intentionally public (no authentication required)
to serve the landing page's track record section and build trust
with prospective subscribers.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from db.models.daily_snapshot import DailySnapshot
from db.models.trade import Trade
from db.models.user import User
from fastapi import Depends

logger = logging.getLogger(__name__)
router = APIRouter()

# The master bot's user email -- used to identify the system account
# whose performance is shown publicly.  Set via admin panel or env.
_MASTER_BOT_EMAIL = "system@neuraledge.ai"


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class EquityPoint(BaseModel):
    date: date
    equity_usd: float
    daily_pnl_pct: float


class TrackRecordResponse(BaseModel):
    equity_curve: list[EquityPoint]
    start_date: date | None
    end_date: date | None
    total_days: int
    data_available: bool


class PerformanceStats(BaseModel):
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    avg_trade_pnl_pct: float
    best_month_pct: float
    worst_month_pct: float
    profit_factor: float | None
    avg_win_pct: float
    avg_loss_pct: float
    longest_winning_streak: int
    longest_losing_streak: int
    calmar_ratio: float | None
    start_date: date | None
    end_date: date | None
    data_available: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_master_user(db: AsyncSession) -> User | None:
    """Get the master bot system user."""
    result = await db.execute(
        select(User).where(User.email == _MASTER_BOT_EMAIL)
    )
    return result.scalar_one_or_none()


def _compute_max_drawdown(equity_values: list[float]) -> float:
    """Compute maximum drawdown percentage from a list of equity values."""
    if len(equity_values) < 2:
        return 0.0

    peak = equity_values[0]
    max_dd = 0.0

    for eq in equity_values:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd

    return round(max_dd, 2)


def _compute_sharpe(daily_returns: list[float], annualize: bool = True) -> float | None:
    """Compute Sharpe ratio from daily returns (assuming risk-free rate = 0)."""
    if len(daily_returns) < 30:
        return None

    import statistics

    mean_ret = statistics.mean(daily_returns)
    std_ret = statistics.stdev(daily_returns)

    if std_ret == 0:
        return None

    sharpe = mean_ret / std_ret
    if annualize:
        sharpe *= (365 ** 0.5)  # Crypto trades 365 days

    return round(sharpe, 3)


def _compute_sortino(daily_returns: list[float]) -> float | None:
    """Compute Sortino ratio (penalizes only downside volatility)."""
    if len(daily_returns) < 30:
        return None

    import statistics

    mean_ret = statistics.mean(daily_returns)
    downside = [r for r in daily_returns if r < 0]

    if len(downside) < 2:
        return None

    downside_std = statistics.stdev(downside)
    if downside_std == 0:
        return None

    sortino = mean_ret / downside_std * (365 ** 0.5)
    return round(sortino, 3)


def _compute_streaks(trade_pnls: list[float]) -> tuple[int, int]:
    """Compute longest winning and losing streaks."""
    max_win = 0
    max_loss = 0
    current_win = 0
    current_loss = 0

    for pnl in trade_pnls:
        if pnl > 0:
            current_win += 1
            current_loss = 0
            max_win = max(max_win, current_win)
        elif pnl < 0:
            current_loss += 1
            current_win = 0
            max_loss = max(max_loss, current_loss)
        else:
            current_win = 0
            current_loss = 0

    return max_win, max_loss


# ---------------------------------------------------------------------------
# GET /track-record
# ---------------------------------------------------------------------------
@router.get(
    "/track-record",
    response_model=TrackRecordResponse,
    summary="Master bot equity curve (public)",
)
async def track_record(
    period: str = Query("all", regex="^(30d|90d|180d|1y|all)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return the master bot's daily equity curve for the landing page.

    This is public data -- no authentication required.
    """
    master = await _get_master_user(db)
    if master is None:
        return TrackRecordResponse(
            equity_curve=[],
            start_date=None,
            end_date=None,
            total_days=0,
            data_available=False,
        )

    query = select(DailySnapshot).where(
        DailySnapshot.user_id == master.id
    )

    period_days = {"30d": 30, "90d": 90, "180d": 180, "1y": 365}
    if period != "all":
        days = period_days.get(period, 365)
        start = date.today() - timedelta(days=days)
        query = query.where(DailySnapshot.date >= start)

    query = query.order_by(DailySnapshot.date.asc())

    result = await db.execute(query)
    snapshots = result.scalars().all()

    if not snapshots:
        return TrackRecordResponse(
            equity_curve=[],
            start_date=None,
            end_date=None,
            total_days=0,
            data_available=False,
        )

    points = [
        EquityPoint(
            date=s.date,
            equity_usd=s.equity_usd,
            daily_pnl_pct=s.daily_pnl_pct,
        )
        for s in snapshots
    ]

    return TrackRecordResponse(
        equity_curve=points,
        start_date=snapshots[0].date,
        end_date=snapshots[-1].date,
        total_days=len(snapshots),
        data_available=True,
    )


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------
@router.get(
    "/stats",
    response_model=PerformanceStats,
    summary="Master bot performance statistics (public)",
)
async def performance_stats(
    db: AsyncSession = Depends(get_db),
):
    """Return comprehensive performance statistics for the master bot.

    Public endpoint -- serves the landing page stats section.
    """
    master = await _get_master_user(db)
    if master is None:
        return PerformanceStats(
            total_return_pct=0, annualized_return_pct=0, sharpe_ratio=None,
            sortino_ratio=None, max_drawdown_pct=0, win_rate_pct=0,
            total_trades=0, avg_trade_pnl_pct=0, best_month_pct=0,
            worst_month_pct=0, profit_factor=None, avg_win_pct=0,
            avg_loss_pct=0, longest_winning_streak=0, longest_losing_streak=0,
            calmar_ratio=None, start_date=None, end_date=None,
            data_available=False,
        )

    # Fetch all equity snapshots
    snap_result = await db.execute(
        select(DailySnapshot)
        .where(DailySnapshot.user_id == master.id)
        .order_by(DailySnapshot.date.asc())
    )
    snapshots = snap_result.scalars().all()

    # Fetch all closed trades
    trade_result = await db.execute(
        select(Trade)
        .where(Trade.user_id == master.id, Trade.status == "closed")
        .order_by(Trade.closed_at.asc())
    )
    trades = trade_result.scalars().all()

    if not snapshots or not trades:
        return PerformanceStats(
            total_return_pct=0, annualized_return_pct=0, sharpe_ratio=None,
            sortino_ratio=None, max_drawdown_pct=0, win_rate_pct=0,
            total_trades=0, avg_trade_pnl_pct=0, best_month_pct=0,
            worst_month_pct=0, profit_factor=None, avg_win_pct=0,
            avg_loss_pct=0, longest_winning_streak=0, longest_losing_streak=0,
            calmar_ratio=None, start_date=None, end_date=None,
            data_available=False,
        )

    # Equity-based metrics
    equities = [s.equity_usd for s in snapshots]
    daily_returns = [s.daily_pnl_pct / 100 for s in snapshots]  # Fraction form
    start_date = snapshots[0].date
    end_date = snapshots[-1].date
    total_days = (end_date - start_date).days or 1

    initial_eq = equities[0] if equities[0] > 0 else 1.0
    final_eq = equities[-1]
    total_return_pct = ((final_eq - initial_eq) / initial_eq) * 100
    annualized = ((final_eq / initial_eq) ** (365 / total_days) - 1) * 100 if total_days > 0 else 0

    max_dd = _compute_max_drawdown(equities)
    sharpe = _compute_sharpe(daily_returns)
    sortino = _compute_sortino(daily_returns)

    # Trade-based metrics
    total_trades = len(trades)
    winning_trades = [t for t in trades if t.pnl_usd and t.pnl_usd > 0]
    losing_trades = [t for t in trades if t.pnl_usd and t.pnl_usd <= 0]

    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0

    trade_pnl_pcts = [t.pnl_pct for t in trades if t.pnl_pct is not None]
    avg_trade_pnl = sum(trade_pnl_pcts) / len(trade_pnl_pcts) if trade_pnl_pcts else 0

    win_pcts = [t.pnl_pct for t in winning_trades if t.pnl_pct is not None]
    loss_pcts = [t.pnl_pct for t in losing_trades if t.pnl_pct is not None]
    avg_win = sum(win_pcts) / len(win_pcts) if win_pcts else 0
    avg_loss = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0

    # Profit factor (gross wins / gross losses)
    gross_wins = sum(t.pnl_usd for t in winning_trades if t.pnl_usd)
    gross_losses = abs(sum(t.pnl_usd for t in losing_trades if t.pnl_usd))
    profit_factor = round(gross_wins / gross_losses, 3) if gross_losses > 0 else None

    # Monthly returns for best/worst month
    monthly_pnl: dict[str, float] = {}
    for s in snapshots:
        month_key = s.date.strftime("%Y-%m")
        monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + s.daily_pnl_pct

    best_month = max(monthly_pnl.values()) if monthly_pnl else 0
    worst_month = min(monthly_pnl.values()) if monthly_pnl else 0

    # Streaks
    trade_pnls = [t.pnl_usd or 0 for t in trades]
    longest_win, longest_loss = _compute_streaks(trade_pnls)

    # Calmar ratio (annualized return / max drawdown)
    calmar = None
    if max_dd > 0:
        calmar = round(annualized / max_dd, 3)

    return PerformanceStats(
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized, 2),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd,
        win_rate_pct=round(win_rate, 2),
        total_trades=total_trades,
        avg_trade_pnl_pct=round(avg_trade_pnl, 4),
        best_month_pct=round(best_month, 2),
        worst_month_pct=round(worst_month, 2),
        profit_factor=profit_factor,
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        longest_winning_streak=longest_win,
        longest_losing_streak=longest_loss,
        calmar_ratio=calmar,
        start_date=start_date,
        end_date=end_date,
        data_available=True,
    )
