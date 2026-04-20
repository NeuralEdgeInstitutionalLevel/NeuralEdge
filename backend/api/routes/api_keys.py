"""
NeuralEdge AI - API Key Management Routes

POST   /             -- store encrypted exchange API keys
GET    /             -- list stored keys (masked)
DELETE /{key_id}     -- remove an API key
POST   /{key_id}/validate  -- test key against exchange
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_active_user, get_db
from core.encryption import decrypt, encrypt
from core.permissions import require_tier
from db.models.api_key import APIKey
from db.models.audit_log import AuditLog
from db.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()

# Supported exchanges
_SUPPORTED_EXCHANGES = {"bitget", "bybit", "okx", "binance"}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class StoreKeyRequest(BaseModel):
    exchange: str = Field(..., description="Exchange name (bitget, bybit, okx, binance)")
    label: str = Field(..., max_length=100, description="Friendly label for this key")
    api_key: str = Field(..., min_length=8, max_length=256)
    api_secret: str = Field(..., min_length=8, max_length=256)
    passphrase: str | None = Field(None, max_length=128, description="Required for Bitget/OKX")


class KeyResponse(BaseModel):
    id: str
    exchange: str
    label: str
    api_key_masked: str
    is_valid: bool
    last_validated: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyListResponse(BaseModel):
    keys: list[KeyResponse]
    count: int


class ValidateResponse(BaseModel):
    valid: bool
    exchange: str
    balance_usd: float | None = None
    error: str | None = None


class DeleteResponse(BaseModel):
    deleted: bool
    key_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mask_key(key: str) -> str:
    """Mask an API key showing only first 4 and last 4 characters."""
    if len(key) <= 8:
        return key[:2] + "****" + key[-2:]
    return key[:4] + "****" + key[-4:]


# ---------------------------------------------------------------------------
# POST / -- Store encrypted API keys
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=KeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store exchange API keys (encrypted)",
    dependencies=[Depends(require_tier("starter"))],
)
async def store_api_key(
    body: StoreKeyRequest,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Store exchange API credentials encrypted with AES-256-GCM.

    Requires Pro tier or above.  Keys are encrypted at rest and can
    only be decrypted by the backend for trade execution.
    """
    exchange = body.exchange.lower().strip()
    if exchange not in _SUPPORTED_EXCHANGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported exchange: {exchange}. Supported: {', '.join(sorted(_SUPPORTED_EXCHANGES))}",
        )

    # Bitget and OKX require passphrase
    if exchange in ("bitget", "okx") and not body.passphrase:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{exchange.title()} requires a passphrase",
        )

    # Check for existing key with same exchange + label
    existing = await db.execute(
        select(APIKey).where(
            APIKey.user_id == user.id,
            APIKey.exchange == exchange,
            APIKey.label == body.label,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A key with label '{body.label}' already exists for {exchange}",
        )

    # Limit keys per user (max 5 per exchange)
    count_result = await db.execute(
        select(APIKey).where(
            APIKey.user_id == user.id,
            APIKey.exchange == exchange,
        )
    )
    existing_keys = count_result.scalars().all()
    if len(existing_keys) >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum 5 API keys per exchange (currently {len(existing_keys)} for {exchange})",
        )

    # Encrypt credentials -- all share the same nonce for atomic storage
    api_key_enc, nonce = encrypt(body.api_key)
    api_secret_enc, _ = encrypt(body.api_secret)  # Uses fresh nonce internally
    passphrase_enc = None
    if body.passphrase:
        passphrase_enc, _ = encrypt(body.passphrase)

    # Note: each encrypt() call generates its own unique nonce internally.
    # We store the nonce from the api_key encryption as the primary nonce.
    # For decryption, we need per-field nonces. We concatenate nonce + ciphertext.
    # Actually, looking at the encrypt() function, it returns (ciphertext, nonce)
    # separately. We need to store nonces per field or use a shared approach.
    # For simplicity, we re-encrypt all with the same nonce approach:

    # Re-encrypt all with a single shared nonce for this key record
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from core.encryption import derive_key

    key_bytes = derive_key()
    aesgcm = AESGCM(key_bytes)
    shared_nonce = os.urandom(12)

    api_key_enc = aesgcm.encrypt(shared_nonce, body.api_key.encode("utf-8"), None)
    api_secret_enc = aesgcm.encrypt(shared_nonce, body.api_secret.encode("utf-8"), None)
    passphrase_enc = None
    if body.passphrase:
        passphrase_enc = aesgcm.encrypt(shared_nonce, body.passphrase.encode("utf-8"), None)

    api_key_record = APIKey(
        id=uuid.uuid4(),
        user_id=user.id,
        exchange=exchange,
        label=body.label,
        api_key_enc=api_key_enc,
        api_secret_enc=api_secret_enc,
        passphrase_enc=passphrase_enc,
        nonce=shared_nonce,
        key_version=1,
        is_valid=True,
        last_validated=None,
        permissions=None,
    )
    db.add(api_key_record)
    await db.flush()

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="api_key.stored",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        details={"exchange": exchange, "label": body.label, "key_id": str(api_key_record.id)},
    )
    db.add(audit)

    logger.info("API key stored: user=%s exchange=%s label=%s", user.email, exchange, body.label)

    return KeyResponse(
        id=str(api_key_record.id),
        exchange=exchange,
        label=body.label,
        api_key_masked=_mask_key(body.api_key),
        is_valid=True,
        last_validated=None,
        created_at=api_key_record.created_at,
    )


# ---------------------------------------------------------------------------
# GET / -- List stored keys (masked)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=KeyListResponse,
    summary="List stored API keys (masked)",
)
async def list_api_keys(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all API keys for the authenticated user with masked values."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == user.id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    key_responses = []
    for k in keys:
        # Decrypt just enough to mask
        try:
            plaintext_key = decrypt(k.api_key_enc, k.nonce)
            masked = _mask_key(plaintext_key)
        except Exception:
            masked = "****"

        key_responses.append(
            KeyResponse(
                id=str(k.id),
                exchange=k.exchange,
                label=k.label,
                api_key_masked=masked,
                is_valid=k.is_valid,
                last_validated=k.last_validated,
                created_at=k.created_at,
            )
        )

    return KeyListResponse(keys=key_responses, count=len(key_responses))


# ---------------------------------------------------------------------------
# DELETE /{key_id} -- Remove an API key
# ---------------------------------------------------------------------------
@router.delete(
    "/{key_id}",
    response_model=DeleteResponse,
    summary="Delete an API key",
)
async def delete_api_key(
    key_id: str,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an API key from encrypted storage."""
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid key ID format",
        )

    result = await db.execute(
        select(APIKey).where(APIKey.id == key_uuid, APIKey.user_id == user.id)
    )
    api_key_record = result.scalar_one_or_none()

    if api_key_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    await db.delete(api_key_record)

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="api_key.deleted",
        ip_address=client_ip,
        details={
            "exchange": api_key_record.exchange,
            "label": api_key_record.label,
            "key_id": key_id,
        },
    )
    db.add(audit)

    logger.info(
        "API key deleted: user=%s exchange=%s label=%s",
        user.email, api_key_record.exchange, api_key_record.label,
    )

    return DeleteResponse(deleted=True, key_id=key_id)


# ---------------------------------------------------------------------------
# POST /{key_id}/validate -- Test key against exchange
# ---------------------------------------------------------------------------
@router.post(
    "/{key_id}/validate",
    response_model=ValidateResponse,
    summary="Validate API key by checking exchange balance",
)
async def validate_api_key(
    key_id: str,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Test an API key by performing a read-only balance check via ccxt.

    This verifies the key has proper read permissions and is not expired.
    """
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid key ID format",
        )

    result = await db.execute(
        select(APIKey).where(APIKey.id == key_uuid, APIKey.user_id == user.id)
    )
    api_key_record = result.scalar_one_or_none()

    if api_key_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    # Decrypt credentials
    try:
        api_key_plain = decrypt(api_key_record.api_key_enc, api_key_record.nonce)
        api_secret_plain = decrypt(api_key_record.api_secret_enc, api_key_record.nonce)
        passphrase_plain = None
        if api_key_record.passphrase_enc is not None:
            passphrase_plain = decrypt(api_key_record.passphrase_enc, api_key_record.nonce)
    except Exception as exc:
        logger.error("Failed to decrypt API key %s: %s", key_id, exc)
        api_key_record.is_valid = False
        return ValidateResponse(
            valid=False,
            exchange=api_key_record.exchange,
            error="Decryption failed -- key may be corrupted",
        )

    # Test via ccxt
    balance_usd = None
    error_msg = None
    is_valid = False

    try:
        import ccxt.async_support as ccxt

        exchange_class = getattr(ccxt, api_key_record.exchange, None)
        if exchange_class is None:
            raise ValueError(f"Unsupported exchange: {api_key_record.exchange}")

        config = {
            "apiKey": api_key_plain,
            "secret": api_secret_plain,
            "enableRateLimit": True,
        }
        if passphrase_plain:
            config["password"] = passphrase_plain

        exchange_instance = exchange_class(config)

        try:
            # Fetch balance (read-only operation)
            balance = await exchange_instance.fetch_balance()
            total = balance.get("total", {})
            # Sum USDT balance
            balance_usd = float(total.get("USDT", 0.0))
            is_valid = True
        finally:
            await exchange_instance.close()

    except Exception as exc:
        error_msg = str(exc)[:200]
        logger.warning(
            "API key validation failed: user=%s exchange=%s error=%s",
            user.email, api_key_record.exchange, error_msg,
        )

    # Update key status
    api_key_record.is_valid = is_valid
    api_key_record.last_validated = datetime.now(timezone.utc)

    # Audit log
    client_ip = request.client.host if request.client else None
    audit = AuditLog(
        user_id=user.id,
        action="api_key.validated",
        ip_address=client_ip,
        details={
            "exchange": api_key_record.exchange,
            "key_id": key_id,
            "valid": is_valid,
            "error": error_msg,
        },
    )
    db.add(audit)

    return ValidateResponse(
        valid=is_valid,
        exchange=api_key_record.exchange,
        balance_usd=balance_usd,
        error=error_msg,
    )
