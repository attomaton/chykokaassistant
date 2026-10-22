"""SQLAlchemy ORM models.

Uses the generic ``JSON`` type (rather than Postgres-only ``JSONB``) so the
same models work against SQLite in tests and Postgres in production.
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    NOTIFIED = "notified"
    RESOLVED = "resolved"


class DeliveryStatus(str, enum.Enum):
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))
    role: Mapped[str] = mapped_column(String(16), default=UserRole.CUSTOMER.value, nullable=False, index=True)

    # Lightweight server-side FSM state, required because Vercel functions
    # are stateless and cannot rely on in-process memory between requests.
    fsm_state: Mapped[str | None] = mapped_column(String(64))
    fsm_data: Mapped[dict | None] = mapped_column(JSON)

    # DB-backed fixed-window rate limiting (per Telegram user).
    rate_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_window_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    support_requests: Mapped[list["SupportRequest"]] = relationship(
        back_populates="user", foreign_keys="SupportRequest.user_id"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    user: Mapped["User"] = relationship(back_populates="conversations")


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    original_question: Mapped[str] = mapped_column(Text, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text)
    missing_information: Mapped[list | None] = mapped_column(JSON)

    customer_name: Mapped[str | None] = mapped_column(String(128))
    customer_phone: Mapped[str | None] = mapped_column(String(32))
    customer_email: Mapped[str | None] = mapped_column(String(128))

    status: Mapped[str] = mapped_column(String(16), default=RequestStatus.PENDING.value, nullable=False, index=True)
    admin_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="support_requests", foreign_keys=[user_id])
    admin_replies: Mapped[list["AdminReply"]] = relationship(
        back_populates="support_request", cascade="all, delete-orphan"
    )


class AdminReply(Base):
    __tablename__ = "admin_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    support_request_id: Mapped[int] = mapped_column(
        ForeignKey("support_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivery_status: Mapped[str] = mapped_column(String(16), default=DeliveryStatus.PENDING.value, nullable=False)

    support_request: Mapped["SupportRequest"] = relationship(back_populates="admin_replies")


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProcessedUpdate(Base):
    """Records Telegram update_ids already handled, for webhook dedup.

    Required because Vercel invocations do not share process memory, so
    in-memory dedup would miss duplicates delivered to a different instance.
    """

    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
