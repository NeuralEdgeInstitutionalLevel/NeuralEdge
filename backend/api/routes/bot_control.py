"""
NeuralEdge AI - Bot Control Routes

GET  /status    -- bot running/stopped, last heartbeat
GET  /settings  -- current bot configuration
POST /settings  -- update risk params (max_positions, pairs, sizing)
POST /start     -- activate bot
POST /stop      -- pause bot
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from config import settings
from core.permissions import require_tier
from db.models.audit_log import AuditLog
from db.models.bot_instance import BotInstance
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class BotStatusResponse(BaseModel):
    status: str  # running, stopped, error
    exchange: str
    last_heartbeat: datetime | None
    last_error: str | None
    error_count: int
    uptime_seconds: int | None = None

    model_config = {"from_attributes": True}


class BotSettingsResponse(BaseModel):
    exchange: str
    max_positions: int
    max_exposure_pct: float
    min_trade_usd: float
    max_trade_usd: float
    leverage: int
    pairs: list[str] | None
    disabled_pairs: list[str] | None
    daily_loss_limit_pct: float
    max_drawdown_pct: float
    sizing_mode: str
    fixed_size_usd: float | None
    pct_size: float | None

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    max_positions: int | None = Field(None, ge=1, le=24)
    max_exposure_pct: float | None = Field(None, ge=10.0, le=100.0)
    min_trade_usd: float | None = Field(None, ge=1.0, le=1000.0)
    max_trade_usd: float | None = Field(None, ge=5.0, le=50000.0)
    leverage: int | None = Field(None, ge=1, le=20)
    pairs: list[str] | None = None
    disabled_pairs: list[str] | None = None
    daily_loss_limit_pct: float | None = Field(None, ge=1.0, le=50.0)
    max_drawdown_pct: float | None = Field(None, ge=5.0, le=50.0)
    sizing_mode: str | None = Field(None, pattern="^(auto|fixed|percent)$")
    fixed_size_usd: float | None = Field(None, ge=1.0, le=50000.0)
    pct_size: float | None = Field(None, ge=0.1, le=100.0)


class BotActionResponse(BaseModel):
    success: bool
    status: str
    message: str


# ---------------------------------------------------------------------------
# Valid trading pairs
# ---------------------------------------------------------------------------
_VALID_PAIRS = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
    "AVAX/USDT", "DOGE/USDT", "DOT/USDT", "LINK/USDT", "LTC/USDT",
    "BCH/USDT", "ATOM/USDT", "NEAR/USDT", "ARB/USDT", "OP/USDT",
    "SUI/USDT", "APT/USDT", "INJ/USDT", "HBAR/USDT", "AAVE/USDT",
    "TIA/USDT", "PEPE/USDT", "FIL/USDT", "ETC/USDT",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_or_create_bot(
    db: AsyncSession, user: User
) -> BotInstance:
    """Get the user's bot instance, or create one with defaults."""
    result = await db.execute(
        select(BotInstance)
        .where(BotInstance.user_id == user.id)
        .order_by(BotInstance.created_at.desc())
        .limit(1)
    )
    bot = result.scalar_one_or_none()

    if bot is None:
        tier_limits = settings.TIER_LIMITS.get(
            user.tier, settings.TIER_LIMITS["free"]
        )
        bot = BotInstance(
            id=uuid.uuid4(),
            user_id=user.id,
            status="stopped",
            exchange="bitget",
            max_positions=min(tier_limits["max_positions"], 8),
            max_exposure_pct=80.0,
            min_trade_usd=5.0,
            max_trade_usd=100.0,
            leverage=2,
            pairs=None,
            disabled_pairs=None,
            daily_loss_limit_pct=5.0,
            max_drawdown_pct=15.0,
            sizing_mode="auto",
        )
        db.add(bot)
        await db.flush()

    return bot


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
@router.get(
    "/status",
    response_model=BotStatusResponse,
    summary="Bot running status and heartbeat",
    dependencies=[Depends(require_tier("starter"))],
)
async def bot_status(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the bot's current status, last heartbeat, and error info."""
    bot = await _get_or_create_bot(db, user)

    # Calculate uptime if running
    uptime = None
    if bot.status == "running" and bot.last_heartbeat:
        uptime = int(
            (datetime.now(timezone.utc) - bot.last_heartbeat).total_seconds()
        )
        # If heartbeat is older than 5 minutes, mark as stale
        if uptime > 300:
            bot.status = "error"
            bot.last_error = "Heartbeat timeout (>5min)"

    return BotStatusResponse(
        status=bot.status,
        exchange=bot.exchange,
        last_heartbeat=bot.last_heartbeat,
        last_error=bot.last_error,
        error_count=bot.error_count,
        uptime_seconds=uptime,
    )


# ---------------------------------------------------------------------------
# GET /settings
# ---------------------------------------------------------------------------
@router.get(
    "/settings",
    response_model=BotSettingsResponse,
    summary="Current bot configuration",
    dependencies=[Depends(require_tier("starter"))],
)
async def get_bot_settings(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the bot's current risk and trading parameters."""
    bot = await _get_or_create_bot(db, user)

    # Parse JSONB pairs fields into lists
    pairs_list = None
    if bot.pairs and isinstance(bot.pairs, dict):
        pairs_list = bot.pairs.get("active", None)
    elif bot.pairs and isinstance(bot.pairs, list):
        pairs_list = bot.pairs

    disabled_list = None
    if bot.disabled_pairs and isinstance(bot.disabled_pairs, dict):
        disabled_list = bot.disabled_pairs.get("disabled", None)
    elif bot.disabled_pairs and isinstance(bot.disabled_pairs, list):
        disabled_list = bot.disabled_pairs

    return BotSettingsResponse(
        exchange=bot.exchange,
        max_positions=bot.max_positions,
        max_exposure_pct=bot.max_exposure_pct,
        min_trade_usd=bot.min_trade_usd,
        max_trade_usd=bot.max_trade_usd,
        leverage=bot.leverage,
        pairs=pairs_list,
        disabled_pairs=disabled_list,
        daily_loss_limit_pct=bot.daily_loss_limit_pct,
        max_drawdown_pct=bot.max_drawdown_pct,
        sizing_mode=bot.sizing_mode,
        fixed_size_usd=bot.fixed_size_usd,
        pct_size=bot.pct_size,
    )


# ---------------------------------------------------------------------------
# POST /settings
# ---------------------------------------------------------------------------
@router.post(
    "/settings",
    response_model=BotSettingsResponse,
    summary="Update bot risk parameters",
    dependencies=[Depends(require_tier("starter"))],
)
async def update_bot_settings(
    body: UpdateSettingsRequest,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the bot's risk and trading parameters.

    Only provided fields are updated -- omitted fields remain unchanged.
    Validates against tier limits to prevent exceeding allowed positions/pairs.
    """
    bot = await _get_or_create_bot(db, user)
    tier_limits = settings.TIER_LIMITS.get(user.tier, settings.TIER_LIMITS["free"])
    changes = {}

    if body.max_positions is not None:
        max_allowed = tier_limits["max_positions"]
        if body.max_positions > max_allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Max positions for {user.tier} tier is {max_allowed}",
            )
        changes["max_positions"] = body.max_positions
        bot.max_positions = body.max_positions

    if body.max_exposure_pct is not None:
        changes["max_exposure_pct"] = body.max_exposure_pct
        bot.max_exposure_pct = body.max_exposure_pct

    if body.min_trade_usd is not None:
        changes["min_trade_usd"] = body.min_trade_usd
        bot.min_trade_usd = body.min_trade_usd

    if body.max_trade_usd is not None:
        if body.min_trade_usd and body.max_trade_usd < body.min_trade_usd:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="max_trade_usd must be >= min_trade_usd",
            )
        changes["max_trade_usd"] = body.max_trade_usd
        bot.max_trade_usd = body.max_trade_usd

    if body.leverage is not None:
        changes["leverage"] = body.leverage
        bot.leverage = body.leverage

    if body.pairs is not None:
        # Validate pairs
        max_pairs = tier_limits["max_pairs"]
        if len(body.pairs) > max_pairs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Max pairs for {user.tier} tier is {max_pairs}",
            )
        invalid = set(body.pairs) - _VALID_PAIRS
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid pairs: {', '.join(sorted(invalid))}",
            )
        bot.pairs = {"active": body.pairs}
        changes["pairs"] = body.pairs

    if body.disabled_pairs is not None:
        invalid = set(body.disabled_pairs) - _VALID_PAIRS
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid disabled pairs: {', '.join(sorted(invalid))}",
            )
        bot.disabled_pairs = {"disabled": body.disabled_pairs}
        changes["disabled_pairs"] = body.disabled_pairs

    if body.daily_loss_limit_pct is not None:
        changes["daily_loss_limit_pct"] = body.daily_loss_limit_pct
        bot.daily_loss_limit_pct = body.daily_loss_limit_pct

    if body.max_drawdown_pct is not None:
        changes["max_drawdown_pct"] = body.max_drawdown_pct
        bot.max_drawdown_pct = body.max_drawdown_pct

    if body.sizing_mode is not None:
        changes["sizing_mode"] = body.sizing_mode
        bot.sizing_mode = body.sizing_mode

    if body.fixed_size_usd is not None:
        changes["fixed_size_usd"] = body.fixed_size_usd
        bot.fixed_size_usd = body.fixed_size_usd

    if body.pct_size is not None:
        changes["pct_size"] = body.pct_size
        bot.pct_size = body.pct_size

    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update",
        )

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="bot.settings_updated",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        details=changes,
    )
    db.add(audit)

    logger.info("Bot settings updated: user=%s changes=%s", user.email, list(changes.keys()))

    # Return updated settings
    return await get_bot_settings(user=user, db=db)


# ---------------------------------------------------------------------------
# POST /start
# ---------------------------------------------------------------------------
@router.post(
    "/start",
    response_model=BotActionResponse,
    summary="Start the trading bot",
    dependencies=[Depends(require_tier("starter"))],
)
async def start_bot(
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate the bot for the authenticated user.

    Requires at least one valid API key for the bot's exchange.
    """
    bot = await _get_or_create_bot(db, user)

    if bot.status == "running":
        return BotActionResponse(
            success=True,
            status="running",
            message="Bot is already running",
        )

    # Verify user has valid API keys
    from db.models.api_key import APIKey

    key_result = await db.execute(
        select(APIKey).where(
            APIKey.user_id == user.id,
            APIKey.exchange == bot.exchange,
            APIKey.is_valid == True,
        ).limit(1)
    )
    has_key = key_result.scalar_one_or_none()

    if has_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No valid API key found for {bot.exchange}. Add one first.",
        )

    # Verify tier allows auto-execution
    tier_limits = settings.TIER_LIMITS.get(user.tier, settings.TIER_LIMITS["free"])
    if not tier_limits.get("auto_execute", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Auto-execution not available on {user.tier} tier. Upgrade to Pro or higher.",
        )

    bot.status = "running"
    bot.last_heartbeat = datetime.now(timezone.utc)
    bot.error_count = 0
    bot.last_error = None

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="bot.started",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        details={"exchange": bot.exchange},
    )
    db.add(audit)

    logger.info("Bot started: user=%s exchange=%s", user.email, bot.exchange)

    return BotActionResponse(
        success=True,
        status="running",
        message="Bot started successfully",
    )


# ---------------------------------------------------------------------------
# POST /stop
# ---------------------------------------------------------------------------
@router.post(
    "/stop",
    response_model=BotActionResponse,
    summary="Stop the trading bot",
    dependencies=[Depends(require_tier("starter"))],
)
async def stop_bot(
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause the bot. Open positions remain (not auto-closed)."""
    bot = await _get_or_create_bot(db, user)

    if bot.status == "stopped":
        return BotActionResponse(
            success=True,
            status="stopped",
            message="Bot is already stopped",
        )

    bot.status = "stopped"

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="bot.stopped",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        details={"exchange": bot.exchange},
    )
    db.add(audit)

    logger.info("Bot stopped: user=%s exchange=%s", user.email, bot.exchange)

    return BotActionResponse(
        success=True,
        status="stopped",
        message="Bot stopped successfully. Open positions are NOT auto-closed.",
    )
