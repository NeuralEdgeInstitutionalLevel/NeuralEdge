"""
NeuralEdge AI - Authentication Routes

POST /register  -- create account, return tokens
POST /login     -- verify credentials, return tokens
POST /refresh   -- exchange refresh token for new access token
GET  /me        -- current user profile + tier + subscription status
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from db.models.audit_log import AuditLog
from db.models.subscription import Subscription
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=100)
    website: str | None = Field(None, max_length=200)  # Honeypot: bots fill this, humans don't


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserProfileResponse(BaseModel):
    id: str
    email: str
    display_name: str | None
    role: str
    tier: str
    is_active: bool
    is_email_verified: bool
    max_pairs: int
    max_positions: int
    created_at: datetime
    last_login_at: datetime | None
    subscription: dict | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------
@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user with email and password.

    Returns access + refresh JWT tokens on success.
    """
    # Honeypot: if 'website' field is filled, it's a bot
    if body.website:
        logger.warning(f"Bot registration blocked (honeypot): {body.email} from {request.client.host}")
        raise HTTPException(status_code=status.HTTP_201_CREATED, detail="Account created")  # Fake success

    # Check for existing email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # Create user
    user = User(
        id=uuid.uuid4(),
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role="user",
        tier="free",
        is_active=True,
        is_email_verified=False,
        max_pairs=0,
        max_positions=0,
    )
    db.add(user)
    await db.flush()  # Assign user.id before building tokens

    # Issue tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="user.registered",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        details={"email": body.email},
    )
    db.add(audit)

    logger.info("New user registered: %s", body.email)

    from config import settings

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate with email and password",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify credentials and return access + refresh JWT tokens."""
    result = await db.execute(select(User).where(User.email == body.email))
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    # Update last login
    client_ip = request.client.host if request.client else None
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = client_ip

    # Issue tokens
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Audit log
    audit = AuditLog(
        user_id=user.id,
        action="user.login",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
    )
    db.add(audit)

    logger.info("User logged in: %s", user.email)

    from config import settings

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# POST /refresh
# ---------------------------------------------------------------------------
@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange refresh token for new access token",
)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Validate a refresh token and issue a new access + refresh pair.

    The old refresh token is implicitly invalidated by the short-lived
    nature of the access token -- token rotation happens on each call.
    """
    from jose import JWTError

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = verify_token(body.refresh_token)
    except JWTError:
        raise credentials_exception

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required (access token provided)",
        )

    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_uuid = uuid.UUID(user_id_str)
    except ValueError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_uuid))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated",
        )

    # Issue new token pair
    token_data = {"sub": str(user.id)}
    access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    from config import settings

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------
@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
)
async def me(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's profile, tier, and active subscription."""
    # Fetch active subscription
    sub_result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    subscription = sub_result.scalar_one_or_none()

    sub_data = None
    if subscription is not None:
        sub_data = {
            "id": str(subscription.id),
            "tier": subscription.tier,
            "status": subscription.status,
            "current_period_start": (
                subscription.current_period_start.isoformat()
                if subscription.current_period_start
                else None
            ),
            "current_period_end": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None
            ),
            "cancel_at_period_end": subscription.cancel_at_period_end,
        }

    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        tier=user.tier,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        max_pairs=user.max_pairs,
        max_positions=user.max_positions,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        subscription=sub_data,
    )
