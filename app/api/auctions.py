from __future__ import annotations

from difflib import SequenceMatcher
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Artifact, AuctionLot
from ..schemas import (
    AuctionCandidate,
    AuctionLotIn,
    AuctionLotOut,
    AuctionStats,
    AuctionStatus,
    CurrencyStats,
    LinkArtifact,
    Page,
)
from ..services.events import EventBus
from ..services.ingest import Outcome, auction_brief, upsert_auction
from .deps import commit_and_publish, get_bus, get_db, paginate

router = APIRouter(prefix="/auctions", tags=["auctions"])

_realized = func.coalesce(AuctionLot.premium_price, AuctionLot.hammer_price)


def _filtered(
    q: str | None = None,
    house: str | None = None,
    status: AuctionStatus | None = None,
    currency: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    artifact_id: int | None = None,
    linked: bool | None = None,
):
    stmt = select(AuctionLot)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuctionLot.title.ilike(like), AuctionLot.culture.ilike(like), AuctionLot.sale_title.ilike(like)))
    if house:
        stmt = stmt.where(AuctionLot.auction_house.ilike(f"%{house}%"))
    if status:
        stmt = stmt.where(AuctionLot.status == status)
    if currency:
        stmt = stmt.where(AuctionLot.currency == currency.upper())
    if min_price is not None:
        stmt = stmt.where(_realized >= min_price)
    if max_price is not None:
        stmt = stmt.where(_realized <= max_price)
    if year_from is not None:
        stmt = stmt.where(AuctionLot.sale_year >= year_from)
    if year_to is not None:
        stmt = stmt.where(AuctionLot.sale_year <= year_to)
    if artifact_id is not None:
        stmt = stmt.where(AuctionLot.artifact_id == artifact_id)
    if linked is not None:
        stmt = stmt.where(AuctionLot.artifact_id.is_not(None) if linked else AuctionLot.artifact_id.is_(None))
    return stmt


@router.get("", response_model=Page[AuctionLotOut])
def list_auctions(
    filtered=Depends(_filtered),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Auction lots with estimates and realized prices (price filters use premium price, else hammer)."""
    stmt = filtered.order_by(AuctionLot.sale_date.desc().nulls_last(), AuctionLot.sale_year.desc().nulls_last(), AuctionLot.id.desc())
    items, total = paginate(db, stmt, limit, offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=AuctionStats)
def auction_stats(filtered=Depends(_filtered), db: Session = Depends(get_db)):
    lots = db.scalars(filtered).all()
    by_status: dict[str, int] = {}
    by_house: dict[str, int] = {}
    by_currency: dict[str, list[AuctionLot]] = {}
    for lot in lots:
        by_status[lot.status] = by_status.get(lot.status, 0) + 1
        by_house[lot.auction_house] = by_house.get(lot.auction_house, 0) + 1
        if lot.currency:
            by_currency.setdefault(lot.currency, []).append(lot)
    currency_stats = []
    for code, group in sorted(by_currency.items()):
        prices = [p for p in ((lot.premium_price if lot.premium_price is not None else lot.hammer_price) for lot in group) if p is not None]
        currency_stats.append(
            CurrencyStats(
                currency=code,
                lots=len(group),
                sold=sum(1 for lot in group if lot.status == "sold"),
                min_price=min(prices) if prices else None,
                max_price=max(prices) if prices else None,
                avg_price=round(mean(prices), 2) if prices else None,
                total_realized=sum(prices),
            )
        )
    return AuctionStats(
        total_lots=len(lots),
        by_status=by_status,
        by_house=dict(sorted(by_house.items(), key=lambda kv: -kv[1])),
        by_currency=currency_stats,
    )


@router.post("", response_model=AuctionLotOut, status_code=201)
def create_auction(body: AuctionLotIn, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    outcome = Outcome()
    lot = upsert_auction(db, body, outcome)
    commit_and_publish(db, bus, outcome)
    return lot


def _get(db: Session, lot_id: int) -> AuctionLot:
    lot = db.get(AuctionLot, lot_id)
    if lot is None:
        raise HTTPException(404, f"auction lot {lot_id} not found")
    return lot


@router.get("/{lot_id}", response_model=AuctionLotOut)
def get_auction(lot_id: int, db: Session = Depends(get_db)):
    return _get(db, lot_id)


@router.put("/{lot_id}/artifact", response_model=AuctionLotOut)
def link_artifact(lot_id: int, body: LinkArtifact, db: Session = Depends(get_db), bus: EventBus = Depends(get_bus)):
    """Link (or unlink with null) an auction lot to the artifact that was sold."""
    lot = _get(db, lot_id)
    if body.artifact_id is not None and db.get(Artifact, body.artifact_id) is None:
        raise HTTPException(404, f"artifact {body.artifact_id} not found")
    lot.artifact_id = body.artifact_id
    db.flush()
    outcome = Outcome()
    outcome.emit("auction.updated", auction_brief(lot))
    commit_and_publish(db, bus, outcome)
    return lot


@router.get("/{lot_id}/candidates", response_model=list[AuctionCandidate])
def link_candidates(lot_id: int, limit: int = Query(5, ge=1, le=25), db: Session = Depends(get_db)):
    """Artifacts whose title/culture resemble this lot — to help link sales to objects."""
    lot = _get(db, lot_id)
    lot_text = f"{lot.title or ''} {lot.culture or ''}".lower().strip()
    if not lot_text:
        return []
    scored = []
    for artifact in db.scalars(select(Artifact)):
        text = f"{artifact.title} {artifact.culture or ''}".lower()
        score = SequenceMatcher(None, lot_text, text).ratio()
        scored.append(AuctionCandidate(artifact_id=artifact.id, title=artifact.title, culture=artifact.culture, score=round(score, 3)))
    scored.sort(key=lambda c: -c.score)
    return scored[:limit]
