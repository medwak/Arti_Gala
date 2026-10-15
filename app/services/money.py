"""Parse prices and estimates as they appear on auction pages."""

from __future__ import annotations

import re

# Longest symbols first so "US$" is not read as "$".
_SYMBOLS: list[tuple[str, str]] = [
    ("US$", "USD"), ("HK$", "HKD"), ("CA$", "CAD"), ("A$", "AUD"), ("GH₵", "GHS"), ("KSh", "KES"),
    ("$", "USD"), ("£", "GBP"), ("€", "EUR"), ("¥", "JPY"), ("₦", "NGN"), ("₵", "GHS"),
]
_CODES = {
    "USD", "GBP", "EUR", "CHF", "HKD", "CAD", "AUD", "JPY", "ZAR", "NGN", "KES", "GHS", "XOF", "XAF",
    "SEK", "NOK", "DKK", "CNY",
}
_CODE_RE = re.compile(r"\b(" + "|".join(sorted(_CODES)) + r")\b")
_NUMBER_RE = re.compile(r"\d[\d,.\s  ']*\d(?:\s?[kKmM]\b)?|\d(?:\s?[kKmM]\b)?")


def detect_currency(text: str, default: str | None = None) -> str | None:
    match = _CODE_RE.search(text.upper())
    if match:
        return match.group(1)
    for symbol, code in _SYMBOLS:
        if symbol in text:
            return code
    return default


def _to_number(token: str) -> float | None:
    token = token.strip()
    multiplier = 1.0
    if token and token[-1] in "kKmM":
        multiplier = 1_000.0 if token[-1] in "kK" else 1_000_000.0
        token = token[:-1].strip()
    token = re.sub(r"[\s  ']", "", token)
    if not token:
        return None
    if "," in token and "." in token:
        # Whichever separator comes last is the decimal mark.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        parts = token.split(sep)
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            token = "".join(parts)  # thousands separators
        else:
            token = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(token) * multiplier
    except ValueError:
        return None


def parse_amounts(text: str) -> list[float]:
    amounts = []
    for token in _NUMBER_RE.findall(text):
        value = _to_number(token)
        if value is not None:
            amounts.append(value)
    return amounts


_MARK = "|".join([re.escape(s) for s, _ in _SYMBOLS] + sorted(_CODES))
_NUM = r"\d[\d,.\s  ']*\d(?:\s?[kKmM]\b)?|\d(?:\s?[kKmM]\b)?"
_NEAR_MARK_RE = re.compile(rf"(?:{_MARK})\s?({_NUM})|({_NUM})\s?(?:{_MARK})")


def parse_money(text: str | None, default_currency: str | None = None) -> tuple[float | None, str | None]:
    """Parse one price such as "£12,500" or "EUR 3.200". Returns (amount, currency).

    When the text holds several numbers, the one next to a currency mark wins.
    """
    if not text:
        return None, None
    near = _NEAR_MARK_RE.search(text)
    if near:
        amount = _to_number(near.group(1) or near.group(2))
    else:
        amounts = parse_amounts(text)
        amount = amounts[0] if amounts else None
    return amount, detect_currency(text, default_currency)


def parse_estimate(
    text: str | None, default_currency: str | None = None
) -> tuple[float | None, float | None, str | None]:
    """Parse an estimate such as "USD 1,000 - 1,500". Returns (low, high, currency)."""
    if not text:
        return None, None, None
    amounts = parse_amounts(text)
    currency = detect_currency(text, default_currency)
    if not amounts:
        return None, None, currency
    if len(amounts) == 1:
        return amounts[0], amounts[0], currency
    low, high = amounts[0], amounts[1]
    return min(low, high), max(low, high), currency
