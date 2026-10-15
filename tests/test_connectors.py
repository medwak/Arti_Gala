"""Connectors against canned API responses shaped like the real ones."""

import httpx

from app.config import Settings
from app.connectors.artic import ArticConnector
from app.connectors.cleveland import ClevelandConnector
from app.connectors.met import BASE as MET_BASE
from app.connectors.met import MetConnector
from app.connectors.scraper import HtmlScraper, RobotsDisallowed, ScrapeConfig
from app.connectors.smithsonian import SmithsonianConnector
from app.schemas import ArtifactIn, AuctionLotIn

from .conftest import json_routes

SETTINGS = Settings(database_url="sqlite://", scrape_delay_seconds=0, smithsonian_api_key="KEY")


def client_for(routes) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(json_routes(routes)))


MET_OBJECT_EDO = {
    "objectID": 1001, "title": "Plaque: Warrior and Attendants", "objectName": "Plaque", "culture": "Edo peoples",
    "country": "Nigeria", "region": "Court of Benin", "objectDate": "16th–17th century", "objectBeginDate": 1550,
    "objectEndDate": 1680, "medium": "Brass", "dimensions": "H. 47.6 cm", "accessionYear": "1990",
    "creditLine": "Gift of Example Donor, 1990", "primaryImageSmall": "https://images.example/1001.jpg",
    "objectURL": "https://www.metmuseum.org/art/collection/search/1001",
}
MET_OBJECT_OCEANIA = {"objectID": 1002, "title": "Shield", "culture": "Asmat", "country": "Indonesia", "region": "Papua"}


def test_met_connector_keeps_only_sub_saharan():
    routes = {
        f"{MET_BASE}/search": {"total": 2, "objectIDs": [1002, 1001]},
        f"{MET_BASE}/objects/1001": MET_OBJECT_EDO,
        f"{MET_BASE}/objects/1002": MET_OBJECT_OCEANIA,
    }
    records = list(MetConnector(client_for(routes), SETTINGS).fetch("plaque", 10))
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec, ArtifactIn)
    assert (rec.source, rec.source_id, rec.origin_country) == ("met", "1001", "Nigeria")
    assert rec.year_start == 1550 and rec.year_end == 1680
    assert rec.holder.name == "The Metropolitan Museum of Art"
    assert rec.provenance[0].year_start == 1990
    assert rec.provenance[0].description == "Gift of Example Donor, 1990"


AIC_RESPONSE = {
    "pagination": {"total_pages": 1},
    "config": {"iiif_url": "https://www.artic.edu/iiif/2"},
    "data": [
        {
            "id": 55, "title": "Mask (Mukenga)", "place_of_origin": "Democratic Republic of the Congo",
            "artist_display": "Kuba\nDemocratic Republic of the Congo", "date_display": "Late 19th century",
            "date_start": 1875, "date_end": 1900, "medium_display": "Wood, raffia, cowrie shells",
            "artwork_type_title": "Mask", "image_id": "abc-123", "description": "<p>A <em>royal</em> mask.</p>",
            "provenance_text": "Collected by A. Missionary, Kasai, 1905; sold, Christie's, London, 1970, lot 45, to Private collection, Brussels; purchased by the Art Institute, 1990.",
            "credit_line": "Example Fund",
        },
        {"id": 56, "title": "Vase", "place_of_origin": "Greece", "artist_display": "Ancient Greek"},
    ],
}


def test_artic_connector_parses_provenance_and_sales():
    routes = {"https://api.artic.edu/api/v1/artworks/search": AIC_RESPONSE}
    records = list(ArticConnector(client_for(routes), SETTINGS).fetch("mask", 10))
    assert len(records) == 1
    rec = records[0]
    assert rec.culture == "Kuba"
    assert rec.origin_region == "Central Africa"
    assert rec.description == "A royal mask."
    assert rec.image_url == "https://www.artic.edu/iiif/2/abc-123/full/843,/0/default.jpg"
    assert [p.event_type for p in rec.provenance] == ["collected", "sold", "acquired"]
    assert len(rec.auctions) == 1
    lot = rec.auctions[0]
    assert (lot.auction_house, lot.lot_number, lot.sale_year, lot.status) == ("Christie's", "45", 1970, "sold")


CMA_RESPONSE = {
    "info": {"total": 1},
    "data": [
        {
            "id": 777, "title": "Power Figure (Nkisi Nkondi)", "type": "Sculpture",
            "culture": ["Central Africa, Democratic Republic of the Congo, Kongo peoples"],
            "creation_date": "late 1800s", "creation_date_earliest": 1875, "creation_date_latest": 1899,
            "technique": "wood, iron", "measurements": "H. 90 cm", "url": "https://clevelandart.org/art/777",
            "images": {"web": {"url": "https://images.example/777.jpg"}},
            "provenance": [
                {"description": "Collected in the Mayombe region", "date": "before 1910"},
                {"description": "Sold, Sotheby's, New York, lot 88, to Private collection, New York", "date": "1979"},
                {"description": "Gift to the Cleveland Museum of Art", "date": "1999"},
            ],
        }
    ],
}


def test_cleveland_connector_structured_provenance():
    routes = {"https://openaccess-api.clevelandart.org/api/artworks/": CMA_RESPONSE}
    records = list(ClevelandConnector(client_for(routes), SETTINGS).fetch("", 5))
    assert len(records) == 1
    rec = records[0]
    assert rec.origin_country == "Democratic Republic of the Congo"
    assert [p.event_type for p in rec.provenance] == ["collected", "sold", "donated"]
    assert rec.provenance[1].year_start == 1979
    assert rec.provenance[1].holder_kind == "private_collection"
    assert rec.auctions[0].auction_house == "Sotheby's"


SI_RESPONSE = {
    "response": {
        "rowCount": 1,
        "rows": [
            {
                "id": "edanmdm-nmafa_85-1-1",
                "content": {
                    "descriptiveNonRepeating": {
                        "record_ID": "nmafa_85-1-1", "title": {"content": "Crest mask"},
                        "record_link": "https://africa.si.edu/collections/objects/1",
                        "online_media": {"media": [{"content": "https://ids.si.edu/1.jpg"}]},
                    },
                    "indexedStructured": {
                        "geoLocation": [{"L2": {"content": "Africa"}, "L3": {"content": "Cameroon"}}],
                        "culture": ["Bamileke peoples"], "object_type": ["Masks"], "date": ["1900s"],
                    },
                    "freetext": {
                        "date": [{"label": "Date", "content": "Early 20th century"}],
                        "physicalDescription": [{"label": "Medium", "content": "Wood"}],
                        "notes": [{"label": "Provenance", "content": "Private collection, Paris, 1960; acquired by the museum, 1985"}],
                    },
                },
            }
        ],
    }
}


def test_smithsonian_connector_is_national_museum():
    routes = {"https://api.si.edu/openaccess/api/v1.0/search": SI_RESPONSE}
    records = list(SmithsonianConnector(client_for(routes), SETTINGS).fetch("mask", 5))
    assert len(records) == 1
    rec = records[0]
    assert rec.holder.kind == "national_museum"
    assert rec.origin_country == "Cameroon"
    assert rec.object_type == "Masks"
    assert rec.provenance[0].holder_kind == "private_collection"


ROBOTS = "User-agent: *\nDisallow: /private\n"
LISTING_1 = """
<html><body>
 <div class="lot" data-lot-id="A1">
   <span class="lot-number">12</span><h3 class="lot-title">Yoruba Ibeji figure</h3>
   <span class="lot-culture">Yoruba, Nigeria</span><span class="sale-name">African Art</span>
   <time class="sale-date" datetime="2024-05-14"></time><span class="estimate">USD 2,000 - 3,000</span>
   <span class="price-realised">USD 4,410</span><a class="lot-link" href="/lots/A1">view</a>
 </div>
 <div class="lot" data-lot-id="A2">
   <span class="lot-number">13</span><h3 class="lot-title">Chinese vase</h3><span class="lot-culture">China</span>
 </div>
 <a class="next-page" href="/results?page=2">next</a>
</body></html>
"""
LISTING_2 = """
<html><body>
 <div class="lot" data-lot-id="B7">
   <span class="lot-number">40</span><h3 class="lot-title">Fang reliquary head</h3>
   <span class="lot-culture">Fang, Gabon</span><span class="estimate">€50.000–70.000</span>
   <span class="lot-status">Bought in</span>
 </div>
</body></html>
"""

CONFIG = ScrapeConfig(
    name="test-house",
    start_urls=["https://auctions.test/results"],
    item_selector="div.lot",
    fields={
        "lot_id": "@data-lot-id", "lot_number": ".lot-number", "title": "h3.lot-title", "culture": ".lot-culture",
        "sale_title": ".sale-name", "sale_date": "time.sale-date@datetime", "estimate": ".estimate",
        "price": ".price-realised", "status": ".lot-status", "url": "a.lot-link@href",
    },
    next_page_selector="a.next-page",
    auction_house="Test Auctions",
)


def test_scraper_extracts_paginated_auction_lots():
    routes = {
        "https://auctions.test/robots.txt": ROBOTS,
        "https://auctions.test/results?page=2": LISTING_2,
        "https://auctions.test/results": LISTING_1,
    }
    records = list(HtmlScraper(client_for(routes), SETTINGS, CONFIG).fetch("", 10))
    assert all(isinstance(r, AuctionLotIn) for r in records)
    assert [r.title for r in records] == ["Yoruba Ibeji figure", "Fang reliquary head"]  # vase filtered out
    ibeji, fang = records
    assert (ibeji.estimate_low, ibeji.estimate_high, ibeji.premium_price, ibeji.currency) == (2000, 3000, 4410, "USD")
    assert ibeji.status == "sold"
    assert ibeji.url == "https://auctions.test/lots/A1"
    assert ibeji.sale_date.isoformat() == "2024-05-14"
    assert ibeji.auction_house == "Test Auctions"
    assert (fang.estimate_low, fang.estimate_high, fang.currency, fang.status) == (50000, 70000, "EUR", "unsold")


def test_scraper_respects_robots_txt():
    config = CONFIG.model_copy(update={"start_urls": ["https://auctions.test/private/results"]})
    routes = {"https://auctions.test/robots.txt": ROBOTS, "https://auctions.test/private": LISTING_1}
    scraper = HtmlScraper(client_for(routes), SETTINGS, config)
    try:
        list(scraper.fetch("", 10))
    except RobotsDisallowed:
        pass
    else:
        raise AssertionError("expected RobotsDisallowed")
