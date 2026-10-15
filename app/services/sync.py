"""Run a connector and store what it returns, recording progress on a SyncJob."""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
from sqlalchemy.orm import sessionmaker

from ..config import Settings
from ..connectors.base import Connector
from ..models import SyncJob, utcnow
from ..schemas import ArtifactIn
from .events import EventBus
from .ingest import NotFound, NotSubSaharan, Outcome, upsert_artifact, upsert_auction

log = logging.getLogger(__name__)

ConnectorFactory = Callable[[httpx.Client, Settings], Connector]


def make_http_client(settings: Settings, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        transport=transport,
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent, "Accept": "application/json, text/html;q=0.9"},
    )


def run_sync(
    session_factory: sessionmaker,
    settings: Settings,
    bus: EventBus | None,
    job_id: int,
    factory: ConnectorFactory,
    query: str,
    limit: int,
    transport: httpx.BaseTransport | None = None,
) -> None:
    with session_factory() as db:
        job = db.get(SyncJob, job_id)
        job.status = "running"
        job.started_at = utcnow()
        db.commit()
        try:
            with make_http_client(settings, transport) as client:
                connector = factory(client, settings)
                for record in connector.fetch(query, limit):
                    job.fetched += 1
                    outcome = Outcome()
                    try:
                        if isinstance(record, ArtifactIn):
                            upsert_artifact(db, record, outcome)
                        else:
                            upsert_auction(db, record, outcome)
                        db.commit()
                    except (NotSubSaharan, NotFound) as exc:
                        db.rollback()
                        job = db.get(SyncJob, job_id)
                        job.skipped += 1
                        log.info("skipped record: %s", exc)
                        continue
                    job.created += outcome.created
                    job.updated += outcome.updated
                    if outcome.created == 0 and outcome.updated == 0:
                        job.skipped += 1
                    db.commit()
                    if bus is not None:
                        bus.emit_all(outcome.events)
            job.status = "succeeded"
        except Exception as exc:  # report any connector failure on the job
            db.rollback()
            job = db.get(SyncJob, job_id)
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            log.exception("sync job %s failed", job_id)
        job.finished_at = utcnow()
        db.commit()
        if bus is not None:
            bus.emit(
                "sync.finished",
                {
                    "job_id": job.id, "connector": job.connector, "status": job.status,
                    "created": job.created, "updated": job.updated, "skipped": job.skipped, "error": job.error,
                },
            )
