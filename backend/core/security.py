"""
NeuralEdge AI - JWT Authentication & Password Hashing

JWT:     HS256 via python-jose, short-lived access + long-lived refresh tokens.
Hashing: Argon2id via passlib (memory-hard, GPU-resistant).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

# ---------------------------------------------------------------------------
# Password hashing (Argon2id -- OWASP recommended, GPU-resistant)
# ---------------------------------------------------------------------------
_pwd_ctx = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",          # Argon2id (hybrid side-channel + GPU resistance)
    argon2__memory_cost=65536,  # 64 MiB
    argon2__time_cost=3,        # 3 iterations
    argon2__parallelism=4,      # 4 lanes
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against an Argon2id hash.

    Returns True on match, False otherwise (never raises on mismatch).
    """
    return _pwd_ctx.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT token creation / verification
# ---------------------------------------------------------------------------
_ALGORITHM = settings.JWT_ALGORITHM  # HS256


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived access JWT.

    Default expiry: settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES (15 min).
    The ``sub`` claim should be the user's UUID string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=_ALGORITHM)


def create_refresh_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a long-lived refresh JWT.

    Default expiry: settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS (7 days).
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=_ALGORITHM)


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT.  Returns the payload dict.

    Raises ``JWTError`` on invalid/expired/malformed tokens -- callers must
    translate this into an HTTP 401.
    """
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[_ALGORITHM],
    )
    # Require ``sub`` claim
    if payload.get("sub") is None:
        raise JWTError("Token missing 'sub' claim")
    return payload
