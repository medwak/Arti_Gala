from __future__ import annotations

from functools import partial

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors import CONNECTORS, HtmlScraper, ScrapeConfig
from ..models import SyncJob
from ..schemas import SyncJobOut, SyncRequest
from ..services.sync import run_sync
from ..services.webhooks import validate_target_url
from .deps import get_db

router = APIRouter(prefix="/sync", tags=["sync"])


def _start(request: Request, background: BackgroundTasks, db: Session, name: str, factory, query: str, limit: int) -> SyncJob:
    job = SyncJob(connector=name, query=query, status="queued")
    db.add(job)
    db.commit()
    state = request.app.state
    background.add_task(
        run_sync, state.session_factory, state.settings, state.bus, job.id, factory, query, limit, state.http_transport
    )
    return job


@router.get("/connectors")
def list_connectors():
    """Data sources that can be synced through their public APIs."""
    return [{"name": c.name, "description": c.description} for c in CONNECTORS.values()] + [
        {"name": "scrape", "description": HtmlScraper.description}
    ]


@router.post("/scrape", response_model=SyncJobOut, status_code=202)
def start_scrape(
    config: ScrapeConfig,
    request: Request,
    background: BackgroundTasks,
    query: str = "",
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Scrape auction results or collection pages described by CSS selectors (see scrapers/*.json)."""
    for url in config.start_urls:
        try:
            validate_target_url(url, request.app.state.settings.allow_private_webhook_targets)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    factory = partial(HtmlScraper, config=config)
    return _start(request, background, db, f"scrape:{config.name}", factory, query, limit)


@router.post("/{connector}", response_model=SyncJobOut, status_code=202)
def start_sync(
    connector: str, body: SyncRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """Pull sub-Saharan objects from a museum API in the background."""
    factory = CONNECTORS.get(connector)
    if factory is None:
        raise HTTPException(404, f"unknown connector {connector!r}; see GET /sync/connectors")
    return _start(request, background, db, connector, factory, body.query, body.limit)


@router.get("/jobs", response_model=list[SyncJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(SyncJob).order_by(SyncJob.id.desc()).limit(50)).all()


@router.get("/jobs/{job_id}", response_model=SyncJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return job
