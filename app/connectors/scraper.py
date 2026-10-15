"""Configurable HTML scraper for auction results and collection pages without an API.

Each site is described by a ``ScrapeConfig`` (CSS selectors), so adding a source
is a JSON file, not code. The scraper honours robots.txt, identifies itself with
a User-Agent and waits between requests. Check each site's terms of use before
scraping it.

Field selectors:
  "h3.title"          -> text of the first matching element inside the item
  "a.lot-link@href"   -> attribute of the first matching element
  "@data-lot"         -> attribute of the item element itself
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date, datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from ..config import Settings
from ..regions import classify
from ..schemas import ArtifactIn, AuctionLotIn, HolderIn
from ..services.money import parse_estimate, parse_money
from .base import Connector

DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y", "%d/%m/%Y", "%d.%m.%Y")


class ScrapeConfig(BaseModel):
    name: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    kind: Literal["auction_lot", "artifact"] = "auction_lot"
    start_urls: list[str] = Field(min_length=1)
    item_selector: str
    fields: dict[str, str]
    next_page_selector: str | None = None
    max_pages: int = Field(default=5, ge=1, le=100)
    # auction_lot defaults
    auction_house: str | None = None
    default_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    # artifact defaults
    holder: HolderIn | None = None


class RobotsDisallowed(Exception):
    pass


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = " ".join(text.split())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def extract(item: Tag, selector: str) -> str | None:
    selector = selector.strip()
    if not selector:
        value = item.get_text(" ", strip=True)
        return value or None
    css, _, attr = selector.partition("@")
    element = item.select_one(css) if css else item
    if element is None:
        return None
    if attr:
        value = element.get(attr)
        if isinstance(value, list):
            value = " ".join(value)
    else:
        value = element.get_text(" ", strip=True)
    return (value or "").strip() or None


class HtmlScraper(Connector):
    name = "scrape"
    description = "Configurable HTML scraper (auction results / collection pages)"

    def __init__(self, client: httpx.Client, settings: Settings, config: ScrapeConfig, sleep=time.sleep) -> None:
        super().__init__(client, settings)
        self.config = config
        self._robots: dict[str, RobotFileParser] = {}
        self._sleep = sleep
        self._last_request = 0.0

    # -- politeness ---------------------------------------------------

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                response = self.client.get(f"{origin}/robots.txt")
                lines = response.text.splitlines() if response.status_code == 200 else []
            except httpx.HTTPError:
                lines = []
            parser.parse(lines)  # missing robots.txt means everything is allowed
            self._robots[origin] = parser
        return parser.can_fetch(self.settings.user_agent, url)

    def fetch_page(self, url: str) -> str:
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        wait = self.settings.scrape_delay_seconds - (time.monotonic() - self._last_request)
        if self._last_request and wait > 0:
            self._sleep(wait)
        self._last_request = time.monotonic()
        response = self.client.get(url)
        response.raise_for_status()
        return response.text

    # -- crawling -----------------------------------------------------

    def pages(self) -> Iterator[tuple[str, BeautifulSoup]]:
        for start in self.config.start_urls:
            url: str | None = start
            seen: set[str] = set()
            for _ in range(self.config.max_pages):
                if url is None or url in seen:
                    break
                seen.add(url)
                soup = BeautifulSoup(self.fetch_page(url), "html.parser")
                yield url, soup
                url = None
                if self.config.next_page_selector:
                    link = soup.select_one(self.config.next_page_selector)
                    if link is not None and link.get("href"):
                        url = urljoin(start, link["href"])

    def raw_items(self) -> Iterator[tuple[str, dict[str, str | None]]]:
        for page_url, soup in self.pages():
            for item in soup.select(self.config.item_selector):
                yield page_url, {key: extract(item, sel) for key, sel in self.config.fields.items()}

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn | AuctionLotIn]:
        found = 0
        needle = query.lower().strip()
        for page_url, raw in self.raw_items():
            if needle and not any(needle in (v or "").lower() for v in raw.values()):
                continue
            record = self.to_auction(page_url, raw) if self.config.kind == "auction_lot" else self.to_artifact(page_url, raw)
            if record is None:
                continue
            found += 1
            yield record
            if found >= limit:
                return

    # -- normalization ------------------------------------------------

    def to_auction(self, page_url: str, raw: dict[str, str | None]) -> AuctionLotIn | None:
        title = raw.get("title")
        culture = raw.get("culture") or raw.get("origin")
        if classify(culture, raw.get("origin"), title) is None:
            return None
        cfg = self.config
        low, high, est_currency = parse_estimate(raw.get("estimate"), cfg.default_currency)
        hammer, hammer_currency = parse_money(raw.get("hammer_price"), cfg.default_currency)
        premium, premium_currency = parse_money(raw.get("price") or raw.get("premium_price"), cfg.default_currency)
        currency = premium_currency or hammer_currency or est_currency or cfg.default_currency
        status = (raw.get("status") or "").lower()
        if status not in ("upcoming", "sold", "unsold", "withdrawn"):
            if premium is not None or hammer is not None:
                status = "sold"
            elif "withdrawn" in status:
                status = "withdrawn"
            elif "unsold" in status or "not sold" in status or "passed" in status or "bought in" in status:
                status = "unsold"
            else:
                status = "unknown"
        url = urljoin(page_url, raw["url"]) if raw.get("url") else None
        sale_date = parse_date(raw.get("sale_date"))
        return AuctionLotIn(
            source=f"scrape:{cfg.name}",
            source_id=raw.get("lot_id") or url or f"{raw.get('sale_title')}:{raw.get('lot_number')}:{title}",
            auction_house=raw.get("auction_house") or cfg.auction_house or urlsplit(page_url).netloc,
            sale_title=raw.get("sale_title"),
            lot_number=raw.get("lot_number"),
            title=title,
            culture=culture,
            sale_date=sale_date,
            sale_year=sale_date.year if sale_date else None,
            location=raw.get("location"),
            currency=currency,
            estimate_low=low,
            estimate_high=high,
            hammer_price=hammer,
            premium_price=premium,
            status=status,
            url=url,
        )

    def to_artifact(self, page_url: str, raw: dict[str, str | None]) -> ArtifactIn | None:
        cls = classify(raw.get("origin_country"), raw.get("culture"), raw.get("origin"))
        if cls is None or not raw.get("title"):
            return None
        url = urljoin(page_url, raw["url"]) if raw.get("url") else None
        image = urljoin(page_url, raw["image_url"]) if raw.get("image_url") else None
        return ArtifactIn(
            source=f"scrape:{self.config.name}",
            source_id=raw.get("id") or url or raw["title"],
            title=raw["title"],
            object_type=raw.get("object_type"),
            culture=raw.get("culture"),
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=raw.get("date"),
            materials=raw.get("materials"),
            dimensions=raw.get("dimensions"),
            description=raw.get("description"),
            history=raw.get("provenance") or raw.get("history"),
            image_url=image,
            source_url=url,
            holder=self.config.holder,
        )
