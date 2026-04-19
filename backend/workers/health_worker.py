"""
System health monitoring worker.
"""
import logging
from workers.celery_app import celery_app

logger = logging.getLogger("neuraledge.health_worker")


@celery_app.task(name="workers.health_worker.check_system_health", queue="health")
def check_system_health():
    """Check system health every 60 seconds."""
    import asyncio

    async def _check():
        from sqlalchemy import select, func
        from db.session import async_session_factory
        from db.models.bot_instance import BotInstance
        from datetime import datetime, timedelta, timezone

        async with async_session_factory() as db:
            # Check for stale bot instances (no heartbeat in 5 minutes)
            stale_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
            result = await db.execute(
                select(func.count(BotInstance.id)).where(
                    BotInstance.status == "running",
                    BotInstance.last_heartbeat < stale_threshold,
                )
            )
            stale_count = result.scalar()
            if stale_count > 0:
                logger.warning(f"{stale_count} bot instances have stale heartbeats")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_check())
    finally:
        loop.close()
