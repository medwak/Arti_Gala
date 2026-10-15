from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

INBOUND_SECRET = "test-inbound-secret-0123456789"


class Recorder:
    """Async transport that records outbound webhook calls."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)

    def wait_for(self, count: int, timeout: float = 3.0) -> list[httpx.Request]:
        deadline = time.monotonic() + timeout
        while len(self.requests) < count and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.requests


def json_routes(routes: dict[str, object]):
    """Sync MockTransport handler serving JSON/text by URL prefix (longest prefix wins)."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix in sorted(routes, key=len, reverse=True):
            if url.startswith(prefix):
                body = routes[prefix]
                if callable(body):
                    body = body(request)
                if isinstance(body, httpx.Response):
                    return body
                if isinstance(body, str):
                    return httpx.Response(200, text=body)
                return httpx.Response(200, content=json.dumps(body), headers={"Content-Type": "application/json"})
        return httpx.Response(404, text="not found")

    return handler


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite://",
        inbound_webhook_secret=INBOUND_SECRET,
        allow_private_webhook_targets=True,
        scrape_delay_seconds=0,
        webhook_max_attempts=2,
    )


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def http_routes() -> dict:
    return {}


@pytest.fixture
def client(settings, recorder, http_routes):
    app = create_app(
        settings,
        http_transport=httpx.MockTransport(json_routes(http_routes)),
        webhook_transport=httpx.MockTransport(recorder.handler),
        webhook_backoff=0,
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def benin_head(client):
    body = {
        "source": "test",
        "source_id": "head-1",
        "title": "Commemorative head of an Oba",
        "object_type": "Sculpture",
        "culture": "Edo peoples",
        "origin_country": "Nigeria",
        "date_text": "16th century",
        "year_start": 1500,
        "year_end": 1599,
        "materials": "Brass",
        "holder": {"name": "National Museum Test", "kind": "national_museum", "country": "Testland", "city": "Testville"},
        "provenance": [
            {"event_type": "created", "location": "Benin City", "date_text": "16th century", "year_start": 1500},
            {"event_type": "looted", "holder_name": "British forces", "location": "Benin City", "year_start": 1897},
            {"event_type": "sold", "holder_name": "Private collection", "holder_kind": "private_collection",
             "location": "London", "year_start": 1950},
        ],
        "auctions": [
            {"auction_house": "Test House", "source": "test", "source_id": "lot-1", "lot_number": "12",
             "sale_year": 1950, "currency": "GBP", "hammer_price": 500, "status": "sold"}
        ],
    }
    response = client.post("/artifacts", json=body)
    assert response.status_code == 201, response.text
    return response.json()
