"""Create/update records from any source (API connectors, scrapers, webhooks, manual entry).

Every function records the events it produces on an ``Outcome`` instead of
publishing them, so callers publish only after the transaction commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Artifact, AuctionLot, Holder, LegalCase, ProvenanceEvent
from ..regions import classify
from ..schemas import ArtifactIn, ArtifactRef, AuctionLotIn, CaseIn, HolderIn, ProvenanceIn


class NotSubSaharan(ValueError):
    """The record could not be placed in sub-Saharan Africa, so it is out of scope."""


class NotFound(LookupError):
    pass


@dataclass
class Outcome:
    events: list[tuple[str, dict]] = field(default_factory=list)
    created: int = 0
    updated: int = 0

    def emit(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))


ARTIFACT_FIELDS = (
    "title", "object_type", "culture", "origin_country", "origin_region", "date_text", "year_start",
    "year_end", "materials", "dimensions", "description", "history", "image_url", "source_url",
)
AUCTION_FIELDS = (
    "auction_house", "sale_title", "lot_number", "title", "culture", "sale_date", "sale_year", "location",
    "currency", "estimate_low", "estimate_high", "hammer_price", "premium_price", "status", "url",
)
CASE_FIELDS = (
    "title", "case_type", "status", "claimant", "respondent", "jurisdiction", "filed_date",
    "resolved_date", "summary", "outcome", "url",
)


def artifact_brief(a: Artifact) -> dict:
    return {
        "id": a.id, "source": a.source, "source_id": a.source_id, "title": a.title,
        "culture": a.culture, "origin_country": a.origin_country, "origin_region": a.origin_region,
        "object_type": a.object_type,
        "current_holder": a.current_holder.name if a.current_holder else None,
    }


def auction_brief(lot: AuctionLot) -> dict:
    return {
        "id": lot.id, "artifact_id": lot.artifact_id, "auction_house": lot.auction_house,
        "title": lot.title, "lot_number": lot.lot_number,
        "sale_date": lot.sale_date.isoformat() if lot.sale_date else None, "sale_year": lot.sale_year,
        "status": lot.status, "currency": lot.currency, "estimate_low": lot.estimate_low,
        "estimate_high": lot.estimate_high, "hammer_price": lot.hammer_price,
        "premium_price": lot.premium_price, "url": lot.url,
    }


def case_brief(c: LegalCase) -> dict:
    return {
        "id": c.id, "title": c.title, "case_type": c.case_type, "status": c.status,
        "jurisdiction": c.jurisdiction, "artifact_ids": [a.id for a in c.artifacts],
    }


def _apply(obj, values: dict) -> bool:
    changed = False
    for key, value in values.items():
        if value is not None and getattr(obj, key) != value:
            setattr(obj, key, value)
            changed = True
    return changed


def get_or_create_holder(db: Session, data: HolderIn) -> Holder:
    holder = db.scalar(select(Holder).where(Holder.name == data.name, Holder.kind == data.kind))
    if holder is None:
        holder = Holder(**data.model_dump())
        db.add(holder)
        db.flush()
    else:
        for key in ("country", "city", "website"):
            if getattr(holder, key) is None and getattr(data, key):
                setattr(holder, key, getattr(data, key))
    return holder


def find_artifact(db: Session, ref: ArtifactRef) -> Artifact | None:
    return db.scalar(select(Artifact).where(Artifact.source == ref.source, Artifact.source_id == ref.source_id))


def _provenance_row(db: Session, data: ProvenanceIn, sequence: int) -> ProvenanceEvent:
    holder = None
    if data.holder_name and data.holder_kind:
        holder = get_or_create_holder(db, HolderIn(name=data.holder_name, kind=data.holder_kind))
    return ProvenanceEvent(
        sequence=sequence,
        event_type=data.event_type,
        holder_name=data.holder_name,
        holder=holder,
        location=data.location,
        date_text=data.date_text,
        year_start=data.year_start,
        year_end=data.year_end,
        description=data.description,
        source=data.source,
    )


def _provenance_key(rows) -> list[tuple]:
    return [(r.event_type, r.holder_name, r.location, r.date_text, r.year_start, r.description) for r in rows]


def upsert_artifact(db: Session, data: ArtifactIn, outcome: Outcome) -> Artifact:
    cls = classify(data.origin_country, data.culture, data.origin_region)
    if cls is None:
        raise NotSubSaharan(
            f"Cannot place {data.title!r} in sub-Saharan Africa: set origin_country or culture."
        )
    values = {f: getattr(data, f) for f in ARTIFACT_FIELDS}
    values["origin_country"] = cls.country or data.origin_country
    values["origin_region"] = cls.subregion

    artifact = None
    if data.source_id:
        artifact = find_artifact(db, ArtifactRef(source=data.source, source_id=data.source_id))
    created = artifact is None
    if created:
        artifact = Artifact(source=data.source, source_id=data.source_id or uuid.uuid4().hex)
        db.add(artifact)
    changed = _apply(artifact, values)

    if data.holder_id is not None:
        holder = db.get(Holder, data.holder_id)
        if holder is None:
            raise NotFound(f"holder {data.holder_id} not found")
    elif data.holder is not None:
        holder = get_or_create_holder(db, data.holder)
    else:
        holder = artifact.current_holder
    if holder is not artifact.current_holder:
        artifact.current_holder = holder
        changed = True

    if data.provenance is not None and _provenance_key(data.provenance) != _provenance_key(artifact.provenance):
        artifact.provenance.clear()
        db.flush()
        for i, item in enumerate(data.provenance):
            artifact.provenance.append(_provenance_row(db, item, i))
        changed = True
    db.flush()

    if created:
        outcome.created += 1
        outcome.emit("artifact.created", artifact_brief(artifact))
    elif changed:
        outcome.updated += 1
        outcome.emit("artifact.updated", artifact_brief(artifact))

    for lot in data.auctions:
        upsert_auction(db, lot.model_copy(update={"artifact_id": artifact.id, "artifact_ref": None}), outcome)
    return artifact


def add_provenance_event(db: Session, artifact: Artifact, data: ProvenanceIn, outcome: Outcome) -> ProvenanceEvent:
    sequence = (artifact.provenance[-1].sequence + 1) if artifact.provenance else 0
    row = _provenance_row(db, data, sequence)
    artifact.provenance.append(row)
    if data.sets_current_holder and data.holder_name:
        artifact.current_holder = row.holder or get_or_create_holder(
            db, HolderIn(name=data.holder_name, kind="unknown")
        )
    db.flush()
    outcome.emit(
        "provenance.added",
        {
            "artifact": artifact_brief(artifact),
            "event": {
                "id": row.id, "event_type": row.event_type, "holder_name": row.holder_name,
                "location": row.location, "date_text": row.date_text, "year_start": row.year_start,
            },
        },
    )
    return row


def upsert_auction(db: Session, data: AuctionLotIn, outcome: Outcome) -> AuctionLot:
    artifact = None
    if data.artifact_id is not None:
        artifact = db.get(Artifact, data.artifact_id)
        if artifact is None:
            raise NotFound(f"artifact {data.artifact_id} not found")
    elif data.artifact_ref is not None:
        artifact = find_artifact(db, data.artifact_ref)
    if artifact is None and classify(data.culture, data.title) is None:
        raise NotSubSaharan(f"Lot {data.title!r} is not linked to an artifact and its culture/title is not sub-Saharan")

    values = {f: getattr(data, f) for f in AUCTION_FIELDS}
    if values["sale_year"] is None and data.sale_date:
        values["sale_year"] = data.sale_date.year
    if data.status == "unknown":
        values["status"] = None  # don't overwrite a known status with "unknown"

    lot = None
    if data.source_id:
        lot = db.scalar(select(AuctionLot).where(AuctionLot.source == data.source, AuctionLot.source_id == data.source_id))
    created = lot is None
    if created:
        lot = AuctionLot(source=data.source, source_id=data.source_id or uuid.uuid4().hex, status="unknown")
        db.add(lot)
    changed = _apply(lot, values)
    if artifact is not None and lot.artifact_id != artifact.id:
        lot.artifact = artifact
        changed = True
    db.flush()

    if created:
        outcome.created += 1
        outcome.emit("auction.created", auction_brief(lot))
    elif changed:
        outcome.updated += 1
        outcome.emit("auction.updated", auction_brief(lot))
    return lot


def upsert_case(db: Session, data: CaseIn, outcome: Outcome) -> LegalCase:
    artifacts = []
    for artifact_id in data.artifact_ids:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            raise NotFound(f"artifact {artifact_id} not found")
        artifacts.append(artifact)
    for ref in data.artifact_refs:
        artifact = find_artifact(db, ref)
        if artifact is None:
            raise NotFound(f"artifact {ref.source}/{ref.source_id} not found")
        artifacts.append(artifact)

    case = None
    if data.source_id:
        case = db.scalar(select(LegalCase).where(LegalCase.source == data.source, LegalCase.source_id == data.source_id))
    created = case is None
    if created:
        case = LegalCase(source=data.source, source_id=data.source_id or uuid.uuid4().hex)
        db.add(case)
    changed = _apply(case, {f: getattr(data, f) for f in CASE_FIELDS})
    for artifact in artifacts:
        if artifact not in case.artifacts:
            case.artifacts.append(artifact)
            changed = True
    db.flush()

    if created:
        outcome.created += 1
        outcome.emit("case.created", case_brief(case))
    elif changed:
        outcome.updated += 1
        outcome.emit("case.updated", case_brief(case))
    return case
