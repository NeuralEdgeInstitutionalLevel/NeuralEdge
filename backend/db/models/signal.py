"""
Signal model - generated trade signals from the alpha engine.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Float, Index, String, func
from sqlalchemy import JSON as JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    pair: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    direction: Mapped[str] = mapped_column(
        String(5), nullable=False
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    magnitude: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    entry_price: Mapped[float] = mapped_column(
        Float, nullable=False
    )
    sl_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    tp_price: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    regime: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    alpha_prob: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    lgbm_prob: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    meta_prob: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    uncertainty: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    subsystem_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="signal", lazy="noload"
    )

    __table_args__ = (
        Index("ix_signals_pair", "pair"),
        Index("ix_signals_direction", "direction"),
        Index("ix_signals_created_at", "created_at"),
        Index("ix_signals_pair_created", "pair", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Signal {self.pair} {self.direction} conf={self.confidence:.3f}>"
