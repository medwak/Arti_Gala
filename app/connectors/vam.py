"""Victoria and Albert Museum (London) Collections API v2 (no key needed).

Docs: https://developers.vam.ac.uk/guide/v2/welcome.html
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx

from ..regions import canonical_country, classify
from ..schemas import ArtifactIn, HolderIn, ProvenanceIn
from .base import Connector, auctions_from_sales, provenance_from_text, strip_html

BASE = "https://api.vam.ac.uk/v2"
VAM = HolderIn(name="Victoria and Albert Museum", kind="national_museum", country="United Kingdom", city="London",
               website="https://www.vam.ac.uk")
PAGE_SIZE = 50


def _year(text: str | None) -> int | None:
    match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})", text or "")
    return int(match.group(1)) if match else None


class VamConnector(Connector):
    name = "vam"
    label = "Victoria and Albert Museum (London)"
    continent = "Europe"
    description = "Victoria and Albert Museum, London (Collections API v2)"
    holder = VAM

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        params: dict = {"page_size": PAGE_SIZE}
        country = canonical_country(query)
        if country:
            params["q_place_name"] = country  # a bare country name searches by place of origin
        else:
            params["q"] = query or "Africa"
        found, page = 0, 1
        while found < limit:
            data = self.get_json(f"{BASE}/objects/search", page=page, **params)
            records = data.get("records") or []
            for summary in records:
                if classify(summary.get("_primaryPlace"), places_only=True) is None:
                    continue  # skip the detail request for objects from elsewhere
                record = self.normalize(summary, self._detail(summary.get("systemNumber")))
                if record is not None:
                    found += 1
                    yield record
                    if found >= limit:
                        return
            info = data.get("info") or {}
            if not records or page >= (info.get("pages") or page):
                return
            page += 1

    def _detail(self, system_number: str | None) -> dict:
        if not system_number:
            return {}
        try:
            return self.get_json(f"{BASE}/object/{system_number}").get("record") or {}
        except httpx.HTTPError:
            return {}  # the search summary is still usable

    @staticmethod
    def normalize(summary: dict, detail: dict | None = None) -> ArtifactIn | None:
        detail = detail or {}
        places = [summary.get("_primaryPlace")]
        for origin in detail.get("placesOfOrigin") or []:
            places.append(((origin or {}).get("place") or {}).get("text"))
        cls = classify(*places, places_only=True)
        if cls is None:
            return None
        system_number = summary.get("systemNumber") or detail.get("systemNumber")
        titles = [t.get("title") for t in detail.get("titles") or [] if t.get("title")]
        object_type = summary.get("objectType") or detail.get("objectType")
        images = summary.get("_images") or {}
        iiif = images.get("_iiif_image_base_url")
        dates = (detail.get("productionDates") or [{}])[0].get("date") or {}
        date_text = dates.get("text") or summary.get("_primaryDate")
        history_text = strip_html(detail.get("objectHistory"))
        provenance, sales = provenance_from_text(history_text, "vam")
        if not provenance:
            provenance = [ProvenanceIn(event_type="acquired", holder_name=VAM.name, holder_kind=VAM.kind,
                                       location="London", description=detail.get("creditLine"), source="vam")]
        maker = (summary.get("_primaryMaker") or {}).get("name")
        culture = None
        if maker and maker.lower() not in ("unknown", "unknown maker"):
            culture = maker
        return ArtifactIn(
            source="vam",
            source_id=str(system_number),
            title=summary.get("_primaryTitle") or (titles[0] if titles else None) or object_type or "Untitled",
            object_type=object_type,
            culture=culture,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=date_text,
            year_start=_year(dates.get("earliest")) or _year(date_text),
            year_end=_year(dates.get("latest")),
            materials=detail.get("materialsAndTechniques") or None,
            description=strip_html(detail.get("summaryDescription") or detail.get("briefDescription")),
            history=history_text or detail.get("creditLine") or None,
            image_url=f"{iiif}full/!600,600/0/default.jpg" if iiif else images.get("_primary_thumbnail"),
            source_url=f"https://collections.vam.ac.uk/item/{system_number}/",
            holder=VAM,
            provenance=provenance,
            auctions=auctions_from_sales(sales, "vam", str(system_number)),
        )
