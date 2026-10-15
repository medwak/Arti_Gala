"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


case_artifacts = Table(
    "case_artifacts",
    Base.metadata,
    Column("case_id", ForeignKey("legal_cases.id", ondelete="CASCADE"), primary_key=True),
    Column("artifact_id", ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True),
)


class Holder(Base):
    """A museum, private collection, dealer, etc. that holds or held artifacts."""

    __tablename__ = "holders"
    __table_args__ = (UniqueConstraint("name", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    kind: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    country: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(500))

    artifacts: Mapped[list[Artifact]] = relationship(back_populates="current_holder")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    source_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500), index=True)
    object_type: Mapped[str | None] = mapped_column(String(200), index=True)
    culture: Mapped[str | None] = mapped_column(String(300), index=True)
    origin_country: Mapped[str | None] = mapped_column(String(100), index=True)
    origin_region: Mapped[str | None] = mapped_column(String(100), index=True)
    date_text: Mapped[str | None] = mapped_column(String(200))
    year_start: Mapped[int | None] = mapped_column(Integer, index=True)
    year_end: Mapped[int | None] = mapped_column(Integer)
    materials: Mapped[str | None] = mapped_column(String(500))
    dimensions: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    history: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(1000))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    current_holder_id: Mapped[int | None] = mapped_column(ForeignKey("holders.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    current_holder: Mapped[Holder | None] = relationship(back_populates="artifacts")
    provenance: Mapped[list[ProvenanceEvent]] = relationship(
        back_populates="artifact",
        order_by="ProvenanceEvent.sequence",
        cascade="all, delete-orphan",
    )
    auctions: Mapped[list[AuctionLot]] = relationship(back_populates="artifact")
    cases: Mapped[list[LegalCase]] = relationship(secondary=case_artifacts, back_populates="artifacts")


class ProvenanceEvent(Base):
    """One step in an artifact's journey: who held it, where, and when."""

    __tablename__ = "provenance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String(40), default="transferred")
    holder_name: Mapped[str | None] = mapped_column(String(300))
    holder_id: Mapped[int | None] = mapped_column(ForeignKey("holders.id"))
    location: Mapped[str | None] = mapped_column(String(200))
    date_text: Mapped[str | None] = mapped_column(String(200))
    year_start: Mapped[int | None] = mapped_column(Integer)
    year_end: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(200))

    artifact: Mapped[Artifact] = relationship(back_populates="provenance")
    holder: Mapped[Holder | None] = relationship()


class AuctionLot(Base):
    __tablename__ = "auction_lots"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(200))
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), index=True)
    auction_house: Mapped[str] = mapped_column(String(200), index=True)
    sale_title: Mapped[str | None] = mapped_column(String(500))
    lot_number: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(500))
    culture: Mapped[str | None] = mapped_column(String(300))
    sale_date: Mapped[date | None] = mapped_column(Date, index=True)
    sale_year: Mapped[int | None] = mapped_column(Integer, index=True)
    location: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str | None] = mapped_column(String(3))
    estimate_low: Mapped[float | None] = mapped_column(Float)
    estimate_high: Mapped[float | None] = mapped_column(Float)
    hammer_price: Mapped[float | None] = mapped_column(Float)
    premium_price: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    artifact: Mapped[Artifact | None] = relationship(back_populates="auctions")


class LegalCase(Base):
    """Restitution claims, litigation, seizures and other cases involving artifacts."""

    __tablename__ = "legal_cases"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    case_type: Mapped[str] = mapped_column(String(40), default="other", index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    claimant: Mapped[str | None] = mapped_column(String(300))
    respondent: Mapped[str | None] = mapped_column(String(300))
    jurisdiction: Mapped[str | None] = mapped_column(String(200), index=True)
    filed_date: Mapped[date | None] = mapped_column(Date)
    resolved_date: Mapped[date | None] = mapped_column(Date)
    summary: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    artifacts: Mapped[list[Artifact]] = relationship(secondary=case_artifacts, back_populates="cases")


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1000))
    secret: Mapped[str] = mapped_column(String(200))
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), index=True
    )
    delivery_id: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    connector: Mapped[str] = mapped_column(String(100))
    query: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
