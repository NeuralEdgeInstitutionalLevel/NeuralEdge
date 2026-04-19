"""
NeuralEdge AI - Role-Based Access Control (RBAC)

FastAPI dependencies for authentication and authorization:

  require_auth    -- extracts User from JWT (401 if invalid)
  require_tier()  -- ensures user tier >= min_tier (403 if insufficient)
  require_admin   -- ensures user.role == "admin" (403 if not)

Tier hierarchy (lowest to highest):
  free < starter < pro < elite < system < admin
"""
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import verify_token
from db.models.user import User
from db.session import get_session

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_TIER_HIERARCHY: list[str] = ["free", "starter", "pro", "elite", "system", "admin"]
_TIER_RANK: dict[str, int] = {t: i for i, t in enumerate(_TIER_HIERARCHY)}

_bearer_scheme = HTTPBearer(auto_error=True)

# Type aliases for cleaner route signatures
_Creds = Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)]
_Session = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Core auth dependency
# ---------------------------------------------------------------------------
async def require_auth(
    credentials: _Creds,
    session: _Session,
) -> User:
    """Extract and validate JWT, then load the User from the database.

    Raises HTTP 401 if the token is invalid/expired or the user no longer
    exists.  Raises HTTP 403 if the account is deactivated.
    """
    try:
        payload = verify_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reject refresh tokens used as access tokens
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token required (refresh token provided)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await session.execute(select(User).where(User.id == user_uuid))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    return user


# ---------------------------------------------------------------------------
# Tier-gated dependency factory
# ---------------------------------------------------------------------------
def require_tier(min_tier: str):
    """Return a FastAPI dependency that enforces a minimum subscription tier.

    Usage::

        @router.get("/signals", dependencies=[Depends(require_tier("pro"))])
        async def get_signals(user: User = Depends(require_auth)):
            ...
    """
    if min_tier not in _TIER_RANK:
        raise ValueError(f"Unknown tier '{min_tier}'. Valid: {_TIER_HIERARCHY}")

    min_rank = _TIER_RANK[min_tier]

    async def _check_tier(user: User = Depends(require_auth)) -> User:
        user_rank = _TIER_RANK.get(user.tier, 0)
        # Admins bypass tier checks
        if user.role == "admin":
            return user
        if user_rank < min_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Tier '{user.tier}' insufficient. "
                    f"Minimum required: '{min_tier}'"
                ),
            )
        return user

    return _check_tier


# ---------------------------------------------------------------------------
# Admin-only dependency
# ---------------------------------------------------------------------------
async def require_admin(user: User = Depends(require_auth)) -> User:
    """Reject non-admin users with HTTP 403."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
