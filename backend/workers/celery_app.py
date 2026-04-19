"""
Celery application for background task processing.
Handles: trade execution, daily snapshots, health monitoring, key validation.
"""
from celery import Celery
from celery.schedules import crontab
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "neuraledge",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "workers.trade_worker",
        "workers.snapshot_worker",
        "workers.health_worker",
        "workers.key_validation_worker",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,

    # Result backend
    result_expires=3600,

    # Task routing
    task_routes={
        "workers.trade_worker.*": {"queue": "trades"},
        "workers.snapshot_worker.*": {"queue": "snapshots"},
        "workers.health_worker.*": {"queue": "health"},
        "workers.key_validation_worker.*": {"queue": "health"},
    },

    # Retry policy
    task_default_retry_delay=10,
    task_max_retries=3,

    # Beat schedule (periodic tasks)
    beat_schedule={
        "daily-snapshots": {
            "task": "workers.snapshot_worker.compute_daily_snapshots",
            "schedule": crontab(hour=0, minute=5),  # 00:05 UTC daily
        },
        "system-health-check": {
            "task": "workers.health_worker.check_system_health",
            "schedule": 60.0,  # every 60 seconds
        },
        "validate-api-keys": {
            "task": "workers.key_validation_worker.validate_all_keys",
            "schedule": crontab(hour="*/6", minute=0),  # every 6 hours
        },
        "create-monthly-partitions": {
            "task": "workers.snapshot_worker.create_next_month_partitions",
            "schedule": crontab(day_of_month=28, hour=12, minute=0),  # 28th of each month
        },
    },
)
