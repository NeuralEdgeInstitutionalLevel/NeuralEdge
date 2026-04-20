"""
NeuralEdge AI Backend - One-click setup and run.
Creates database tables, admin user, and starts the server.

Usage:
    python setup_and_run.py          # Setup DB + start server
    python setup_and_run.py --setup  # Setup DB only (no server)
"""
import asyncio
import sys
import os
import subprocess

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def setup_database():
    """Create all tables and seed admin user."""
    print("\n" + "=" * 60)
    print("  NeuralEdge AI Backend Setup")
    print("=" * 60)

    # Wait for PostgreSQL to be ready
    print("\n[1/4] Waiting for PostgreSQL...")
    for attempt in range(30):
        try:
            from sqlalchemy import text
            from db.session import async_engine
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("  PostgreSQL is ready!")
            break
        except Exception as e:
            if attempt == 29:
                print(f"  FAILED: PostgreSQL not reachable after 30 attempts: {e}")
                print("  Make sure docker-compose is running: docker-compose up -d")
                return False
            await asyncio.sleep(2)

    # Create all tables
    print("\n[2/4] Creating database tables...")
    from db.base import Base
    from db.models import User, Subscription, APIKey, Signal, Trade, BotInstance, DailySnapshot, AuditLog
    from db.session import async_engine

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  8 tables created successfully!")

    # Create admin user if not exists
    print("\n[3/4] Creating admin user...")
    from db.session import async_session_factory
    from core.security import hash_password
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == "admin@neuraledge.ai")
        )
        admin = result.scalar_one_or_none()

        if admin:
            print(f"  Admin already exists: {admin.email}")
        else:
            admin_password = os.getenv("ADMIN_PASSWORD", "NeuralEdge2026!")
            admin = User(
                email="admin@neuraledge.ai",
                password_hash=hash_password(admin_password),
                display_name="Admin",
                role="admin",
                tier="system",
                is_active=True,
                is_email_verified=True,
                max_pairs=24,
                max_positions=24,
            )
            session.add(admin)
            await session.commit()
            print(f"  Admin created: admin@neuraledge.ai / {admin_password}")

    # Create system performance user (for public track record)
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == "system@neuraledge.ai")
        )
        system_user = result.scalar_one_or_none()

        if not system_user:
            system_user = User(
                email="system@neuraledge.ai",
                password_hash=hash_password("system-internal-do-not-login"),
                display_name="NeuralEdge System",
                role="admin",
                tier="system",
                is_active=True,
                is_email_verified=True,
                max_pairs=24,
                max_positions=24,
            )
            session.add(system_user)
            await session.commit()
            print("  System user created for public track record")

    # Wait for Redis
    print("\n[4/4] Checking Redis...")
    try:
        import redis.asyncio as aioredis
        from config import settings
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        print("  Redis is ready!")
    except Exception as e:
        print(f"  WARNING: Redis not available: {e}")
        print("  WebSocket and rate limiting will not work without Redis.")

    print("\n" + "=" * 60)
    print("  Setup complete!")
    print("=" * 60)
    return True


def start_server():
    """Start the FastAPI server."""
    print("\n  Starting NeuralEdge AI Backend...")
    print("  API docs: http://localhost:8000/api/docs")
    print("  Health:   http://localhost:8000/api/health")
    print("=" * 60 + "\n")

    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--reload" if os.getenv("ENVIRONMENT") == "development" else "--workers=4",
    ], cwd=os.path.dirname(os.path.abspath(__file__)))


if __name__ == "__main__":
    success = asyncio.run(setup_database())

    if not success:
        sys.exit(1)

    if "--setup" not in sys.argv:
        start_server()
    else:
        print("\n  Setup-only mode. Run 'python setup_and_run.py' to start server.")
