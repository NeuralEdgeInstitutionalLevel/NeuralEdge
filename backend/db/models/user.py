"""
User model - core identity and authentication.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, func
from sqlalchemy import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(
        String(256), nullable=False
    )
    display_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    whop_user_id: Mapped[Optional[str]] = mapped_column(
        String(128), unique=True, nullable=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user"
    )
    tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="free"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    max_pairs: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    max_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_ip: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True
    )

    # Relationships
    subscriptions: Mapped[list["Subscription"]] = relationship(
        "Subscription", back_populates="user", lazy="selectin"
    )
    api_keys: Mapped[list["APIKey"]] = relationship(
        "APIKey", back_populates="user", lazy="selectin"
    )
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="user", lazy="noload"
    )
    bot_instances: Mapped[list["BotInstance"]] = relationship(
        "BotInstance", back_populates="user", lazy="selectin"
    )
    daily_snapshots: Mapped[list["DailySnapshot"]] = relationship(
        "DailySnapshot", back_populates="user", lazy="noload"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", lazy="noload"
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_whop_user_id", "whop_user_id"),
        Index("ix_users_tier", "tier"),
        Index("ix_users_is_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User {self.email} tier={self.tier}>"
