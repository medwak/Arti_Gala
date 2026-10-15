"""Art Institute of Chicago public API (no key needed).

Docs: https://api.artic.edu/docs/
"""

from __future__ import annotations

from collections.abc import Iterator

from ..regions import classify
from ..schemas import ArtifactIn, HolderIn
from .base import Connector, auctions_from_sales, provenance_from_text, strip_html, to_int

BASE = "https://api.artic.edu/api/v1"
FIELDS = ",".join([
    "id", "title", "place_of_origin", "artist_display", "date_display", "date_start", "date_end",
    "medium_display", "dimensions", "artwork_type_title", "classification_title", "provenance_text",
    "credit_line", "image_id", "department_title", "description", "exhibition_history",
])
AIC = HolderIn(name="Art Institute of Chicago", kind="public_museum", country="United States", city="Chicago",
               website="https://www.artic.edu")
PAGE_SIZE = 50


class ArticConnector(Connector):
    name = "artic"
    label = "Art Institute of Chicago"
    continent = "North America"
    description = "Art Institute of Chicago (public API, includes provenance text)"
    holder = AIC

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        found, page = 0, 1
        while found < limit:
            data = self.get_json(
                f"{BASE}/artworks/search", q=query or "Africa", fields=FIELDS, limit=PAGE_SIZE, page=page
            )
            items = data.get("data") or []
            iiif = (data.get("config") or {}).get("iiif_url") or "https://www.artic.edu/iiif/2"
            for item in items:
                record = self.normalize(item, iiif)
                if record is not None:
                    found += 1
                    yield record
                    if found >= limit:
                        return
            pagination = data.get("pagination") or {}
            if not items or page >= (pagination.get("total_pages") or page):
                return
            page += 1

    @staticmethod
    def normalize(o: dict, iiif_url: str = "https://www.artic.edu/iiif/2") -> ArtifactIn | None:
        artist = o.get("artist_display") or ""
        culture = artist.split("\n")[0].strip() or None
        cls = classify(o.get("place_of_origin"), artist)
        if cls is None:
            return None
        record_id = str(o.get("id"))
        provenance, sales = provenance_from_text(o.get("provenance_text"), "artic")
        exhibitions = strip_html(o.get("exhibition_history"))
        history_parts = [strip_html(o.get("provenance_text")), o.get("credit_line")]
        if exhibitions:
            history_parts.append(f"Exhibitions: {exhibitions}")
        image_id = o.get("image_id")
        return ArtifactIn(
            source="artic",
            source_id=record_id,
            title=o.get("title") or "Untitled",
            object_type=o.get("artwork_type_title") or o.get("classification_title"),
            culture=culture,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=o.get("date_display"),
            year_start=to_int(o.get("date_start")),
            year_end=to_int(o.get("date_end")),
            materials=o.get("medium_display"),
            dimensions=o.get("dimensions"),
            description=strip_html(o.get("description")),
            history="\n\n".join(p for p in history_parts if p) or None,
            image_url=f"{iiif_url}/{image_id}/full/843,/0/default.jpg" if image_id else None,
            source_url=f"https://www.artic.edu/artworks/{record_id}",
            holder=AIC,
            provenance=provenance,
            auctions=auctions_from_sales(sales, "artic", record_id),
        )
