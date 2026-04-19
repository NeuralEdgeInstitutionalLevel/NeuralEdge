"""
NeuralEdge AI - Signal Routes

GET /latest   -- latest signals (tier-gated by pair count)
GET /history  -- historical signals paginated
"""
import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from config import settings
from db.models.signal import Signal
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Tier-based pair access
# ---------------------------------------------------------------------------
# Starter gets top 3 by volume, Pro/Elite/System get all 24
_STARTER_PAIRS = {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

_ALL_PAIRS = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "DOGE/USDT", "DOT/USDT", "LINK/USDT", "LTC/USDT",
    "BCH/USDT", "ATOM/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
    "SUI/USDT", "APT/USDT", "INJ/USDT", "HBAR/USDT", "AAVE/USDT",
    "TIA/USDT", "PEPE/USDT", "FIL/USDT", "ETC/USDT",
}


def _get_allowed_pairs(user: User) -> set[str]:
    """Return the set of pairs a user is allowed to see signals for."""
    tier = user.tier
    if tier in ("pro", "elite", "system") or user.role == "admin":
        return _ALL_PAIRS
    elif tier == "starter":
        return _STARTER_PAIRS
    else:
        # Free tier: no signals
        return set()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class SignalItem(BaseModel):
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


class LatestSignalsResponse(BaseModel):
    signals: list[SignalItem]
    count: int
    allowed_pairs: int
    tier: str


class PaginatedSignalHistory(BaseModel):
    signals: list[SignalItem]
    page: int
    per_page: int
    total: int
    total_pages: int
    tier: str


# ---------------------------------------------------------------------------
# GET /latest
# ---------------------------------------------------------------------------
@router.get(
    "/latest",
    response_model=LatestSignalsResponse,
    summary="Latest signals (tier-gated)",
)
async def latest_signals(
    limit: int = Query(20, ge=1, le=100),
    pair: str | None = Query(None, description="Filter by pair"),
    direction: str | None = Query(None, pattern="^(LONG|SHORT)$"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent signals.

    Signal visibility is gated by subscription tier:
    - Free: no signals
    - Starter: BTC, ETH, SOL only (3 pairs)
    - Pro/Elite/System: all 24 pairs
    """
    allowed_pairs = _get_allowed_pairs(user)

    if not allowed_pairs:
        return LatestSignalsResponse(
            signals=[],
            count=0,
            allowed_pairs=0,
            tier=user.tier,
        )

    query = select(Signal).where(Signal.pair.in_(allowed_pairs))

    if pair:
        pair_upper = pair.upper()
        if pair_upper not in allowed_pairs:
            return LatestSignalsResponse(
                signals=[],
                count=0,
                allowed_pairs=len(allowed_pairs),
                tier=user.tier,
            )
        query = query.where(Signal.pair == pair_upper)

    if direction:
        query = query.where(Signal.direction == direction)

    query = query.order_by(desc(Signal.created_at)).limit(limit)

    result = await db.execute(query)
    signals = result.scalars().all()

    signal_items = [
        SignalItem(
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

    return LatestSignalsResponse(
        signals=signal_items,
        count=len(signal_items),
        allowed_pairs=len(allowed_pairs),
        tier=user.tier,
    )


# ---------------------------------------------------------------------------
# GET /history
# ---------------------------------------------------------------------------
@router.get(
    "/history",
    response_model=PaginatedSignalHistory,
    summary="Historical signals (paginated)",
)
async def signal_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    pair: str | None = Query(None, description="Filter by pair"),
    direction: str | None = Query(None, pattern="^(LONG|SHORT)$"),
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return paginated signal history with filters.

    Tier-gated: users only see signals for their allowed pairs.
    """
    allowed_pairs = _get_allowed_pairs(user)

    if not allowed_pairs:
        return PaginatedSignalHistory(
            signals=[],
            page=page,
            per_page=per_page,
            total=0,
            total_pages=0,
            tier=user.tier,
        )

    base_query = select(Signal).where(Signal.pair.in_(allowed_pairs))

    if pair:
        pair_upper = pair.upper()
        if pair_upper not in allowed_pairs:
            return PaginatedSignalHistory(
                signals=[],
                page=page,
                per_page=per_page,
                total=0,
                total_pages=0,
                tier=user.tier,
            )
        base_query = base_query.where(Signal.pair == pair_upper)

    if direction:
        base_query = base_query.where(Signal.direction == direction)

    if min_confidence is not None:
        base_query = base_query.where(Signal.confidence >= min_confidence)

    # Count total
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Fetch page
    offset = (page - 1) * per_page
    result = await db.execute(
        base_query.order_by(desc(Signal.created_at))
        .offset(offset)
        .limit(per_page)
    )
    signals = result.scalars().all()

    signal_items = [
        SignalItem(
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

    total_pages = max(1, math.ceil(total / per_page)) if total > 0 else 0

    return PaginatedSignalHistory(
        signals=signal_items,
        page=page,
        per_page=per_page,
        total=total,
        total_pages=total_pages,
        tier=user.tier,
    )
