import pytest

from app.regions import CENTRAL, EAST, GENERIC, WEST, classify
from app.services.money import parse_estimate, parse_money
from app.services.provenance import parse_provenance


@pytest.mark.parametrize(
    "fields, country, region",
    [
        (("Nigeria",), "Nigeria", WEST),
        (("Edo peoples",), "Nigeria", WEST),
        (("Kingdom of Benin",), "Nigeria", WEST),
        (("Republic of Benin",), "Benin", WEST),
        (("Dahomey",), "Benin", WEST),
        (("Democratic Republic of the Congo",), "Democratic Republic of the Congo", CENTRAL),
        (("Republic of the Congo",), "Republic of the Congo", CENTRAL),
        (("Congo",), None, CENTRAL),
        (("Guinea-Bissau",), "Guinea-Bissau", WEST),
        (("Equatorial Guinea",), "Equatorial Guinea", CENTRAL),
        (("Central Africa, Democratic Republic of the Congo, Luba peoples",), "Democratic Republic of the Congo", CENTRAL),
        (("Abyssinia",), "Ethiopia", EAST),
        (("West Africa",), None, WEST),
        (("Sub-Saharan Africa",), None, GENERIC),
        ((None, "Yoruba"), "Nigeria", WEST),
    ],
)
def test_classify_sub_saharan(fields, country, region):
    result = classify(*fields)
    assert result is not None
    assert result.country == country
    assert result.subregion == region


@pytest.mark.parametrize(
    "text", ["Egypt", "Papua New Guinea", "New Guinea, Sepik River", "Morocco", "France", "Africa", "Nigerian-born artist's studio in Paris"]
)
def test_classify_rejects_non_sub_saharan(text):
    # "Nigerian" is not "Nigeria"/"Niger": we only match whole names.
    assert classify(text) is None


def test_niger_is_not_nigeria():
    assert classify("Niger").country == "Niger"
    assert classify("Nigeria").country == "Nigeria"


@pytest.mark.parametrize(
    "text, amount, currency",
    [
        ("£12,500", 12500.0, "GBP"),
        ("USD 1,200", 1200.0, "USD"),
        ("€ 3.200", 3200.0, "EUR"),
        ("EUR 3.200,50", 3200.5, "EUR"),
        ("US$ 45k", 45000.0, "USD"),
        ("1 250 000 CHF", 1250000.0, "CHF"),
        ("₦2,000,000", 2000000.0, "NGN"),
        ("12.5", 12.5, None),
    ],
)
def test_parse_money(text, amount, currency):
    assert parse_money(text) == (amount, currency)


def test_parse_estimate():
    assert parse_estimate("Estimate: £3,000 - £5,000") == (3000.0, 5000.0, "GBP")
    assert parse_estimate("2.000–3.000 €") == (2000.0, 3000.0, "EUR")
    assert parse_estimate("on request") == (None, None, None)
    assert parse_estimate("1,000", "USD") == (1000.0, 1000.0, "USD")


def test_parse_provenance():
    text = (
        "Taken from the royal palace, Benin City, during the British punitive expedition, 1897; "
        "Captain A. Example, London, by 1899; by descent to his son; "
        "sold, Sotheby's, London, 12 June 1975, lot 120, £8,000, to Private collection, Paris; "
        "given to the Museum, 1985 [1]."
    )
    events, sales = parse_provenance(text)
    assert [e.event_type for e in events] == ["looted", "transferred", "inherited", "sold", "donated"]
    assert events[0].location == "Benin City"
    assert events[0].year_start == 1897
    assert events[1].holder_name == "Captain A. Example"
    assert events[3].holder_kind == "private_collection"
    assert events[4].year_start == 1985
    assert len(sales) == 1
    sale = sales[0]
    assert sale.auction_house == "Sotheby's"
    assert sale.lot_number == "120"
    assert sale.sale_year == 1975
    assert (sale.price, sale.currency) == (8000.0, "GBP")
    assert sale.location == "London"


def test_parse_provenance_empty():
    assert parse_provenance(None) == ([], [])
