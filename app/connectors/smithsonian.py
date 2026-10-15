"""Smithsonian Open Access API, limited to the National Museum of African Art (NMAfA).

Needs a free api.data.gov key in ARTI_SMITHSONIAN_API_KEY.
Docs: https://edan.si.edu/openaccess/apidocs/
"""

from __future__ import annotations

from collections.abc import Iterator

from ..regions import classify
from ..schemas import ArtifactIn, HolderIn
from .base import Connector, auctions_from_sales, provenance_from_text, to_int

BASE = "https://api.si.edu/openaccess/api/v1.0/search"
NMAFA = HolderIn(name="Smithsonian National Museum of African Art", kind="national_museum",
                 country="United States", city="Washington", website="https://africa.si.edu")
PAGE_SIZE = 50


def _contents(items, label: str | None = None) -> list[str]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            if label is None or (item.get("label") or "").lower() == label.lower():
                if item.get("content"):
                    out.append(str(item["content"]))
        elif item:
            out.append(str(item))
    return out


class SmithsonianConnector(Connector):
    name = "smithsonian"
    description = "Smithsonian National Museum of African Art (needs ARTI_SMITHSONIAN_API_KEY)"
    holder = NMAFA

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        if not self.settings.smithsonian_api_key:
            raise RuntimeError("Set ARTI_SMITHSONIAN_API_KEY (free key from https://api.data.gov/signup/)")
        q = f"unit_code:NMAfA AND ({query})" if query else "unit_code:NMAfA"
        found, start = 0, 0
        while found < limit:
            data = self.get_json(BASE, q=q, rows=PAGE_SIZE, start=start, api_key=self.settings.smithsonian_api_key)
            response = data.get("response") or {}
            rows = response.get("rows") or []
            for row in rows:
                record = self.normalize(row)
                if record is not None:
                    found += 1
                    yield record
                    if found >= limit:
                        return
            start += len(rows)
            if not rows or start >= (response.get("rowCount") or 0):
                return

    @staticmethod
    def normalize(row: dict) -> ArtifactIn | None:
        content = row.get("content") or {}
        dnr = content.get("descriptiveNonRepeating") or {}
        indexed = content.get("indexedStructured") or {}
        free = content.get("freetext") or {}

        countries = []
        for geo in indexed.get("geoLocation") or []:
            for level in ("L3", "L2"):
                value = (geo.get(level) or {}).get("content")
                if value:
                    countries.append(value)
        cultures = _contents(indexed.get("culture"))
        cls = classify(*countries, *cultures)
        if cls is None:
            return None

        record_id = dnr.get("record_ID") or row.get("id")
        title = (dnr.get("title") or {}).get("content") or row.get("title") or "Untitled"
        media = ((dnr.get("online_media") or {}).get("media") or [{}])[0]
        provenance_text = " ; ".join(_contents(free.get("notes"), "Provenance"))
        provenance, sales = provenance_from_text(provenance_text, "smithsonian")
        dates = _contents(free.get("date"))
        years = [to_int(d[:4]) for d in indexed.get("date") or [] if d]
        years = [y for y in years if y]
        return ArtifactIn(
            source="smithsonian",
            source_id=str(record_id),
            title=title,
            object_type=(_contents(indexed.get("object_type")) or [None])[0],
            culture="; ".join(cultures) or None,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=dates[0] if dates else None,
            year_start=min(years) if years else None,
            year_end=max(years) if years else None,
            materials="; ".join(_contents(free.get("physicalDescription"), "Medium")) or None,
            dimensions="; ".join(_contents(free.get("physicalDescription"), "Dimensions")) or None,
            description="; ".join(_contents(free.get("notes"), "Description")) or None,
            history=provenance_text or ("; ".join(_contents(free.get("creditLine"))) or None),
            image_url=media.get("content") or media.get("thumbnail"),
            source_url=dnr.get("record_link"),
            holder=NMAFA,
            provenance=provenance,
            auctions=auctions_from_sales(sales, "smithsonian", str(record_id)),
        )
