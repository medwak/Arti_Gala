"""Command line: run the server or sync a source without it.

    python -m app.cli serve --port 8000
    python -m app.cli sync met --query "Benin" --limit 20
    python -m app.cli scrape scrapers/example_auction_results.json --limit 50
"""

from __future__ import annotations

import argparse
import json
import logging
from functools import partial

from .config import Settings
from .connectors import CONNECTORS, HtmlScraper, ScrapeConfig
from .db import Base, make_engine, make_session_factory
from .models import SyncJob
from .services.sync import run_sync


def _run(settings: Settings, name: str, factory, query: str, limit: int) -> None:
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sessions = make_session_factory(engine)
    with sessions() as db:
        job = SyncJob(connector=name, query=query)
        db.add(job)
        db.commit()
        job_id = job.id
    # No event loop here, so WebSocket clients/webhooks are not notified for CLI runs.
    run_sync(sessions, settings, None, job_id, factory, query, limit)
    with sessions() as db:
        job = db.get(SyncJob, job_id)
        print(f"{name}: {job.status} fetched={job.fetched} created={job.created} "
              f"updated={job.updated} skipped={job.skipped}" + (f" error={job.error}" if job.error else ""))


def _lan_ip() -> str | None:
    """This computer's address on the local network (no packets are sent)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 80))
            return s.getsockname()[0]
        except OSError:
            return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="arti-gala")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API, dashboard and WebSocket server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sync = sub.add_parser("sync", help="pull artifacts from a museum API")
    sync.add_argument("connector", choices=sorted(CONNECTORS))
    sync.add_argument("--query", default="")
    sync.add_argument("--limit", type=int, default=25)

    scrape = sub.add_parser("scrape", help="run a scraper config (JSON file)")
    scrape.add_argument("config")
    scrape.add_argument("--query", default="")
    scrape.add_argument("--limit", type=int, default=100)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    if args.command == "serve":
        import uvicorn

        if args.host in ("0.0.0.0", "::"):
            ip = _lan_ip()
            if ip:
                print(f"\n  On your phone (same Wi-Fi), open or enter in the Arti Gala app:  http://{ip}:{args.port}\n")
        uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port)
    elif args.command == "sync":
        _run(settings, args.connector, CONNECTORS[args.connector], args.query, args.limit)
    else:
        with open(args.config, encoding="utf-8") as fh:
            config = ScrapeConfig.model_validate(json.load(fh))
        _run(settings, f"scrape:{config.name}", partial(HtmlScraper, config=config), args.query, args.limit)


if __name__ == "__main__":
    main()
