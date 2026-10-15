"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import artifacts, auctions, cases, holders, realtime, sync, webhooks
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .services.events import EventBus
from .services.ingest import NotFound, NotSubSaharan
from .services.webhooks import WebhookDispatcher

STATIC = Path(__file__).parent / "static"


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx.BaseTransport | None = None,
    webhook_transport: httpx.AsyncBaseTransport | None = None,
    webhook_backoff: float = 1.0,
) -> FastAPI:
    """Build the app. The transports let tests replace real HTTP calls."""
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    bus = EventBus()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        bus.bind(asyncio.get_running_loop())
        bus.dispatcher = WebhookDispatcher(
            session_factory,
            transport=webhook_transport,
            max_attempts=settings.webhook_max_attempts,
            timeout=settings.webhook_timeout_seconds,
            allow_private=settings.allow_private_webhook_targets,
            backoff_base=webhook_backoff,
            user_agent=settings.user_agent,
        )
        yield
        bus.unbind()
        await bus.dispatcher.aclose()

    app = FastAPI(
        title="Arti Gala",
        version="0.1.0",
        description=(
            "Search sub-Saharan African artifacts held by national museums and private collections, "
            "follow where each object has been, its auction sales and prices, and the legal / restitution "
            "cases around it."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.bus = bus
    app.state.http_transport = http_transport

    @app.exception_handler(NotSubSaharan)
    async def _out_of_scope(_: Request, exc: NotSubSaharan):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    for module in (artifacts, auctions, cases, holders, webhooks, sync, realtime):
        app.include_router(module.router)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "websocket_clients": bus.websockets.count}

    return app
