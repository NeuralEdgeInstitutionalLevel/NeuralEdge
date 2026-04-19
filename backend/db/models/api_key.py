"""
APIKey model - encrypted exchange credentials (AES-256-GCM).
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    label: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    api_key_enc: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    api_secret_enc: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    passphrase_enc: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    nonce: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False
    )
    key_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    is_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    last_validated: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    permissions: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_user_exchange", "user_id", "exchange"),
        Index("ix_api_keys_is_valid", "is_valid"),
    )

    def __repr__(self) -> str:
        return f"<APIKey user={self.user_id} exchange={self.exchange} label={self.label}>"
