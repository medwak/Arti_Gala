"""The Metropolitan Museum of Art Collection API (no key needed).

Docs: https://metmuseum.github.io/
"""

from __future__ import annotations

from collections.abc import Iterator

from ..regions import classify
from ..schemas import ArtifactIn, HolderIn, ProvenanceIn
from .base import Connector, to_int

BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
# "Arts of Africa, Oceania, and the Americas" (now "The Michael C. Rockefeller Wing").
AFRICA_DEPARTMENT_ID = 5
MET = HolderIn(name="The Metropolitan Museum of Art", kind="public_museum", country="United States", city="New York",
               website="https://www.metmuseum.org")


class MetConnector(Connector):
    name = "met"
    description = "The Metropolitan Museum of Art, New York (Collection API)"
    holder = MET

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        search = self.get_json(f"{BASE}/search", q=query or "Africa", departmentId=AFRICA_DEPARTMENT_ID)
        ids = search.get("objectIDs") or []
        found = 0
        # The department also covers Oceania and the Americas, so look at more objects than we keep.
        for object_id in ids[: max(limit * 5, limit)]:
            if found >= limit:
                break
            record = self.normalize(self.get_json(f"{BASE}/objects/{object_id}"))
            if record is not None:
                found += 1
                yield record

    @staticmethod
    def normalize(o: dict) -> ArtifactIn | None:
        cls = classify(o.get("country"), o.get("culture"), o.get("region"), o.get("subregion"), o.get("locale"))
        if cls is None:
            return None
        credit = o.get("creditLine") or None
        accession_year = to_int((o.get("accessionYear") or "")[:4])
        provenance = []
        if credit or accession_year:
            provenance.append(
                ProvenanceIn(
                    event_type="acquired",
                    holder_name=MET.name,
                    holder_kind=MET.kind,
                    location="New York",
                    date_text=str(accession_year) if accession_year else None,
                    year_start=accession_year,
                    year_end=accession_year,
                    description=credit,
                    source="met",
                )
            )
        place = ", ".join(p for p in (o.get("locale"), o.get("region"), o.get("country")) if p)
        history = " ".join(
            s for s in (
                f"Made by {o['culture']} artists" if o.get("culture") else None,
                f"in {place}" if place else None,
                f"({o['objectDate']})." if o.get("objectDate") else ".",
                f"Credit line: {credit}." if credit else None,
            ) if s
        )
        return ArtifactIn(
            source="met",
            source_id=str(o.get("objectID")),
            title=o.get("title") or o.get("objectName") or "Untitled",
            object_type=o.get("objectName") or o.get("classification") or None,
            culture=o.get("culture") or None,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=o.get("objectDate") or None,
            year_start=to_int(o.get("objectBeginDate")),
            year_end=to_int(o.get("objectEndDate")),
            materials=o.get("medium") or None,
            dimensions=o.get("dimensions") or None,
            history=history or None,
            image_url=o.get("primaryImageSmall") or o.get("primaryImage") or None,
            source_url=o.get("objectURL") or None,
            holder=MET,
            provenance=provenance,
        )
