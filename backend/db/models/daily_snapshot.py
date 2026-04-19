"""
DailySnapshot model - daily equity and performance tracking per user.
"""
import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    equity_usd: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    daily_pnl_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    daily_pnl_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    open_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    total_trades: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    winning_trades: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    sharpe_30d: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    max_dd_30d: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    metadata_: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="daily_snapshots")

    __table_args__ = (
        Index("ix_daily_snapshots_user_id", "user_id"),
        Index("ix_daily_snapshots_date", "date"),
        Index("ix_daily_snapshots_user_date", "user_id", "date", unique=True),
    )

    def __repr__(self) -> str:
        return f"<DailySnapshot user={self.user_id} date={self.date} equity={self.equity_usd}>"
