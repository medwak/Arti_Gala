from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import Artifact, Holder
from ..schemas import (
    ArtifactDetail,
    ArtifactHistory,
    ArtifactIn,
    ArtifactJourney,
    ArtifactPatch,
    ArtifactSummary,
    AuctionLotOut,
    CaseOut,
    HolderOut,
    JourneyStop,
    Origin,
    Page,
    ProvenanceIn,
    ProvenanceOut,
)
from ..services.events import EventBus
from ..services.ingest import Outcome, add_provenance_event, artifact_brief, upsert_artifact
from ..services.provenance import compose_timeline
from .deps import artifact_detail, artifact_summary, case_out, commit_and_publish, get_bus, get_db, paginate

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

_LOAD = (
    selectinload(Artifact.current_holder),
    selectinload(Artifact.auctions),
    selectinload(Artifact.cases),
)


def _get(db: Session, artifact_id: int) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, f"artifact {artifact_id} not found")
    return artifact


@router.get("", response_model=Page[ArtifactSummary])
def search_artifacts(
    q: str | None = Query(None, description="Free text over title, culture, materials, description, history"),
    country: str | None = None,
    region: str | None = Query(None, description="West/Central/East/Southern Africa"),
    culture: str | None = None,
    object_type: str | None = Query(None, description="e.g. painting, mask, ornament, sculpture"),
    holder_kind: str | None = Query(None, description="national_museum, private_collection, ..."),
    holder_id: int | None = None,
    source: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    has_auctions: bool | None = None,
    has_cases: bool | None = None,
    sort: Literal["title", "year", "updated"] = "updated",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Artifact).options(*_LOAD)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Artifact.title.ilike(like), Artifact.culture.ilike(like), Artifact.materials.ilike(like),
                Artifact.description.ilike(like), Artifact.history.ilike(like), Artifact.object_type.ilike(like),
            )
        )
    if country:
        stmt = stmt.where(Artifact.origin_country.ilike(f"%{country}%"))
    if region:
        stmt = stmt.where(Artifact.origin_region.ilike(f"%{region}%"))
    if culture:
        stmt = stmt.where(Artifact.culture.ilike(f"%{culture}%"))
    if object_type:
        stmt = stmt.where(or_(Artifact.object_type.ilike(f"%{object_type}%"), Artifact.title.ilike(f"%{object_type}%")))
    if holder_kind:
        stmt = stmt.join(Holder, Artifact.current_holder).where(Holder.kind == holder_kind)
    if holder_id is not None:
        stmt = stmt.where(Artifact.current_holder_id == holder_id)
    if source:
        stmt = stmt.where(Artifact.source == source)
    if year_from is not None:
        stmt = stmt.where(or_(Artifact.year_end >= year_from, Artifact.year_start >= year_from))
    if year_to is not None:
        stmt = stmt.where(Artifact.year_start <= year_to)
    if has_auctions is not None:
        stmt = stmt.where(Artifact.auctions.any() if has_auctions else ~Artifact.auctions.any())
    if has_cases is not None:
        stmt = stmt.where(Artifact.cases.any() if has_cases else ~Artifact.cases.any())
    order = {
        "title": Artifact.title.asc(),
        "year": Artifact.year_start.asc(),
        "updated": Artifact.updated_at.desc(),
    }[sort]
    items, total = paginate(db, stmt.order_by(order, Artifact.id), limit, offset)
    return Page(items=[artifact_summary(a) for a in items], total=total, limit=limit, offset=offset)


@router.post("", response_model=ArtifactDetail, status_code=201)
def create_artifact(body: ArtifactIn, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    """Register an artifact, e.g. one held in a personal collection. Upserts on (source, source_id)."""
    outcome = Outcome()
    artifact = upsert_artifact(db, body, outcome)
    commit_and_publish(db, bus, outcome)
    db.refresh(artifact)
    return artifact_detail(artifact)


@router.get("/{artifact_id}", response_model=ArtifactDetail)
def get_artifact(artifact_id: int, db: Session = Depends(get_db)):
    return artifact_detail(_get(db, artifact_id))


@router.patch("/{artifact_id}", response_model=ArtifactDetail)
def update_artifact(
    artifact_id: int, body: ArtifactPatch, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)
):
    artifact = _get(db, artifact_id)
    changes = body.model_dump(exclude_unset=True)
    if "holder_id" in changes and changes["holder_id"] is not None and db.get(Holder, changes["holder_id"]) is None:
        raise HTTPException(404, f"holder {changes['holder_id']} not found")
    for key, value in changes.items():
        if key == "holder_id":
            artifact.current_holder_id = value
        else:
            setattr(artifact, key, value)
    outcome = Outcome()
    db.flush()
    db.refresh(artifact)
    outcome.emit("artifact.updated", artifact_brief(artifact))
    commit_and_publish(db, bus, outcome)
    return artifact_detail(artifact)


@router.get("/{artifact_id}/provenance", response_model=list[ProvenanceOut])
def get_provenance(artifact_id: int, db: Session = Depends(get_db)):
    return _get(db, artifact_id).provenance


@router.post("/{artifact_id}/provenance", response_model=ProvenanceOut, status_code=201)
def add_provenance(
    artifact_id: int, body: ProvenanceIn, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)
):
    """Record a new movement (sale, loan, restitution, ...) of the artifact."""
    artifact = _get(db, artifact_id)
    outcome = Outcome()
    row = add_provenance_event(db, artifact, body, outcome)
    commit_and_publish(db, bus, outcome)
    return row


@router.get("/{artifact_id}/journey", response_model=ArtifactJourney)
def get_journey(artifact_id: int, db: Session = Depends(get_db)):
    """Where the artifact has been: each holder and location in order."""
    artifact = _get(db, artifact_id)
    stops = [
        JourneyStop(
            sequence=e.sequence,
            event_type=e.event_type,
            holder=e.holder_name,
            location=e.location,
            when=e.date_text or (str(e.year_start) if e.year_start else None),
        )
        for e in artifact.provenance
    ]
    locations: list[str] = []
    origin = ", ".join(p for p in (artifact.culture, artifact.origin_country) if p) or None
    for loc in [artifact.origin_country] + [s.location for s in stops]:
        if loc and (not locations or locations[-1] != loc):
            locations.append(loc)
    holder = artifact.current_holder
    if holder and holder.city and (not locations or locations[-1] != holder.city):
        locations.append(holder.city)
    return ArtifactJourney(
        artifact_id=artifact.id,
        origin=origin,
        current_holder=HolderOut.model_validate(holder) if holder else None,
        stops=stops,
        locations=locations,
    )


@router.get("/{artifact_id}/history", response_model=ArtifactHistory)
def get_history(artifact_id: int, db: Session = Depends(get_db)):
    """Origin of the artifact plus its full documented history."""
    artifact = _get(db, artifact_id)
    return ArtifactHistory(
        artifact_id=artifact.id,
        title=artifact.title,
        origin=Origin(
            culture=artifact.culture,
            country=artifact.origin_country,
            region=artifact.origin_region,
            date_text=artifact.date_text,
            year_start=artifact.year_start,
            year_end=artifact.year_end,
        ),
        narrative=artifact.history,
        timeline=compose_timeline(artifact.provenance),
        events=[ProvenanceOut.model_validate(e) for e in artifact.provenance],
    )


@router.get("/{artifact_id}/auctions", response_model=list[AuctionLotOut])
def get_artifact_auctions(artifact_id: int, db: Session = Depends(get_db)):
    return sorted(_get(db, artifact_id).auctions, key=lambda lot: (lot.sale_year or 0, lot.id))


@router.get("/{artifact_id}/cases", response_model=list[CaseOut])
def get_artifact_cases(artifact_id: int, db: Session = Depends(get_db)):
    return [case_out(c) for c in _get(db, artifact_id).cases]
