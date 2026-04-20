"""
Daily snapshot computation and partition management.
"""
import logging
from workers.celery_app import celery_app

logger = logging.getLogger("neuraledge.snapshot_worker")


async def _fetch_user_equity(user_id) -> float:
    """Fetch real USDT equity from user's Bitget account via ccxt."""
    from sqlalchemy import select
    from db.session import async_session_factory
    from db.models.api_key import APIKey
    from core.encryption import decrypt

    async with async_session_factory() as db:
        stmt = select(APIKey).where(
            APIKey.user_id == user_id,
            APIKey.exchange == "bitget",
            APIKey.is_valid == True,
        )
        result = await db.execute(stmt)
        api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        return 0.0

    try:
        api_key = decrypt(api_key_record.api_key_enc, api_key_record.nonce)
        api_secret = decrypt(api_key_record.api_secret_enc, api_key_record.nonce)
        passphrase = None
        if api_key_record.passphrase_enc:
            passphrase = decrypt(api_key_record.passphrase_enc, api_key_record.nonce)

        import ccxt.async_support as ccxt_async
        exchange = ccxt_async.bitget({
            "apiKey": api_key,
            "secret": api_secret,
            "password": passphrase,
            "options": {"defaultType": "swap"},
        })

        balance = await exchange.fetch_balance()
        equity = float(balance.get("USDT", {}).get("total", 0))
        await exchange.close()
        return equity
    except Exception as e:
        logger.warning(f"User {user_id}: equity fetch failed: {e}")
        if "exchange" in locals():
            try:
                await exchange.close()
            except Exception:
                pass
        return 0.0


@celery_app.task(name="workers.snapshot_worker.compute_daily_snapshots", queue="snapshots")
def compute_daily_snapshots():
    """Compute daily PnL snapshots for all active users. Runs at 00:05 UTC."""
    import asyncio

    async def _compute():
        from sqlalchemy import select, func
        from db.session import async_session_factory
        from db.models.user import User
        from db.models.trade import Trade
        from db.models.daily_snapshot import DailySnapshot
        from datetime import date, timedelta

        today = date.today()
        yesterday = today - timedelta(days=1)

        async with async_session_factory() as db:
            # Get all active users
            result = await db.execute(select(User).where(User.is_active == True))
            users = result.scalars().all()

            for user in users:
                try:
                    # Count trades from yesterday
                    trade_result = await db.execute(
                        select(
                            func.count(Trade.id).label("total"),
                            func.count(Trade.id).filter(Trade.pnl_usd > 0).label("wins"),
                            func.coalesce(func.sum(Trade.pnl_usd), 0).label("pnl"),
                        ).where(
                            Trade.user_id == user.id,
                            func.date(Trade.opened_at) == yesterday,
                        )
                    )
                    row = trade_result.one()

                    # Fetch real equity from exchange
                    equity = await _fetch_user_equity(user.id)

                    # Compute PnL percentage
                    prev_stmt = select(DailySnapshot).where(
                        DailySnapshot.user_id == user.id,
                        DailySnapshot.date == yesterday - timedelta(days=1),
                    )
                    prev_result = await db.execute(prev_stmt)
                    prev_snap = prev_result.scalar_one_or_none()
                    prev_equity = prev_snap.equity_usd if prev_snap and prev_snap.equity_usd > 0 else equity
                    daily_pnl_pct = (float(row.pnl) / prev_equity * 100) if prev_equity > 0 else 0.0

                    # Count open positions
                    open_count_result = await db.execute(
                        select(func.count(Trade.id)).where(
                            Trade.user_id == user.id,
                            Trade.status == "open",
                        )
                    )
                    open_positions = open_count_result.scalar() or 0

                    snapshot = DailySnapshot(
                        user_id=user.id,
                        date=yesterday,
                        equity_usd=equity,
                        daily_pnl_usd=float(row.pnl),
                        daily_pnl_pct=daily_pnl_pct,
                        open_positions=open_positions,
                        total_trades=row.total,
                        winning_trades=row.wins,
                    )
                    db.add(snapshot)
                except Exception as e:
                    logger.error(f"Snapshot failed for user {user.id}: {e}")

            await db.commit()
            logger.info(f"Daily snapshots computed for {len(users)} users")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_compute())
    finally:
        loop.close()


@celery_app.task(name="workers.snapshot_worker.create_next_month_partitions", queue="snapshots")
def create_next_month_partitions():
    """Create next month's PostgreSQL range partitions for high-volume tables.

    Partitions signals, trades, and audit_logs by month for query performance.
    Safe to call repeatedly -- skips if partition already exists.
    """
    import asyncio

    async def _partition():
        from datetime import date, timedelta
        from sqlalchemy import text
        from db.session import async_engine

        # Target the NEXT month
        today = date.today()
        if today.month == 12:
            next_start = date(today.year + 1, 1, 1)
            next_end = date(today.year + 1, 2, 1)
        else:
            next_start = date(today.year, today.month + 1, 1)
            if today.month + 1 == 12:
                next_end = date(today.year + 1, 1, 1)
            else:
                next_end = date(today.year, today.month + 2, 1)

        suffix = next_start.strftime("%Y_%m")
        tables = {
            "signals": "created_at",
            "trades": "opened_at",
            "audit_logs": "created_at",
        }

        async with async_engine.begin() as conn:
            for table, col in tables.items():
                partition_name = f"{table}_{suffix}"
                try:
                    await conn.execute(text(
                        f"CREATE TABLE IF NOT EXISTS {partition_name} "
                        f"PARTITION OF {table} "
                        f"FOR VALUES FROM ('{next_start.isoformat()}') "
                        f"TO ('{next_end.isoformat()}')"
                    ))
                    logger.info(f"Partition {partition_name} ready")
                except Exception as e:
                    # Table may not be partitioned yet (dev mode / SQLite)
                    logger.debug(f"Partition {partition_name} skipped: {e}")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_partition())
    finally:
        loop.close()
