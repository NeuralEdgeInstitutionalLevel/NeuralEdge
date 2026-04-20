"""
NeuralEdge AI SaaS Backend
Institutional-grade trading bot platform API.
Security hardened: CSP, HSTS, brute force protection, request signing, audit logging.
"""
import logging
import uuid
import time
import hashlib
import hmac
from contextlib import asynccontextmanager
from collections import defaultdict

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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

    # Initialize Redis (or fakeredis for dev)
    if settings.REDIS_URL:
        import redis.asyncio as aioredis
        app.state.redis = aioredis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
        logger.info("Redis connected")
    else:
        import fakeredis.aioredis
        app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        logger.info("Using FakeRedis (development mode)")

    # Auto-create tables on startup (development)
    if settings.ENVIRONMENT == "development":
        from db.base import Base
        from db.models import User, Subscription, APIKey, Signal, Trade, BotInstance, DailySnapshot, AuditLog
        from db.session import async_engine
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    yield

    # Shutdown
    if hasattr(app.state.redis, 'close'):
        await app.state.redis.close()
    logger.info("Shutdown complete")


# === SECURITY MIDDLEWARE ===

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://client.crisp.chat; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' https://api.binance.com wss://stream.binance.com https://client.crisp.chat"
        # Strict Transport Security (HTTPS only)
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        # Unique request ID for tracing
        response.headers["X-Request-ID"] = str(uuid.uuid4())
        return response


class BruteForceProtectionMiddleware(BaseHTTPMiddleware):
    """Block IPs after too many failed login attempts."""
    def __init__(self, app, max_attempts: int = 5, lockout_seconds: int = 900):
        super().__init__(app)
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self.failed_attempts = defaultdict(list)  # ip -> [timestamps]

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/api/auth/login" and request.method == "POST":
            ip = request.client.host if request.client else "unknown"
            now = time.time()

            # Clean old entries
            self.failed_attempts[ip] = [t for t in self.failed_attempts[ip] if now - t < self.lockout_seconds]

            # Check if locked out
            if len(self.failed_attempts[ip]) >= self.max_attempts:
                remaining = int(self.lockout_seconds - (now - self.failed_attempts[ip][0]))
                return Response(
                    content=f'{{"detail":"Too many login attempts. Try again in {remaining} seconds."}}',
                    status_code=429,
                    media_type="application/json"
                )

            response = await call_next(request)

            # Track failed attempts
            if response.status_code == 401:
                self.failed_attempts[ip].append(now)
                attempts_left = self.max_attempts - len(self.failed_attempts[ip])
                if attempts_left > 0:
                    response.headers["X-Attempts-Remaining"] = str(attempts_left)

            # Clear on success
            if response.status_code == 200:
                self.failed_attempts.pop(ip, None)

            return response

        return await call_next(request)


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit ALL API requests per IP. Prevents abuse on any endpoint."""
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.requests = defaultdict(list)  # ip -> [timestamps]

    async def dispatch(self, request: Request, call_next):
        # Only rate limit API paths
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean entries older than 60s
        self.requests[ip] = [t for t in self.requests[ip] if now - t < 60]

        if len(self.requests[ip]) >= self.rpm:
            return Response(
                content='{"detail":"Rate limit exceeded. Max 60 requests/minute."}',
                status_code=429,
                media_type="application/json"
            )

        self.requests[ip].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(self.rpm - len(self.requests[ip]))
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing for security audit."""
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        # Log slow requests, auth attempts, and errors
        ip = request.client.host if request.client else "unknown"
        if duration > 5.0 or "auth" in request.url.path or response.status_code >= 400:
            logger.info(f"[{request.method}] {request.url.path} -> {response.status_code} ({duration:.2f}s) IP={ip}")

        return response


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

# === Security Middleware (order matters: first added = outermost) ===
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(GlobalRateLimitMiddleware, requests_per_minute=60)
app.add_middleware(BruteForceProtectionMiddleware, max_attempts=5, lockout_seconds=900)
app.add_middleware(SecurityHeadersMiddleware)


# === Import and register routers ===
from api.routes import auth, whop, subscriptions, api_keys, dashboard, bot_control, signals, admin, performance, ws, two_factor

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
app.include_router(two_factor.router, prefix="/api/2fa", tags=["Two-Factor Auth"])


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
