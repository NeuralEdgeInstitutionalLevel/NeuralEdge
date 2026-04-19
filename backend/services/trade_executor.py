"""
Multi-user trade execution engine.
Signal Fan-Out: ONE central bot generates signals -> this service executes per user.
"""
import logging
from uuid import UUID
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.encryption import decrypt
from db.models.user import User
from db.models.api_key import APIKey
from db.models.bot_instance import BotInstance
from db.models.trade import Trade
from db.models.signal import Signal
from config import settings

logger = logging.getLogger("neuraledge.trade_executor")


class TradeExecutor:
    """Executes trades for multiple users based on a signal."""

    async def fan_out_signal(self, signal_id: int, db: AsyncSession):
        """
        For a given signal, find all eligible users and dispatch
        trade execution tasks via Celery.
        """
        # Fetch the signal
        signal = await db.get(Signal, signal_id)
        if not signal:
            logger.error(f"Signal {signal_id} not found")
            return

        # Find all eligible users
        stmt = (
            select(User, BotInstance)
            .join(BotInstance, User.id == BotInstance.user_id)
            .where(
                User.is_active == True,
                User.tier.in_(["pro", "elite", "system"]),
                BotInstance.status == "running",
            )
        )
        result = await db.execute(stmt)
        eligible = result.all()

        logger.info(f"Signal {signal_id} ({signal.pair} {signal.direction}) -> "
                     f"{len(eligible)} eligible users")

        for user, bot_instance in eligible:
            # Check if pair is allowed for this user
            if bot_instance.pairs and signal.pair not in bot_instance.pairs:
                continue
            if signal.pair in (bot_instance.disabled_pairs or []):
                continue

            # Dispatch Celery task
            from workers.trade_worker import execute_trade_for_user
            execute_trade_for_user.delay(
                user_id=str(user.id),
                signal_id=signal_id,
                pair=signal.pair,
                direction=signal.direction,
                entry_price=signal.entry_price,
                sl_price=signal.sl_price,
                confidence=signal.confidence,
            )

    async def execute_for_user(
        self,
        user_id: UUID,
        signal_id: int,
        pair: str,
        direction: str,
        entry_price: float,
        sl_price: Optional[float],
        confidence: float,
        db: AsyncSession,
    ) -> Optional[Trade]:
        """Execute a single trade for a specific user."""
        # Fetch user's API keys
        stmt = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.exchange == "bitget",
            APIKey.is_valid == True,
        )
        result = await db.execute(stmt)
        api_key_record = result.scalar_one_or_none()

        if not api_key_record:
            logger.warning(f"User {user_id}: no valid API keys")
            return None

        # Fetch bot instance for risk params
        stmt = select(BotInstance).where(BotInstance.user_id == user_id)
        result = await db.execute(stmt)
        bot_instance = result.scalar_one_or_none()

        if not bot_instance:
            logger.warning(f"User {user_id}: no bot instance")
            return None

        # Decrypt API keys (in memory only)
        try:
            api_key = decrypt(api_key_record.api_key_enc, api_key_record.nonce)
            api_secret = decrypt(api_key_record.api_secret_enc, api_key_record.nonce)
            passphrase = None
            if api_key_record.passphrase_enc:
                passphrase = decrypt(api_key_record.passphrase_enc, api_key_record.nonce)
        except Exception as e:
            logger.error(f"User {user_id}: failed to decrypt API keys: {e}")
            return None

        # Create exchange instance with user's keys
        try:
            import ccxt.async_support as ccxt_async
            exchange = ccxt_async.bitget({
                "apiKey": api_key,
                "secret": api_secret,
                "password": passphrase,
                "options": {"defaultType": "swap"},
            })

            # Fetch balance to determine position size
            balance = await exchange.fetch_balance()
            available_usd = float(balance.get("USDT", {}).get("free", 0))

            if available_usd < bot_instance.min_trade_usd:
                logger.info(f"User {user_id}: insufficient balance ${available_usd:.2f}")
                await exchange.close()
                return None

            # Calculate position size based on user's settings
            if bot_instance.sizing_mode == "fixed_usd":
                size_usd = min(bot_instance.fixed_size_usd, available_usd * bot_instance.max_exposure_pct)
            elif bot_instance.sizing_mode == "pct_balance":
                size_usd = available_usd * bot_instance.pct_size
            else:  # dynamic
                size_usd = available_usd * bot_instance.pct_size * confidence

            size_usd = max(bot_instance.min_trade_usd, min(size_usd, bot_instance.max_trade_usd))

            # Calculate amount in base currency
            amount = size_usd * bot_instance.leverage / entry_price

            # Place order
            side = "buy" if direction == "long" else "sell"
            order = await exchange.create_order(
                symbol=pair.replace("/", "") + ":USDT",
                type="limit",
                side=side,
                amount=amount,
                price=entry_price,
                params={"tdMode": "cross", "lever": str(bot_instance.leverage)},
            )

            await exchange.close()

            # Record trade in database
            trade = Trade(
                user_id=user_id,
                signal_id=signal_id,
                pair=pair,
                direction=direction,
                entry_price=entry_price,
                amount=amount,
                size_usd=size_usd,
                status="open",
                fill_type="maker",
                exchange="bitget",
                order_ids=[order.get("id", "")],
                metadata={
                    "confidence": confidence,
                    "sl_price": sl_price,
                    "balance_at_entry": available_usd,
                },
            )
            db.add(trade)
            await db.commit()
            await db.refresh(trade)

            logger.info(f"User {user_id}: OPENED {direction} {pair} "
                        f"${size_usd:.2f} @ {entry_price}")

            return trade

        except Exception as e:
            logger.error(f"User {user_id}: trade execution failed: {e}")
            if 'exchange' in locals():
                await exchange.close()
            return None


trade_executor = TradeExecutor()
