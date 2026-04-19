"""
BotInstance model - per-user bot configuration and runtime state.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class BotInstance(Base):
    __tablename__ = "bot_instances"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="stopped"
    )
    exchange: Mapped[str] = mapped_column(
        String(20), nullable=False, default="bitget"
    )
    max_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8
    )
    max_exposure_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=80.0
    )
    min_trade_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=5.0
    )
    max_trade_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=100.0
    )
    leverage: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2
    )
    pairs: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    disabled_pairs: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    daily_loss_limit_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=5.0
    )
    max_drawdown_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=15.0
    )
    sizing_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="auto"
    )
    fixed_size_usd: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    pct_size: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bot_instances")

    __table_args__ = (
        Index("ix_bot_instances_user_id", "user_id"),
        Index("ix_bot_instances_status", "status"),
        Index("ix_bot_instances_last_heartbeat", "last_heartbeat"),
    )

    def __repr__(self) -> str:
        return f"<BotInstance user={self.user_id} status={self.status} exchange={self.exchange}>"
