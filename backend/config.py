"""
NeuralEdge AI SaaS Backend - Configuration
All settings via environment variables with sensible defaults.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # === Application ===
    APP_NAME: str = "NeuralEdge AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"  # development | staging | production

    # === Server ===
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    ALLOWED_ORIGINS: list[str] = [
        "https://neuraledgeinstitutionallevel.github.io",
        "https://neuraledge.ai",
        "http://localhost:3000",
    ]

    # === Database ===
    DATABASE_URL: str = "postgresql+asyncpg://neuraledge:neuraledge@localhost:5432/neuraledge"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30

    # === Redis ===
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50

    # === Security - JWT ===
    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION-USE-OPENSSL-RAND-HEX-64"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # === Security - Encryption (AES-256-GCM for API keys) ===
    ENCRYPTION_MASTER_KEY: str = "CHANGE-ME-USE-OPENSSL-RAND-HEX-32"

    # === Security - Rate Limiting ===
    RATE_LIMIT_UNAUTH: int = 20       # per minute
    RATE_LIMIT_AUTH: int = 120         # per minute
    RATE_LIMIT_ADMIN: int = 600        # per minute
    RATE_LIMIT_TRADE: int = 5          # per minute

    # === Whop Integration ===
    WHOP_API_KEY: str = ""
    WHOP_WEBHOOK_SECRET: str = ""
    WHOP_PLAN_MAP: dict = {
        "plan_starter": "starter",
        "plan_pro": "pro",
        "plan_elite": "elite",
        "plan_system": "system",
    }

    # === Internal API (Trading bot -> Backend) ===
    INTERNAL_API_KEY: str = "CHANGE-ME-INTERNAL-SECRET"

    # === Telegram Notifications ===
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_CHAT_ID: str = ""

    # === Tier Configuration ===
    TIER_LIMITS: dict = {
        "free": {"max_pairs": 0, "max_positions": 0, "auto_execute": False, "dashboard": False},
        "starter": {"max_pairs": 3, "max_positions": 3, "auto_execute": False, "dashboard": False},
        "pro": {"max_pairs": 24, "max_positions": 8, "auto_execute": True, "dashboard": True},
        "elite": {"max_pairs": 24, "max_positions": 12, "auto_execute": True, "dashboard": True},
        "system": {"max_pairs": 24, "max_positions": 24, "auto_execute": True, "dashboard": True},
    }

    # === Email (future) ===
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = "noreply@neuraledge.ai"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": True}


settings = Settings()
