import random
import string

import duckdb
import pytest

from hdq.controls import load_controls
from hdq.identifiers import cusip_check_digit, is_valid_cusip, is_valid_figi


@pytest.mark.parametrize("cusip", ["037833100", "594918104", "02079K305", "88160R101"])
def test_known_valid_cusips(cusip):
    assert is_valid_cusip(cusip)


@pytest.mark.parametrize("cusip", ["037833101", "59491810", "0378331000", None, "", "03783310X"])
def test_invalid_cusips(cusip):
    assert not is_valid_cusip(cusip)


@pytest.mark.parametrize("figi", ["BBG000B9XRY4", "BBG000BPH459"])
def test_known_valid_figis(figi):
    assert is_valid_figi(figi)


@pytest.mark.parametrize(
    "figi", ["BBG000B9XRY5", "BBG000B9XRY", "BAG000B9XRY4", "GGG000B9XRY4", None]
)
def test_invalid_figis(figi):
    assert not is_valid_figi(figi)


def test_sql_check_digit_agrees_with_python():
    """C03 is written in plain SQL; the Python implementation is the oracle."""
    rng = random.Random(1)
    alphabet = string.digits + string.ascii_uppercase
    cusips = []
    for _ in range(400):
        body = "".join(rng.choice(alphabet) for _ in range(8))
        good = body + str(cusip_check_digit(body))
        cusips.append(good if rng.random() < 0.5 else body + str((int(good[8]) + 1) % 10))
    cusips += ["ABC", "12345678*", "0378331O0"]

    con = duckdb.connect()
    con.execute("create table raw_holding (accession varchar, line_no int, cusip varchar)")
    con.executemany("insert into raw_holding values ('a', ?, ?)", list(enumerate(cusips)))
    con.execute(
        """
        create view current_holding as
        select *, date '2024-03-31' as period_of_report, 'X' as issuer_name, 1.0 as value_usd
        from raw_holding
        """
    )
    c03 = next(c for c in load_controls() if c.id == "C03")
    got = dict(con.execute(f"select line_no, is_exception from ({c03.query})").fetchall())
    assert got == {i: not is_valid_cusip(c) for i, c in enumerate(cusips)}
