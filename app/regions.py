"""Decide whether an object comes from sub-Saharan Africa, and from where.

Matching works on short structured fields (country, culture, place of origin),
never on free-text descriptions, because culture names such as "Dan" or "Fon"
are ordinary words elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WEST = "West Africa"
CENTRAL = "Central Africa"
EAST = "East Africa"
SOUTHERN = "Southern Africa"
GENERIC = "Sub-Saharan Africa"

COUNTRIES: dict[str, str] = {
    # West Africa
    "Benin": WEST, "Burkina Faso": WEST, "Cabo Verde": WEST, "Côte d'Ivoire": WEST,
    "Gambia": WEST, "Ghana": WEST, "Guinea": WEST, "Guinea-Bissau": WEST, "Liberia": WEST,
    "Mali": WEST, "Mauritania": WEST, "Niger": WEST, "Nigeria": WEST, "Senegal": WEST,
    "Sierra Leone": WEST, "Togo": WEST,
    # Central Africa
    "Angola": CENTRAL, "Cameroon": CENTRAL, "Central African Republic": CENTRAL, "Chad": CENTRAL,
    "Republic of the Congo": CENTRAL, "Democratic Republic of the Congo": CENTRAL,
    "Equatorial Guinea": CENTRAL, "Gabon": CENTRAL, "São Tomé and Príncipe": CENTRAL,
    # East Africa (UN "Eastern Africa", plus Sudan as counted by the World Bank)
    "Burundi": EAST, "Comoros": EAST, "Djibouti": EAST, "Eritrea": EAST, "Ethiopia": EAST,
    "Kenya": EAST, "Madagascar": EAST, "Malawi": EAST, "Mauritius": EAST, "Mozambique": EAST,
    "Rwanda": EAST, "Seychelles": EAST, "Somalia": EAST, "South Sudan": EAST, "Sudan": EAST,
    "Tanzania": EAST, "Uganda": EAST, "Zambia": EAST, "Zimbabwe": EAST,
    # Southern Africa
    "Botswana": SOUTHERN, "Eswatini": SOUTHERN, "Lesotho": SOUTHERN, "Namibia": SOUTHERN,
    "South Africa": SOUTHERN,
}

# Alternative spellings and historical / colonial names -> modern country.
ALIASES: dict[str, str] = {
    "Ivory Coast": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire", "Côte d’Ivoire": "Côte d'Ivoire",
    "Cote d’Ivoire": "Côte d'Ivoire", "Dahomey": "Benin", "Gold Coast": "Ghana",
    "Upper Volta": "Burkina Faso", "French Sudan": "Mali", "Portuguese Guinea": "Guinea-Bissau",
    "The Gambia": "Gambia", "Cape Verde": "Cabo Verde",
    "Kingdom of Benin": "Nigeria", "Benin Kingdom": "Nigeria", "Benin City": "Nigeria",
    "Zaire": "Democratic Republic of the Congo", "Belgian Congo": "Democratic Republic of the Congo",
    "Congo Free State": "Democratic Republic of the Congo", "DR Congo": "Democratic Republic of the Congo",
    "DRC": "Democratic Republic of the Congo", "Congo-Kinshasa": "Democratic Republic of the Congo",
    "Democratic Republic of Congo": "Democratic Republic of the Congo",
    "Congo (Kinshasa)": "Democratic Republic of the Congo",
    "Republic of Congo": "Republic of the Congo", "Congo-Brazzaville": "Republic of the Congo",
    "Congo (Brazzaville)": "Republic of the Congo", "French Congo": "Republic of the Congo",
    "Middle Congo": "Republic of the Congo",
    "Ubangi-Shari": "Central African Republic", "Fernando Po": "Equatorial Guinea",
    "Sao Tome and Principe": "São Tomé and Príncipe", "Sao Tome": "São Tomé and Príncipe",
    "São Tomé": "São Tomé and Príncipe",
    "Abyssinia": "Ethiopia", "Tanganyika": "Tanzania", "Zanzibar": "Tanzania",
    "Rhodesia": "Zimbabwe", "Southern Rhodesia": "Zimbabwe", "Northern Rhodesia": "Zambia",
    "Nyasaland": "Malawi", "Somaliland": "Somalia", "Swaziland": "Eswatini",
    "Bechuanaland": "Botswana", "Basutoland": "Lesotho", "South West Africa": "Namibia",
    "German South West Africa": "Namibia", "Kamerun": "Cameroon", "Togoland": "Togo",
}

# Peoples / cultures -> the country most associated with them.
CULTURES: dict[str, str] = {
    "Edo": "Nigeria", "Bini": "Nigeria", "Yoruba": "Nigeria", "Igbo": "Nigeria", "Ibo": "Nigeria",
    "Ife": "Nigeria", "Nok": "Nigeria", "Hausa": "Nigeria", "Ijo": "Nigeria", "Ijaw": "Nigeria",
    "Ibibio": "Nigeria", "Igala": "Nigeria", "Idoma": "Nigeria", "Tiv": "Nigeria", "Mumuye": "Nigeria",
    "Jukun": "Nigeria", "Urhobo": "Nigeria", "Owo": "Nigeria", "Esie": "Nigeria",
    "Akan": "Ghana", "Asante": "Ghana", "Ashanti": "Ghana", "Fante": "Ghana", "Ewe": "Ghana",
    "Ga": "Ghana", "Fon": "Benin", "Dogon": "Mali", "Bamana": "Mali", "Bambara": "Mali",
    "Malinke": "Mali", "Djenne": "Mali", "Jenne": "Mali", "Tellem": "Mali",
    "Senufo": "Côte d'Ivoire", "Baule": "Côte d'Ivoire", "Baoulé": "Côte d'Ivoire",
    "Dan": "Côte d'Ivoire", "Guro": "Côte d'Ivoire", "Gouro": "Côte d'Ivoire", "Yaure": "Côte d'Ivoire",
    "Attie": "Côte d'Ivoire", "Lagoons peoples": "Côte d'Ivoire", "Kru": "Liberia", "Grebo": "Liberia",
    "Lobi": "Burkina Faso", "Mossi": "Burkina Faso", "Bwa": "Burkina Faso", "Nuna": "Burkina Faso",
    "Mende": "Sierra Leone", "Sapi": "Sierra Leone", "Sherbro": "Sierra Leone", "Temne": "Sierra Leone",
    "Baga": "Guinea", "Nalu": "Guinea", "Kissi": "Guinea", "Toma": "Guinea", "Loma": "Guinea",
    "Bidjogo": "Guinea-Bissau", "Bijago": "Guinea-Bissau", "Wolof": "Senegal", "Diola": "Senegal",
    "Kongo": "Democratic Republic of the Congo", "Luba": "Democratic Republic of the Congo",
    "Kuba": "Democratic Republic of the Congo", "Songye": "Democratic Republic of the Congo",
    "Lega": "Democratic Republic of the Congo", "Hemba": "Democratic Republic of the Congo",
    "Tabwa": "Democratic Republic of the Congo", "Pende": "Democratic Republic of the Congo",
    "Yaka": "Democratic Republic of the Congo", "Suku": "Democratic Republic of the Congo",
    "Mangbetu": "Democratic Republic of the Congo", "Zande": "Democratic Republic of the Congo",
    "Azande": "Democratic Republic of the Congo", "Lulua": "Democratic Republic of the Congo",
    "Salampasu": "Democratic Republic of the Congo", "Mbole": "Democratic Republic of the Congo",
    "Bembe": "Democratic Republic of the Congo", "Ngbandi": "Democratic Republic of the Congo",
    "Chokwe": "Angola", "Ovimbundu": "Angola", "Lwena": "Angola",
    "Fang": "Gabon", "Kota": "Gabon", "Punu": "Gabon", "Tsogo": "Gabon", "Mahongwe": "Gabon",
    "Teke": "Republic of the Congo", "Vili": "Republic of the Congo", "Kuyu": "Republic of the Congo",
    "Bamileke": "Cameroon", "Bamum": "Cameroon", "Bamoum": "Cameroon", "Duala": "Cameroon",
    "Mambila": "Cameroon", "Sao": "Chad",
    "Makonde": "Tanzania", "Nyamwezi": "Tanzania", "Zaramo": "Tanzania", "Swahili": "Kenya",
    "Maasai": "Kenya", "Masai": "Kenya", "Kikuyu": "Kenya", "Turkana": "Kenya", "Giriama": "Kenya",
    "Ganda": "Uganda", "Baganda": "Uganda", "Amhara": "Ethiopia", "Oromo": "Ethiopia",
    "Konso": "Ethiopia", "Nuba": "Sudan", "Dinka": "South Sudan", "Nuer": "South Sudan",
    "Malagasy": "Madagascar", "Sakalava": "Madagascar", "Mahafaly": "Madagascar",
    "Shona": "Zimbabwe", "Lozi": "Zambia", "Chewa": "Malawi",
    "Zulu": "South Africa", "Xhosa": "South Africa", "Ndebele": "South Africa", "Tsonga": "South Africa",
    "Venda": "South Africa", "Sotho": "Lesotho", "Tswana": "Botswana", "Herero": "Namibia",
    "Ovambo": "Namibia", "Swazi": "Eswatini",
}

SUBREGIONS: dict[str, str] = {
    "West Africa": WEST, "Western Africa": WEST, "Guinea Coast": WEST, "Western Sudan": WEST,
    "Central Africa": CENTRAL, "Equatorial Africa": CENTRAL, "Middle Africa": CENTRAL,
    "East Africa": EAST, "Eastern Africa": EAST, "Horn of Africa": EAST,
    "Southern Africa": SOUTHERN, "Sub-Saharan Africa": GENERIC, "Subsaharan Africa": GENERIC,
}

# Places whose names contain an African name but are elsewhere.
_EXCLUDE = re.compile(r"\b(Papua New Guinea|New Guinea|Guinea pig)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Classification:
    country: str | None
    subregion: str
    matched: str


def _build_patterns() -> list[tuple[re.Pattern[str], str | None, str | None, str]]:
    entries: list[tuple[str, str | None, str | None]] = []
    for name, region in COUNTRIES.items():
        entries.append((name, name, region))
    for alias, country in ALIASES.items():
        entries.append((alias, country, COUNTRIES[country]))
    for culture, country in CULTURES.items():
        entries.append((culture, country, COUNTRIES[country]))
    for name, region in SUBREGIONS.items():
        entries.append((name, None, region))
    # Bare "Congo" is ambiguous between the two Congos.
    entries.append(("Congo", None, CENTRAL))
    # Longest names first so "Democratic Republic of the Congo" wins over "Republic of the Congo".
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return [
        (re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", re.IGNORECASE), country, region, name)
        for name, country, region in entries
    ]


_PATTERNS = _build_patterns()


def classify(*fields: str | None) -> Classification | None:
    """Return where in sub-Saharan Africa the first matching field points, or None.

    Fields are tried in order, so pass the most reliable one (country) first.
    """
    for text in fields:
        if not text:
            continue
        cleaned = _EXCLUDE.sub(" ", text)
        for pattern, country, region, name in _PATTERNS:
            if pattern.search(cleaned):
                return Classification(country=country, subregion=region or GENERIC, matched=name)
    return None


def is_sub_saharan(*fields: str | None) -> bool:
    return classify(*fields) is not None
