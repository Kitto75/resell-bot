from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import Enum
from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ResellerStatus(str, Enum):
    active = "active"
    disabled = "disabled"
    archived = "archived"


class TransactionType(str, Enum):
    increase = "increase"
    decrease = "decrease"
    set_balance = "set_balance"
    create_user = "create_user"
    renew_user = "renew_user"
    recharge = "recharge"


class RechargeStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class OperationType(str, Enum):
    create = "create"
    renew = "renew"


class Reseller(Base):
    __tablename__ = "resellers"
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    price_per_gb: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[ResellerStatus] = mapped_column(SAEnum(ResellerStatus), default=ResellerStatus.active)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    transactions: Mapped[list[BalanceTransaction]] = relationship(back_populates="reseller")


class BalanceTransaction(Base):
    __tablename__ = "balance_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), index=True)
    type: Mapped[TransactionType] = mapped_column(SAEnum(TransactionType))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_before: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    reseller: Mapped[Reseller] = relationship(back_populates="transactions")


class RechargeRequest(Base):
    __tablename__ = "recharge_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    receipt_file_id: Mapped[str | None] = mapped_column(String(255))
    receipt_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RechargeStatus] = mapped_column(SAEnum(RechargeStatus), default=RechargeStatus.pending)
    admin_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResellerInbound(Base):
    __tablename__ = "reseller_inbounds"
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), index=True)
    inbound_tag: Mapped[str] = mapped_column(String(255))
    __table_args__ = (UniqueConstraint("reseller_id", "inbound_tag"),)


class CreatedUser(Base):
    __tablename__ = "created_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    marzban_status: Mapped[str] = mapped_column(String(50), default="on_hold")
    total_gb: Mapped[int] = mapped_column(Integer, default=0)
    total_days: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_created_users_reseller_username", "reseller_id", "username"),)


class BotSetting(Base):
    __tablename__ = "bot_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class OperationLog(Base):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey("resellers.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    operation_type: Mapped[OperationType] = mapped_column(SAEnum(OperationType))
    added_gb: Mapped[int] = mapped_column(Integer)
    added_days: Mapped[int] = mapped_column(Integer)
    charged_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_before: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
