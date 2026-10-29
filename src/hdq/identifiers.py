"""Check digits for the security identifiers that appear in 13F filings.

CUSIP: 9 characters, the last a modulus 10 "double add double" check digit.
FIGI: 12 characters, BBG-style prefix, the last a Luhn-style check digit over
character values (0-9 as is, A=10 ... Z=35).
"""

from __future__ import annotations

import re

_CUSIP_SPECIAL = {"*": 36, "@": 37, "#": 38}
_FIGI_RE = re.compile(r"^[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]$")
_FIGI_BAD_PREFIXES = {"BS", "BM", "GG", "GB", "GH", "KY", "VG"}


def _char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if c.isalpha():
        return ord(c.upper()) - ord("A") + 10
    if c in _CUSIP_SPECIAL:
        return _CUSIP_SPECIAL[c]
    raise ValueError(f"invalid character {c!r}")


def _luhn_like(body: str) -> int:
    total = 0
    for i, c in enumerate(body):
        v = _char_value(c)
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10


def cusip_check_digit(first8: str) -> int:
    return _luhn_like(first8)


def is_valid_cusip(cusip: str | None) -> bool:
    if not cusip or len(cusip) != 9 or not cusip[8].isdigit():
        return False
    try:
        return cusip_check_digit(cusip[:8].upper()) == int(cusip[8])
    except ValueError:
        return False


def is_valid_figi(figi: str | None) -> bool:
    if not figi:
        return False
    figi = figi.upper()
    if not _FIGI_RE.match(figi) or figi[:2] in _FIGI_BAD_PREFIXES:
        return False
    return _luhn_like(figi[:11]) == int(figi[11])
