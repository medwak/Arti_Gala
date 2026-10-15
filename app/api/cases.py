from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import Artifact, LegalCase
from ..schemas import CaseIn, CaseOut, CasePatch, CaseStatus, CaseType, Page
from ..services.events import EventBus
from ..services.ingest import Outcome, case_brief, upsert_case
from .deps import case_out, commit_and_publish, get_bus, get_db, paginate

router = APIRouter(prefix="/cases", tags=["cases"])


def _get(db: Session, case_id: int) -> LegalCase:
    case = db.get(LegalCase, case_id)
    if case is None:
        raise HTTPException(404, f"case {case_id} not found")
    return case


@router.get("", response_model=Page[CaseOut])
def list_cases(
    q: str | None = None,
    status: CaseStatus | None = None,
    case_type: CaseType | None = None,
    jurisdiction: str | None = None,
    artifact_id: int | None = None,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Restitution claims, lawsuits, seizures and investigations involving artifacts."""
    stmt = select(LegalCase).options(selectinload(LegalCase.artifacts))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(LegalCase.title.ilike(like), LegalCase.summary.ilike(like), LegalCase.claimant.ilike(like),
                LegalCase.respondent.ilike(like))
        )
    if status:
        stmt = stmt.where(LegalCase.status == status)
    if case_type:
        stmt = stmt.where(LegalCase.case_type == case_type)
    if jurisdiction:
        stmt = stmt.where(LegalCase.jurisdiction.ilike(f"%{jurisdiction}%"))
    if artifact_id is not None:
        stmt = stmt.where(LegalCase.artifacts.any(Artifact.id == artifact_id))
    items, total = paginate(db, stmt.order_by(LegalCase.updated_at.desc(), LegalCase.id.desc()), limit, offset)
    return Page(items=[case_out(c) for c in items], total=total, limit=limit, offset=offset)


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseIn, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    outcome = Outcome()
    case = upsert_case(db, body, outcome)
    commit_and_publish(db, bus, outcome)
    return case_out(case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, db: Session = Depends(get_db)):
    return case_out(_get(db, case_id))


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(case_id: int, body: CasePatch, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    case = _get(db, case_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(case, key, value)
    db.flush()
    outcome = Outcome()
    outcome.emit("case.updated", case_brief(case))
    commit_and_publish(db, bus, outcome)
    return case_out(case)


@router.put("/{case_id}/artifacts/{artifact_id}", response_model=CaseOut)
def link_case_artifact(case_id: int, artifact_id: int, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    case = _get(db, case_id)
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, f"artifact {artifact_id} not found")
    if artifact not in case.artifacts:
        case.artifacts.append(artifact)
        db.flush()
        outcome = Outcome()
        outcome.emit("case.updated", case_brief(case))
        commit_and_publish(db, bus, outcome)
    return case_out(case)
