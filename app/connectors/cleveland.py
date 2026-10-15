"""Cleveland Museum of Art Open Access API (no key needed).

Docs: https://openaccess-api.clevelandart.org/
"""

from __future__ import annotations

from collections.abc import Iterator

from ..regions import classify
from ..schemas import ArtifactIn, HolderIn, ProvenanceIn
from ..services.provenance import YEAR_RE, event_type_for, parse_provenance
from .base import Connector, auctions_from_sales, strip_html, to_int

BASE = "https://openaccess-api.clevelandart.org/api/artworks/"
CMA = HolderIn(name="Cleveland Museum of Art", kind="public_museum", country="United States", city="Cleveland",
               website="https://www.clevelandart.org")
PAGE_SIZE = 50


class ClevelandConnector(Connector):
    name = "cleveland"
    description = "Cleveland Museum of Art (Open Access API, structured provenance)"
    holder = CMA

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        found, skip = 0, 0
        while found < limit:
            params = {"department": "African Art", "limit": PAGE_SIZE, "skip": skip}
            if query:
                params["q"] = query
            data = self.get_json(BASE, **params)
            items = data.get("data") or []
            for item in items:
                record = self.normalize(item)
                if record is not None:
                    found += 1
                    yield record
                    if found >= limit:
                        return
            total = (data.get("info") or {}).get("total") or 0
            skip += len(items)
            if not items or skip >= total:
                return

    @staticmethod
    def normalize(o: dict) -> ArtifactIn | None:
        cultures = o.get("culture") or []
        if isinstance(cultures, str):
            cultures = [cultures]
        cls = classify(*cultures)
        if cls is None:
            return None
        record_id = str(o.get("id"))
        provenance: list[ProvenanceIn] = []
        sales: list[dict] = []
        for entry in o.get("provenance") or []:
            text = strip_html(entry.get("description")) or ""
            if not text:
                continue
            parsed, found_sales = parse_provenance(text)
            first = parsed[0] if parsed else None
            years = [int(y) for y in YEAR_RE.findall(entry.get("date") or "")]
            provenance.append(
                ProvenanceIn(
                    event_type=event_type_for(text),
                    holder_name=first.holder_name if first else None,
                    holder_kind=first.holder_kind if first else None,
                    location=first.location if first else None,
                    date_text=entry.get("date") or (first.date_text if first else None),
                    year_start=min(years) if years else (first.year_start if first else None),
                    year_end=max(years) if years else (first.year_end if first else None),
                    description=text,
                    source="cleveland",
                )
            )
            sales.extend(s.__dict__ for s in found_sales)
        images = o.get("images") or {}
        web = images.get("web") or {}
        culture_text = "; ".join(cultures) or None
        return ArtifactIn(
            source="cleveland",
            source_id=record_id,
            title=o.get("title") or "Untitled",
            object_type=o.get("type"),
            culture=culture_text,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=o.get("creation_date"),
            year_start=to_int(o.get("creation_date_earliest")),
            year_end=to_int(o.get("creation_date_latest")),
            materials=o.get("technique"),
            dimensions=o.get("measurements"),
            description=strip_html(o.get("description")),
            history=strip_html(o.get("fun_fact")) or o.get("creditline"),
            image_url=web.get("url"),
            source_url=o.get("url"),
            holder=CMA,
            provenance=provenance,
            auctions=auctions_from_sales(sales, "cleveland", record_id),
        )
