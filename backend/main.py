"""
NeuralEdge AI SaaS Backend
Institutional-grade trading bot platform API.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("neuraledge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("=" * 60)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  Environment: {settings.ENVIRONMENT}")
    logger.info("=" * 60)

    # Initialize Redis connection pool
    import redis.asyncio as aioredis
    app.state.redis = aioredis.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
    )
    logger.info("Redis connected")

    # Run Alembic migrations on startup (development only)
    if settings.ENVIRONMENT == "development":
        logger.info("Running database migrations...")

    yield

    # Shutdown
    await app.state.redis.close()
    logger.info("Shutdown complete")


# === Create FastAPI Application ===
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Institutional-grade AI crypto trading platform API",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# === CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# === Import and register routers ===
from api.routes import auth, whop, subscriptions, api_keys, dashboard, bot_control, signals, admin, performance, ws

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(whop.router, prefix="/api/whop", tags=["Whop Integration"])
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["Subscriptions"])
app.include_router(api_keys.router, prefix="/api/keys", tags=["API Keys"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(bot_control.router, prefix="/api/bot", tags=["Bot Control"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(performance.router, prefix="/api/performance", tags=["Performance"])
app.include_router(ws.router, prefix="/api/ws", tags=["WebSocket"])


# === Health Check ===
@app.get("/api/health", tags=["System"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# === Root ===
@app.get("/", include_in_schema=False)
async def root():
    return {"message": f"{settings.APP_NAME} API v{settings.APP_VERSION}"}
