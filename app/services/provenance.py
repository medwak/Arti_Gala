"""Turn free-text provenance (as published by museums) into structured events.

Provenance text usually lists owners in order, separated by semicolons, e.g.
"Collected by X, Benin City, 1897; by descent to Y; sold, Sotheby's, London,
1975, lot 120, to Z; given to the museum, 1980." The parsing is heuristic:
every event keeps the original text in ``description`` so nothing is lost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..regions import classify
from .money import parse_money

YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
LOT_RE = re.compile(r"\blot\s*(?:no\.?\s*)?([0-9]+[A-Za-z]?)\b", re.IGNORECASE)
FOOTNOTE_RE = re.compile(r"\[\d+\]")

# Checked in order; the first match decides the event type.
EVENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in [
        ("looted", r"\b(looted|loot|punitive expedition|seized|confiscated|taken by force|spoils of war)\b"),
        ("stolen", r"\b(stolen|theft)\b"),
        ("restituted", r"\b(restitut\w*|repatriat\w*|returned to)\b"),
        ("recovered", r"\b(recovered)\b"),
        ("sold", r"\b(sold|sale|auction(?:ed)?|lot\s*\d+)\b"),
        ("donated", r"\b(gift|given|donat\w+|bequest|bequeathed|presented)\b"),
        ("inherited", r"\b(by descent|inherited|by inheritance|his (?:son|daughter|widow)|her (?:son|daughter))\b"),
        ("loaned", r"\b(on loan|lent|loaned)\b"),
        ("exhibited", r"\b(exhibited|exhibition)\b"),
        ("collected", r"\b(collected|field collection|acquired in situ|in situ)\b"),
        ("acquired", r"\b(purchased|bought|acquired|acquisition)\b"),
        ("created", r"\b(made|carved|cast|created)\b"),
    ]
]

AUCTION_HOUSES = [
    "Sotheby's", "Sotheby Parke Bernet", "Christie's", "Bonhams", "Phillips", "Hôtel Drouot", "Drouot",
    "Lempertz", "Zemanek-Münster", "Dorotheum", "Artcurial", "Millon", "Binoche et Giquello",
    "Heritage Auctions", "Woolley and Wallis", "Woolley & Wallis", "Skinner", "Koller",
    "Bukowskis", "Tajan", "Cornette de Saint Cyr", "Glendining's",
]
_HOUSE_RE = re.compile(
    "|".join(re.escape(h).replace("'", "['’]") for h in sorted(AUCTION_HOUSES, key=len, reverse=True)),
    re.IGNORECASE,
)
_CANONICAL_HOUSES = {h.lower().replace("’", "'"): h for h in AUCTION_HOUSES}

CITIES = [
    "London", "Paris", "Brussels", "Antwerp", "New York", "Berlin", "Hamburg", "Munich", "Cologne",
    "Vienna", "Amsterdam", "Geneva", "Zurich", "Basel", "Stockholm", "Los Angeles", "Chicago",
    "Philadelphia", "Boston", "Washington", "Lagos", "Benin City", "Ibadan", "Ife", "Accra", "Kumasi",
    "Dakar", "Bamako", "Abidjan", "Kinshasa", "Brazzaville", "Luanda", "Nairobi", "Addis Ababa",
    "Dar es Salaam", "Zanzibar", "Johannesburg", "Cape Town", "Harare", "Douala", "Yaoundé", "Libreville",
]
_CITY_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(CITIES, key=len, reverse=True)) + r")\b")


@dataclass
class ParsedEvent:
    event_type: str
    holder_name: str | None
    holder_kind: str | None
    location: str | None
    date_text: str | None
    year_start: int | None
    year_end: int | None
    description: str


@dataclass
class ParsedSale:
    auction_house: str
    sale_year: int | None
    lot_number: str | None
    location: str | None
    price: float | None
    currency: str | None
    description: str


def split_segments(text: str) -> list[str]:
    text = FOOTNOTE_RE.sub("", text)
    parts = re.split(r";|\n+", text)
    return [p.strip(" .\t") for p in parts if p and p.strip(" .\t")]


def event_type_for(text: str) -> str:
    for name, pattern in EVENT_PATTERNS:
        if pattern.search(text):
            return name
    return "transferred"


def _holder_from(segment: str) -> tuple[str | None, str | None]:
    if re.search(r"\bprivate collection\b", segment, re.IGNORECASE):
        return "Private collection", "private_collection"
    to_match = re.search(r"\bto\s+([A-Z][^,;]+)", segment)
    if to_match:
        return to_match.group(1).strip(), None
    by_match = re.search(r"\bby\s+([A-Z][^,;]+)", segment)
    if by_match:
        return by_match.group(1).strip(), None
    first = segment.split(",")[0].strip()
    if first and first[0].isupper() and not YEAR_RE.fullmatch(first) and len(first) <= 200:
        return first, None
    return None, None


def _location_from(segment: str) -> str | None:
    city = _CITY_RE.search(segment)
    if city:
        return city.group(1)
    cls = classify(segment)
    return cls.country if cls and cls.country else None


def parse_provenance(text: str | None) -> tuple[list[ParsedEvent], list[ParsedSale]]:
    """Split provenance text into events, plus any auction sales it mentions."""
    if not text:
        return [], []
    events: list[ParsedEvent] = []
    sales: list[ParsedSale] = []
    for segment in split_segments(text):
        years = [int(y) for y in YEAR_RE.findall(segment)]
        event_type = event_type_for(segment)
        holder_name, holder_kind = _holder_from(segment)
        location = _location_from(segment)
        date_match = re.search(r"\b(?:c\.|ca\.|circa|by|before|after|until)?\s*(1[0-9]{3}|20[0-9]{2})(?:\s*[-–]\s*(1[0-9]{3}|20[0-9]{2}))?", segment)
        events.append(
            ParsedEvent(
                event_type=event_type,
                holder_name=holder_name,
                holder_kind=holder_kind,
                location=location,
                date_text=date_match.group(0).strip() if date_match else None,
                year_start=min(years) if years else None,
                year_end=max(years) if years else None,
                description=segment,
            )
        )
        house = _HOUSE_RE.search(segment)
        if house and event_type == "sold":
            lot = LOT_RE.search(segment)
            price, currency = (None, None)
            if re.search(r"[$£€¥₦]|\b(USD|GBP|EUR|CHF)\b", segment):
                # Strip years and lot numbers so they are not read as prices.
                priced = LOT_RE.sub("", YEAR_RE.sub("", segment))
                price, currency = parse_money(priced)
            canonical = _CANONICAL_HOUSES.get(house.group(0).lower().replace("’", "'"), house.group(0))
            sales.append(
                ParsedSale(
                    auction_house=canonical,
                    sale_year=years[0] if years else None,
                    lot_number=lot.group(1) if lot else None,
                    location=location,
                    price=price,
                    currency=currency,
                    description=segment,
                )
            )
    return events, sales


def compose_timeline(events) -> list[str]:
    """Readable one-line-per-event timeline for ProvenanceEvent-like objects."""
    lines = []
    for e in events:
        when = e.date_text or (str(e.year_start) if e.year_start else "date unknown")
        who = e.holder_name or "unknown holder"
        where = f" ({e.location})" if e.location else ""
        lines.append(f"{when}: {e.event_type.replace('_', ' ')} — {who}{where}")
    return lines
