"""
Celery tasks for per-user trade execution.
Receives signals from the fan-out service and executes on each user's exchange account.
"""
import logging
from workers.celery_app import celery_app

logger = logging.getLogger("neuraledge.trade_worker")


@celery_app.task(
    name="workers.trade_worker.execute_trade_for_user",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    queue="trades",
)
def execute_trade_for_user(
    self,
    user_id: str,
    signal_id: int,
    pair: str,
    direction: str,
    entry_price: float,
    sl_price: float = None,
    confidence: float = 0.5,
):
    """Execute a trade for a specific user (runs in Celery worker)."""
    import asyncio

    async def _execute():
        from uuid import UUID
        from db.session import async_session_factory
        from services.trade_executor import trade_executor

        async with async_session_factory() as db:
            try:
                trade = await trade_executor.execute_for_user(
                    user_id=UUID(user_id),
                    signal_id=signal_id,
                    pair=pair,
                    direction=direction,
                    entry_price=entry_price,
                    sl_price=sl_price,
                    confidence=confidence,
                    db=db,
                )
                if trade:
                    logger.info(f"Trade executed for user {user_id}: {pair} {direction}")

                    # Publish to Redis for WebSocket fan-out
                    import redis
                    r = redis.from_url("redis://localhost:6379/0")
                    import json
                    r.publish(f"user:{user_id}:updates", json.dumps({
                        "event": "position_opened",
                        "data": {
                            "pair": pair,
                            "direction": direction,
                            "entry_price": entry_price,
                            "size_usd": trade.size_usd,
                        },
                    }))
                    r.close()
            except Exception as e:
                logger.error(f"Trade execution failed for user {user_id}: {e}")
                raise self.retry(exc=e)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_execute())
    finally:
        loop.close()


@celery_app.task(
    name="workers.trade_worker.close_trade_for_user",
    bind=True,
    max_retries=3,
    default_retry_delay=3,
    queue="trades",
)
def close_trade_for_user(
    self,
    user_id: str,
    pair: str,
    exit_reason: str = "signal",
):
    """Close an open position for a specific user."""
    logger.info(f"Closing {pair} for user {user_id}, reason: {exit_reason}")
    # Implementation similar to execute_trade_for_user but calls close logic
    pass
