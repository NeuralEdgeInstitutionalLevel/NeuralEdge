"""
NeuralEdge AI - Shared FastAPI Dependencies

Reusable ``Depends()`` providers for database sessions and user extraction.

Usage in route files::

    from api.deps import get_current_user, get_db

    @router.get("/me")
    async def me(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        return {"email": user.email}
"""
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import verify_token
from db.models.user import User
from db.session import get_session

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:
    """Yield an async SQLAlchemy session that auto-commits/rollbacks.

    Delegates to ``db.session.get_session`` -- this wrapper exists so
    route files import from a single ``api.deps`` namespace.
    """
    async for session in get_session():
        yield session


# ---------------------------------------------------------------------------
# Current user extraction
# ---------------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Extract the authenticated user from the Authorization header.

    Validates the JWT, loads the user from the database, and returns the
    ORM instance.  Raises HTTP 401 on any authentication failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    try:
        payload = verify_token(credentials.credentials)
    except JWTError:
        raise credentials_exception

    # Reject refresh tokens used as access tokens
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    result = await session.execute(select(User).where(User.id == user_uuid))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """Same as ``get_current_user`` but additionally verifies the account
    is active.  Returns HTTP 403 if the user is deactivated.
    """
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )
    return user
