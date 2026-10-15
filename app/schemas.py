"""Pydantic models for API input/output and for connector output."""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

HolderKind = Literal[
    "national_museum",
    "public_museum",
    "university_museum",
    "private_collection",
    "auction_house",
    "dealer",
    "community",
    "unknown",
]
EventType = Literal[
    "created",
    "collected",
    "looted",
    "stolen",
    "acquired",
    "sold",
    "donated",
    "inherited",
    "loaned",
    "exhibited",
    "restituted",
    "recovered",
    "transferred",
]
AuctionStatus = Literal["upcoming", "sold", "unsold", "withdrawn", "unknown"]
CaseType = Literal[
    "restitution_claim",
    "repatriation",
    "litigation",
    "theft_investigation",
    "customs_seizure",
    "export_dispute",
    "other",
]
CaseStatus = Literal["open", "pending", "resolved", "returned", "dismissed", "unknown"]
Currency = str  # ISO 4217, validated by pattern where used

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------- holders


class HolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: HolderKind = "unknown"
    country: str | None = None
    city: str | None = None
    website: str | None = None


class HolderOut(ORM):
    id: int
    name: str
    kind: str
    country: str | None
    city: str | None
    website: str | None


class HolderDetail(HolderOut):
    artifact_count: int


# ---------------------------------------------------------------- provenance


class ProvenanceIn(BaseModel):
    event_type: EventType = "transferred"
    holder_name: str | None = None
    holder_kind: HolderKind | None = Field(
        default=None, description="If set together with holder_name, the holder is recorded as a Holder."
    )
    location: str | None = None
    date_text: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    description: str | None = None
    source: str | None = None
    sets_current_holder: bool = Field(
        default=False, description="Make this event's holder the artifact's current holder."
    )


class ProvenanceOut(ORM):
    id: int
    sequence: int
    event_type: str
    holder_name: str | None
    holder_id: int | None
    location: str | None
    date_text: str | None
    year_start: int | None
    year_end: int | None
    description: str | None
    source: str | None


# ---------------------------------------------------------------- auctions


class ArtifactRef(BaseModel):
    source: str
    source_id: str


class AuctionLotIn(BaseModel):
    source: str = "manual"
    source_id: str | None = None
    auction_house: str = Field(min_length=1, max_length=200)
    sale_title: str | None = None
    lot_number: str | None = None
    title: str | None = None
    culture: str | None = None
    sale_date: date | None = None
    sale_year: int | None = None
    location: str | None = None
    currency: Currency | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    estimate_low: float | None = Field(default=None, ge=0)
    estimate_high: float | None = Field(default=None, ge=0)
    hammer_price: float | None = Field(default=None, ge=0)
    premium_price: float | None = Field(default=None, ge=0, description="Price including buyer's premium")
    status: AuctionStatus = "unknown"
    url: str | None = None
    artifact_id: int | None = None
    artifact_ref: ArtifactRef | None = None


class AuctionLotOut(ORM):
    id: int
    source: str
    source_id: str
    artifact_id: int | None
    auction_house: str
    sale_title: str | None
    lot_number: str | None
    title: str | None
    culture: str | None
    sale_date: date | None
    sale_year: int | None
    location: str | None
    currency: str | None
    estimate_low: float | None
    estimate_high: float | None
    hammer_price: float | None
    premium_price: float | None
    status: str
    url: str | None


class LinkArtifact(BaseModel):
    artifact_id: int | None


class AuctionCandidate(BaseModel):
    artifact_id: int
    title: str
    culture: str | None
    score: float


class CurrencyStats(BaseModel):
    currency: str
    lots: int
    sold: int
    min_price: float | None
    max_price: float | None
    avg_price: float | None
    total_realized: float


class AuctionStats(BaseModel):
    total_lots: int
    by_status: dict[str, int]
    by_house: dict[str, int]
    by_currency: list[CurrencyStats]


# ---------------------------------------------------------------- cases


class CaseIn(BaseModel):
    source: str = "manual"
    source_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    case_type: CaseType = "other"
    status: CaseStatus = "open"
    claimant: str | None = None
    respondent: str | None = None
    jurisdiction: str | None = None
    filed_date: date | None = None
    resolved_date: date | None = None
    summary: str | None = None
    outcome: str | None = None
    url: str | None = None
    artifact_ids: list[int] = Field(default_factory=list)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)


class CasePatch(BaseModel):
    status: CaseStatus | None = None
    outcome: str | None = None
    resolved_date: date | None = None
    summary: str | None = None


class CaseOut(ORM):
    id: int
    source: str
    source_id: str
    title: str
    case_type: str
    status: str
    claimant: str | None
    respondent: str | None
    jurisdiction: str | None
    filed_date: date | None
    resolved_date: date | None
    summary: str | None
    outcome: str | None
    url: str | None
    artifact_ids: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------- artifacts


class ArtifactIn(BaseModel):
    source: str = "manual"
    source_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    object_type: str | None = None
    culture: str | None = None
    origin_country: str | None = None
    origin_region: str | None = None
    date_text: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    materials: str | None = None
    dimensions: str | None = None
    description: str | None = None
    history: str | None = None
    image_url: str | None = None
    source_url: str | None = None
    holder: HolderIn | None = None
    holder_id: int | None = None
    provenance: list[ProvenanceIn] | None = Field(
        default=None, description="When given, replaces the stored provenance timeline."
    )
    auctions: list[AuctionLotIn] = Field(default_factory=list)


class ArtifactPatch(BaseModel):
    title: str | None = None
    object_type: str | None = None
    culture: str | None = None
    origin_country: str | None = None
    origin_region: str | None = None
    date_text: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    materials: str | None = None
    dimensions: str | None = None
    description: str | None = None
    history: str | None = None
    image_url: str | None = None
    source_url: str | None = None
    holder_id: int | None = None


class ArtifactSummary(ORM):
    id: int
    source: str
    source_id: str
    title: str
    object_type: str | None
    culture: str | None
    origin_country: str | None
    origin_region: str | None
    date_text: str | None
    year_start: int | None
    year_end: int | None
    image_url: str | None
    current_holder: HolderOut | None
    auction_count: int = 0
    case_count: int = 0


class ArtifactDetail(ArtifactSummary):
    materials: str | None
    dimensions: str | None
    description: str | None
    history: str | None
    source_url: str | None
    created_at: datetime
    updated_at: datetime
    provenance: list[ProvenanceOut]
    auctions: list[AuctionLotOut]
    cases: list[CaseOut]


class Origin(BaseModel):
    culture: str | None
    country: str | None
    region: str | None
    date_text: str | None
    year_start: int | None
    year_end: int | None


class ArtifactHistory(BaseModel):
    artifact_id: int
    title: str
    origin: Origin
    narrative: str | None
    timeline: list[str]
    events: list[ProvenanceOut]


class JourneyStop(BaseModel):
    sequence: int
    event_type: str
    holder: str | None
    location: str | None
    when: str | None


class ArtifactJourney(BaseModel):
    artifact_id: int
    origin: str | None
    current_holder: HolderOut | None
    stops: list[JourneyStop]
    locations: list[str]


# ---------------------------------------------------------------- webhooks


class WebhookSubscriptionIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    events: list[str] = Field(default_factory=lambda: ["*"])
    secret: str | None = Field(default=None, min_length=16, max_length=200)
    description: str | None = None


class WebhookSubscriptionOut(ORM):
    id: int
    url: str
    events: list[str]
    description: str | None
    active: bool
    created_at: datetime


class WebhookSubscriptionCreated(WebhookSubscriptionOut):
    secret: str


class WebhookDeliveryOut(ORM):
    id: int
    subscription_id: int
    delivery_id: str
    event: str
    attempts: int
    status_code: int | None
    success: bool
    error: str | None
    created_at: datetime


class InboundEvent(BaseModel):
    type: Literal["artifact", "auction", "case", "provenance"]
    data: dict
    artifact_ref: ArtifactRef | None = Field(default=None, description="Target artifact for type=provenance")


# ---------------------------------------------------------------- sync


class SyncRequest(BaseModel):
    query: str = ""
    limit: int = Field(default=25, ge=1, le=500)


class SyncJobOut(ORM):
    id: int
    connector: str
    query: str | None
    status: str
    fetched: int
    created: int
    updated: int
    skipped: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class Stats(BaseModel):
    artifacts: int
    holders: int
    auctions: int
    cases: int
    open_cases: int
    by_country: dict[str, int]
    by_region: dict[str, int]
    by_holder_kind: dict[str, int]
