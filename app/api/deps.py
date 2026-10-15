from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Artifact, LegalCase
from ..schemas import ArtifactDetail, ArtifactSummary, CaseOut
from ..services.events import EventBus
from ..services.ingest import Outcome


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as db:
        yield db


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def commit_and_publish(db: Session, bus: EventBus, outcome: Outcome) -> None:
    db.commit()
    bus.emit_all(outcome.events)


def paginate(db: Session, stmt, limit: int, offset: int):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = db.scalars(stmt.limit(limit).offset(offset)).unique().all()
    return items, total


def case_out(case: LegalCase) -> CaseOut:
    return CaseOut.model_validate(case).model_copy(update={"artifact_ids": [a.id for a in case.artifacts]})


def artifact_summary(a: Artifact) -> ArtifactSummary:
    return ArtifactSummary.model_validate(a).model_copy(
        update={"auction_count": len(a.auctions), "case_count": len(a.cases)}
    )


def artifact_detail(a: Artifact) -> ArtifactDetail:
    detail = ArtifactDetail.model_validate(
        {
            **{k: getattr(a, k) for k in ArtifactDetail.model_fields if k not in ("cases", "auction_count", "case_count")},
            "cases": [case_out(c) for c in a.cases],
        },
        from_attributes=True,
    )
    return detail.model_copy(update={"auction_count": len(a.auctions), "case_count": len(a.cases)})
