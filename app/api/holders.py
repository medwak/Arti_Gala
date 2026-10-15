from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..connectors import CONNECTORS
from ..models import Artifact, AuctionLot, Holder, LegalCase
from ..regions import countries_by_region
from ..schemas import CountryInfo, HolderDetail, HolderIn, HolderKind, HolderOut, Page, SourceInfo, Stats
from ..services.ingest import get_or_create_holder
from .deps import get_db, paginate

router = APIRouter(tags=["holders"])


@router.get("/holders", response_model=Page[HolderOut])
def list_holders(
    q: str | None = None,
    kind: HolderKind | None = None,
    country: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """National museums, other museums, private collections, dealers, auction houses."""
    stmt = select(Holder)
    if q:
        stmt = stmt.where(Holder.name.ilike(f"%{q}%"))
    if kind:
        stmt = stmt.where(Holder.kind == kind)
    if country:
        stmt = stmt.where(Holder.country.ilike(f"%{country}%"))
    items, total = paginate(db, stmt.order_by(Holder.name), limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/holders", response_model=HolderOut, status_code=201)
def create_holder(body: HolderIn, db: Session = Depends(get_db)):
    holder = get_or_create_holder(db, body)
    db.commit()
    return holder


@router.get("/holders/{holder_id}", response_model=HolderDetail)
def get_holder(holder_id: int, db: Session = Depends(get_db)):
    holder = db.get(Holder, holder_id)
    if holder is None:
        raise HTTPException(404, f"holder {holder_id} not found")
    count = db.scalar(select(func.count()).where(Artifact.current_holder_id == holder_id))
    return HolderDetail.model_validate(holder).model_copy(update={"artifact_count": count})


@router.get("/countries", response_model=list[CountryInfo], tags=["artifacts"])
def list_countries(db: Session = Depends(get_db)):
    """All 49 sub-Saharan countries, grouped by region, with how many artifacts each has."""
    counts = dict(
        db.execute(select(Artifact.origin_country, func.count()).group_by(Artifact.origin_country)).all()
    )
    return [
        CountryInfo(country=country, region=region, artifact_count=counts.get(country, 0))
        for region, countries in countries_by_region().items()
        for country in countries
    ]


SOURCE_LABELS = {"manual": ("Added by hand / private collections", "Other")}


@router.get("/sources", response_model=list[SourceInfo], tags=["artifacts"])
def list_sources(db: Session = Depends(get_db)):
    """Every data source (museum APIs, scrapers, partners, manual entry) with its artifact count."""
    counts = dict(db.execute(select(Artifact.source, func.count()).group_by(Artifact.source)).all())
    sources = [
        SourceInfo(source=c.name, label=c.label, continent=c.continent, artifact_count=counts.pop(c.name, 0), syncable=True)
        for c in CONNECTORS.values()
    ]
    for source, count in sorted(counts.items()):
        label, continent = SOURCE_LABELS.get(source, (source.replace("scrape:", "Scraped: "), "Other"))
        sources.append(SourceInfo(source=source, label=label, continent=continent, artifact_count=count, syncable=False))
    return sources


def _grouped(db: Session, column, filter_=None, top: int = 20) -> dict[str, int]:
    stmt = select(column, func.count()).group_by(column).order_by(func.count().desc()).limit(top)
    if filter_ is not None:
        stmt = stmt.where(filter_)
    return {str(k or "unknown"): v for k, v in db.execute(stmt).all()}


@router.get("/stats", response_model=Stats, tags=["stats"])
def stats(db: Session = Depends(get_db)):
    by_kind_stmt = (
        select(Holder.kind, func.count(Artifact.id))
        .join(Artifact, Artifact.current_holder_id == Holder.id)
        .group_by(Holder.kind)
    )
    return Stats(
        artifacts=db.scalar(select(func.count(Artifact.id))),
        holders=db.scalar(select(func.count(Holder.id))),
        auctions=db.scalar(select(func.count(AuctionLot.id))),
        cases=db.scalar(select(func.count(LegalCase.id))),
        open_cases=db.scalar(select(func.count(LegalCase.id)).where(LegalCase.status.in_(("open", "pending")))),
        by_country=_grouped(db, Artifact.origin_country),
        by_region=_grouped(db, Artifact.origin_region),
        by_holder_kind={k: v for k, v in db.execute(by_kind_stmt).all()},
    )
