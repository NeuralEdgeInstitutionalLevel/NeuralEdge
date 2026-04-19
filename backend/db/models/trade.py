"""
Trade model - individual user trades linked to signals.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    signal_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("signals.id", ondelete="SET NULL"), nullable=True
    )
    pair: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    direction: Mapped[str] = mapped_column(
        String(5), nullable=False
    )
    entry_price: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    exit_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    amount: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    size_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    pnl_usd: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    pnl_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    fees_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )
    fill_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    exit_reason: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    exchange: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    order_ids: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="trades")
    signal: Mapped[Optional["Signal"]] = relationship("Signal", back_populates="trades")

    __table_args__ = (
        Index("ix_trades_user_id", "user_id"),
        Index("ix_trades_signal_id", "signal_id"),
        Index("ix_trades_pair", "pair"),
        Index("ix_trades_status", "status"),
        Index("ix_trades_user_status", "user_id", "status"),
        Index("ix_trades_user_pair", "user_id", "pair"),
        Index("ix_trades_opened_at", "opened_at"),
        Index("ix_trades_closed_at", "closed_at"),
    )

    def __repr__(self) -> str:
        return f"<Trade {self.pair} {self.direction} status={self.status} pnl={self.pnl_usd}>"
