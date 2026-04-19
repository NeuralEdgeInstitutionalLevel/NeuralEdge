"""
Daily snapshot computation and partition management.
"""
import logging
from workers.celery_app import celery_app

logger = logging.getLogger("neuraledge.snapshot_worker")


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

                    snapshot = DailySnapshot(
                        user_id=user.id,
                        date=yesterday,
                        equity_usd=0,  # TODO: fetch from exchange
                        daily_pnl_usd=float(row.pnl),
                        daily_pnl_pct=0,
                        open_positions=0,
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
    """Create next month's table partitions for signals, trades, audit_log."""
    logger.info("Creating next month partitions...")
    # Implementation: ALTER TABLE ... ADD PARTITION
    pass
