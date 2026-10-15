"""Common connector interface."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator

import httpx
from bs4 import BeautifulSoup

from ..config import Settings
from ..schemas import ArtifactIn, AuctionLotIn, HolderIn, ProvenanceIn
from ..services.provenance import parse_provenance


class Connector(ABC):
    """Fetches records from one source and yields them in normalized form."""

    name: str = ""
    description: str = ""
    holder: HolderIn | None = None

    def __init__(self, client: httpx.Client, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @abstractmethod
    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn | AuctionLotIn]:
        """Yield up to ``limit`` sub-Saharan records matching ``query``."""

    def get_json(self, url: str, **params) -> dict:
        response = self.client.get(url, params=params or None)
        response.raise_for_status()
        return response.json()


def strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", cleaned) or None


def to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def provenance_from_text(text: str | None, source: str) -> tuple[list[ProvenanceIn], list[dict]]:
    """Parse museum provenance text into ProvenanceIn rows plus sale mentions."""
    events, sales = parse_provenance(text)
    rows = [
        ProvenanceIn(
            event_type=e.event_type,
            holder_name=e.holder_name,
            holder_kind=e.holder_kind,
            location=e.location,
            date_text=e.date_text,
            year_start=e.year_start,
            year_end=e.year_end,
            description=e.description,
            source=source,
        )
        for e in events
    ]
    return rows, [s.__dict__ for s in sales]


def auctions_from_sales(sales: list[dict], source: str, record_id: str) -> list[AuctionLotIn]:
    """Auction lots mentioned in an artifact's provenance."""
    lots = []
    for i, sale in enumerate(sales):
        price = sale.get("price")
        lots.append(
            AuctionLotIn(
                source=f"{source}-provenance",
                source_id=f"{record_id}:{i}",
                auction_house=sale["auction_house"],
                lot_number=sale.get("lot_number"),
                sale_year=sale.get("sale_year"),
                location=sale.get("location"),
                currency=sale.get("currency") if price is not None else None,
                hammer_price=price,
                status="sold",
                sale_title=sale.get("description"),
            )
        )
    return lots
