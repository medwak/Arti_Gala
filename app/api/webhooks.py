from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WebhookDelivery, WebhookSubscription
from ..schemas import (
    ArtifactIn,
    AuctionLotIn,
    CaseIn,
    InboundEvent,
    ProvenanceIn,
    WebhookDeliveryOut,
    WebhookSubscriptionCreated,
    WebhookSubscriptionIn,
    WebhookSubscriptionOut,
)
from ..services.events import EventBus
from ..services.ingest import Outcome, add_provenance_event, find_artifact, upsert_artifact, upsert_auction, upsert_case
from ..services.webhooks import SIGNATURE_HEADER, validate_target_url, verify
from .deps import commit_and_publish, get_bus, get_db

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

EVENT_TYPES = [
    "artifact.created", "artifact.updated", "provenance.added", "auction.created", "auction.updated",
    "case.created", "case.updated", "sync.finished", "webhook.test",
]


@router.get("/events", response_model=list[str])
def list_event_types():
    """Event names you can subscribe to. Patterns like "auction.*" or "*" also work."""
    return EVENT_TYPES


@router.post("/subscriptions", response_model=WebhookSubscriptionCreated, status_code=201)
def create_subscription(body: WebhookSubscriptionIn, request: Request, db: Session = Depends(get_db)):
    """Get an HTTP POST for every matching event. Deliveries are signed with
    `X-ArtiGala-Signature: sha256=HMAC(secret, body)`; the secret is only shown here."""
    try:
        validate_target_url(body.url, request.app.state.settings.allow_private_webhook_targets)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    sub = WebhookSubscription(
        url=body.url,
        events=body.events or ["*"],
        secret=body.secret or secrets.token_hex(24),
        description=body.description,
    )
    db.add(sub)
    db.commit()
    return WebhookSubscriptionCreated.model_validate(sub)


@router.get("/subscriptions", response_model=list[WebhookSubscriptionOut])
def list_subscriptions(db: Session = Depends(get_db)):
    return db.scalars(select(WebhookSubscription).order_by(WebhookSubscription.id)).all()


@router.delete("/subscriptions/{sub_id}", status_code=204)
def delete_subscription(sub_id: int, db: Session = Depends(get_db)):
    sub = db.get(WebhookSubscription, sub_id)
    if sub is None:
        raise HTTPException(404, f"subscription {sub_id} not found")
    db.delete(sub)
    db.commit()


@router.get("/subscriptions/{sub_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(sub_id: int, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = (
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == sub_id)
        .order_by(WebhookDelivery.id.desc())
        .limit(limit)
    )
    return db.scalars(stmt).all()


@router.post("/subscriptions/{sub_id}/test", status_code=202)
async def test_subscription(sub_id: int, request: Request, db: Session = Depends(get_db)):
    sub = db.get(WebhookSubscription, sub_id)
    if sub is None:
        raise HTTPException(404, f"subscription {sub_id} not found")
    dispatcher = request.app.state.bus.dispatcher
    message = {"event": "webhook.test", "data": {"subscription_id": sub.id}, "ts": None}
    ok = await dispatcher.deliver(sub.id, sub.url, sub.secret, message)
    return {"delivered": ok}


@router.post("/inbound", status_code=202)
async def inbound(
    request: Request,
    signature: str | None = Header(None, alias=SIGNATURE_HEADER),
    db: Session = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    """Partners (museums, registries, auction houses) push records here.

    Body: `{"type": "artifact"|"auction"|"case"|"provenance", "data": {...}}`, signed with
    the shared ARTI_INBOUND_WEBHOOK_SECRET in the `X-ArtiGala-Signature` header.
    """
    secret = request.app.state.settings.inbound_webhook_secret
    if not secret:
        raise HTTPException(503, "inbound webhooks are disabled: set ARTI_INBOUND_WEBHOOK_SECRET")
    body = await request.body()
    if not verify(secret, body, signature):
        raise HTTPException(401, "invalid signature")
    try:
        event = InboundEvent.model_validate(json.loads(body))
        outcome = Outcome()
        if event.type == "artifact":
            record = upsert_artifact(db, ArtifactIn.model_validate(event.data), outcome)
        elif event.type == "auction":
            record = upsert_auction(db, AuctionLotIn.model_validate(event.data), outcome)
        elif event.type == "case":
            record = upsert_case(db, CaseIn.model_validate(event.data), outcome)
        else:
            if event.artifact_ref is None:
                raise HTTPException(422, "provenance events need artifact_ref")
            artifact = find_artifact(db, event.artifact_ref)
            if artifact is None:
                raise HTTPException(404, "artifact_ref not found")
            record = add_provenance_event(db, artifact, ProvenanceIn.model_validate(event.data), outcome)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    commit_and_publish(db, bus, outcome)
    return {"accepted": True, "type": event.type, "id": record.id, "events": [name for name, _ in outcome.events]}
