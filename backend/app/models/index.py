
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Index(Base):
    __tablename__ = "index_master"

    __table_args__ = (
        CheckConstraint(
            "category IN ('market_index', 'volatility_index')",
            name="ck_index_category",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    exchange: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="market_index",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    provider_mappings: Mapped[list["IndexProviderMapping"]] = relationship(
        back_populates="index",
        cascade="all, delete-orphan",
    )


class IndexProviderMapping(Base):
    __tablename__ = "index_provider_mapping"

    __table_args__ = (
        UniqueConstraint(
            "index_id",
            "provider_name",
            name="uq_index_provider",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    index_id: Mapped[int] = mapped_column(
        ForeignKey("index_master.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    provider_name: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    provider_symbol: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    exchange_segment: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    instrument_token: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    index: Mapped["Index"] = relationship(
        back_populates="provider_mappings",
    )
