"""Europeana Search API: collections of many European museums in one place.

Each record keeps the museum that actually holds the object (``dataProvider``)
as its holder. Docs: https://europeana.atlassian.net/wiki/spaces/EF/pages/2385739812/Search+API+Documentation
Get a free key at https://pro.europeana.eu/pages/get-api and set ARTI_EUROPEANA_API_KEY.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..regions import classify
from ..schemas import ArtifactIn, HolderIn, ProvenanceIn
from .base import Connector, strip_html

BASE = "https://api.europeana.eu/record/v2/search.json"
PAGE_SIZE = 100
NATIONAL_WORDS = ("national", "nationaal", "nationale", "nazionale", "nacional", "rijks", "royal", "royaal", "staatliche")


def _first(value) -> str | None:
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value else None


def _lang_values(field) -> list[str]:
    """Europeana language maps look like {"def": [...], "en": [...]}; prefer English."""
    if not isinstance(field, dict):
        return []
    values = field.get("en") or field.get("def") or next(iter(field.values()), [])
    return [str(v) for v in values if v]


def _labels(field) -> list[str]:
    out = []
    for item in field or []:
        if isinstance(item, dict):
            out.extend(str(v) for k, v in item.items() if k in ("def", "en") and v)
        elif item:
            out.append(str(item))
    return out


class EuropeanaConnector(Connector):
    name = "europeana"
    label = "Europeana (museums across Europe)"
    continent = "Europe"
    description = "Europeana: European museum collections in one search (uses the public demo key unless ARTI_EUROPEANA_API_KEY is set)"
    api_key_setting = "europeana_api_key"
    api_key_env = "ARTI_EUROPEANA_API_KEY"

    def fetch(self, query: str, limit: int) -> Iterator[ArtifactIn]:
        found, cursor = 0, "*"
        while found < limit and cursor:
            data = self.get_json(
                BASE,
                wskey=self.settings.europeana_api_key,
                query=query or "Africa",
                rows=PAGE_SIZE,
                cursor=cursor,
                profile="standard",
            )
            items = data.get("items") or []
            for item in items:
                record = self.normalize(item)
                if record is not None:
                    found += 1
                    yield record
                    if found >= limit:
                        return
            cursor = data.get("nextCursor") if items else None

    @staticmethod
    def normalize(item: dict) -> ArtifactIn | None:
        places = _labels(item.get("edmPlaceLabel"))
        titles = _lang_values(item.get("dcTitleLangAware")) or [str(t) for t in item.get("title") or []]
        title = titles[0] if titles else None
        creators = [str(c) for c in item.get("dcCreator") or []]
        cls = classify(*places) or classify(title, *creators, places_only=True)
        if cls is None or not title:
            return None

        provider = _first(item.get("dataProvider")) or "Unknown European collection"
        provider_country = _first(item.get("country"))
        kind = "national_museum" if any(w in provider.lower() for w in NATIONAL_WORDS) else "public_museum"
        holder = HolderIn(name=provider[:300], kind=kind, country=provider_country)

        descriptions = _lang_values(item.get("dcDescriptionLangAware")) or [str(d) for d in item.get("dcDescription") or []]
        description = strip_html(" ".join(descriptions)) if descriptions else None
        years = [int(y) for y in item.get("year") or [] if re.fullmatch(r"-?\d{1,4}", str(y))]
        types = _lang_values(item.get("dcTypeLangAware"))
        record_id = str(item.get("id") or "").strip("/")
        return ArtifactIn(
            source="europeana",
            source_id=record_id,
            title=title[:500],
            object_type=types[0] if types else None,
            culture=", ".join(creators)[:300] or None,
            origin_country=cls.country,
            origin_region=cls.subregion,
            date_text=", ".join(str(y) for y in item.get("year") or []) or None,
            year_start=min(years) if years else None,
            year_end=max(years) if years else None,
            description=description,
            history=f"Held by {provider}" + (f" ({provider_country})." if provider_country else "."),
            image_url=_first(item.get("edmPreview")),
            source_url=_first(item.get("edmIsShownAt")) or (f"https://www.europeana.eu/item/{record_id}" if record_id else None),
            holder=holder,
            provenance=[ProvenanceIn(event_type="acquired", holder_name=provider[:300], holder_kind=kind,
                                     location=provider_country, source="europeana")],
        )
