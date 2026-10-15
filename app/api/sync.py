from __future__ import annotations

from functools import partial

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..connectors import CONNECTORS, HtmlScraper, ScrapeConfig
from ..models import SyncJob
from ..regions import canonical_country
from ..schemas import ConnectorInfo, SyncJobOut, SyncRequest
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


def _query(body: SyncRequest) -> str:
    """Combine the free-text query with the chosen country (a bare country searches by place)."""
    if body.country is None:
        return body.query
    country = canonical_country(body.country)
    if country is None:
        raise HTTPException(422, f"{body.country!r} is not a sub-Saharan African country; see GET /countries")
    return f"{body.query} {country}".strip() if body.query else country


@router.get("/connectors", response_model=list[ConnectorInfo])
def list_connectors(request: Request):
    """Museum APIs that can be synced, grouped by continent (Europe first)."""
    settings = request.app.state.settings
    return [
        ConnectorInfo(
            name=c.name, label=c.label, description=c.description, continent=c.continent,
            available=c.missing_key(settings) is None, needs=c.missing_key(settings),
        )
        for c in CONNECTORS.values()
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


@router.post("/all", response_model=list[SyncJobOut], status_code=202)
def start_sync_all(body: SyncRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Search every available source at once (one job per source). Sources missing an API key are skipped."""
    query = _query(body)
    settings = request.app.state.settings
    return [
        _start(request, background, db, name, factory, query, body.limit)
        for name, factory in CONNECTORS.items()
        if factory.missing_key(settings) is None
    ]


@router.post("/{connector}", response_model=SyncJobOut, status_code=202)
def start_sync(
    connector: str, body: SyncRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """Pull sub-Saharan objects from one museum API in the background."""
    factory = CONNECTORS.get(connector)
    if factory is None:
        raise HTTPException(404, f"unknown connector {connector!r}; see GET /sync/connectors")
    missing = factory.missing_key(request.app.state.settings)
    if missing:
        raise HTTPException(422, f"{factory.label} needs an API key: set {missing} and restart the server")
    return _start(request, background, db, connector, factory, _query(body), body.limit)


@router.get("/jobs", response_model=list[SyncJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(SyncJob).order_by(SyncJob.id.desc()).limit(50)).all()


@router.get("/jobs/{job_id}", response_model=SyncJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return job
