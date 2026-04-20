"""
NeuralEdge AI - Two-Factor Authentication Routes

POST /2fa/enable   -- generate TOTP secret + QR code
POST /2fa/verify   -- verify code and activate 2FA
POST /2fa/disable  -- disable 2FA (requires current code)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from core.totp import generate_totp_secret, verify_totp, generate_qr_base64
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


class Enable2FAResponse(BaseModel):
    secret: str
    qr_code: str  # base64 PNG


class Verify2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


# ---------------------------------------------------------------------------
# POST /enable -- Generate secret + QR code
# ---------------------------------------------------------------------------
@router.post("/enable", response_model=Enable2FAResponse)
async def enable_2fa(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new TOTP secret and QR code. User must call /verify to activate."""
    if user.is_2fa_enabled:
        raise HTTPException(status_code=400, detail="2FA is already enabled")

    secret = generate_totp_secret()
    user.totp_secret = secret  # Store but don't enable yet
    await db.commit()

    qr = generate_qr_base64(secret, user.email)
    logger.info(f"2FA setup initiated for {user.email}")

    return Enable2FAResponse(secret=secret, qr_code=qr)


# ---------------------------------------------------------------------------
# POST /verify -- Verify code and activate 2FA
# ---------------------------------------------------------------------------
@router.post("/verify")
async def verify_and_activate_2fa(
    body: Verify2FARequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify a TOTP code to activate 2FA on the account."""
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="Call /enable first to generate a secret")

    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    user.is_2fa_enabled = True
    await db.commit()
    logger.info(f"2FA activated for {user.email}")

    return {"status": "2fa_enabled", "message": "Two-factor authentication is now active"}


# ---------------------------------------------------------------------------
# POST /disable -- Disable 2FA (requires valid code)
# ---------------------------------------------------------------------------
@router.post("/disable")
async def disable_2fa(
    body: Verify2FARequest,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable 2FA. Requires a valid current code to prevent unauthorized disabling."""
    if not user.is_2fa_enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled")

    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code. Cannot disable.")

    user.is_2fa_enabled = False
    user.totp_secret = None
    await db.commit()
    logger.info(f"2FA disabled for {user.email}")

    return {"status": "2fa_disabled", "message": "Two-factor authentication has been disabled"}
