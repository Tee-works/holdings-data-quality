import re
from pathlib import Path

import duckdb
import pytest

from hdq.controls import load_controls, parse_control, run_control
from hdq.sample import PLANTED

# Exceptions the sample must produce, by control and quarter. Quarters not listed must be clean.
EXPECTED = {
    "C01": {"2023Q1": 1},
    "C02": {"2023Q1": 1},
    "C03": {"2023Q1": 1},
    "C04": {"2023Q1": 1},
    "C05": {"2023Q1": 1},
    "C06": {"2023Q1": 1},
    "C07": {"2023Q1": 1},
    "C08": {"2023Q1": 1},
    "C09": {"2023Q1": 3},  # every line for the CUSIP is listed
    "C10": {"2023Q1": 2},  # two lines for one entity disagree; neither can be singled out
    "C11": {"2023Q2": 1, "2023Q3": "many"},  # the unit error in 2023Q3 moves every price
    "C12": {"2023Q3": 1},
    "C13": {"2023Q2": 1},
    "C14": {"2023Q1": 1},
    "C15": {"2023Q1": 1, "2023Q3": "some"},  # unit error pushes cheap shares under 1 cent
    "C16": {},  # the load is faithful; see test_load_reconciliation.py for the failure cases
    "C17": {"2023Q1": 1},  # only the odd one of three entities
    "C18": {},  # the sample's new-holdings amendment is genuinely new; see the tampering test
    "C19": {},  # the sample's two managers overlap only partly; see the double-count tests
}


def test_every_control_is_covered():
    assert {c.id for c in load_controls()} == set(EXPECTED)
    assert set(PLANTED) == {k for k, v in EXPECTED.items() if v}


@pytest.mark.parametrize("control_id", sorted(EXPECTED))
def test_control_finds_its_planted_defect_and_nothing_else(run, control_id):
    r = run.results[run.results.control_id == control_id]
    found = r[r.exceptions > 0].groupby("period_label").exceptions.sum().to_dict()
    expected = EXPECTED[control_id]
    assert set(found) == set(expected), f"{control_id}: exceptions in {found}"
    for period, n in expected.items():
        if isinstance(n, int):
            assert found[period] == n
    if control_id in PLANTED:
        assert PLANTED[control_id][0] in found


def test_split_is_cleared_and_jump_is_not(run):
    f = run.findings[(run.findings.control_id == "C11") & (run.findings.period_label == "2023Q2")]
    assert (f.kind == "explained").sum() == 1
    assert "4-for-1 split" in f[f.kind == "explained"].detail.iloc[0]
    assert (
        "x4.9" in f[f.kind == "exception"].detail.iloc[0]
        or "x5.0" in f[f.kind == "exception"].detail.iloc[0]
    )


def test_unit_conversion_is_what_keeps_2022q4_clean(run, con):
    """The 2022Q3 report is in thousands and 2022Q4 in dollars. Converted, C12 passes;
    fed the values as filed, the same control fails."""
    r = run.results
    assert r[(r.control_id == "C12") & (r.period_label == "2022Q4")].status.item() == "pass"

    c12 = next(c for c in load_controls() if c.id == "C12")
    rows = run_control(con, c12)
    q4 = rows[rows.period_of_report.astype(str) == "2022-12-31"].iloc[0]
    raw_ratio = float(re.search(r"before unit conversion: x([\d.]+)", q4.detail).group(1))
    assert 500 < raw_ratio < 2000  # about a thousandfold as filed

    as_filed = c12.query.replace(
        "from current_holding", "from (select * replace (value as value_usd) from current_holding)"
    )
    unconverted = con.execute(as_filed).df()
    assert unconverted[unconverted.period_of_report.astype(str) == "2022-12-31"].is_exception.item()


def test_period_controls_are_not_applicable_in_the_first_quarter(run):
    first = run.results[run.results.period_label == "2022Q3"].set_index("control_id").status
    assert first["C11"] == first["C12"] == "not_applicable"


def test_superseded_report_is_checked_as_a_document_only(run):
    r = run.results
    superseded = r[r.version_role == "superseded"]
    assert set(superseded.control_id) == {"C01", "C02", "C13", "C16", "C18", "C19"}


def test_every_control_has_a_usable_runbook():
    for c in load_controls():
        assert len(c.runbook) >= 3, c.id
        assert c.owner and c.impact and c.description


def test_bad_headers_are_rejected(tmp_path: Path):
    bad = tmp_path / "C99_x.sql"
    bad.write_text("select 1")
    with pytest.raises(ValueError, match="header"):
        parse_control(bad)
    bad.write_text("/*---\nid: C99\nname: x\ndimension: vibes\n---*/\nselect 1")
    with pytest.raises(ValueError, match="missing"):
        parse_control(bad)


def _control(cid):
    return next(c for c in load_controls() if c.id == cid)


@pytest.mark.parametrize(
    ("price_ratio", "share_ratio", "expected"),
    [
        (0.25, 4.0, "explained"),  # clean 4-for-1
        (0.1, 13.0, "explained"),  # 10-for-1 while the fund grew 30% (index inflows)
        (1 / 15, 11.0, "explained"),  # 15-for-1 with the position shrinking
        (10.0, 0.1, "explained"),  # 1-for-10 consolidation
        (5.0, 1.0, "exception"),  # price jump, no share change
        (0.2, 1.0, "exception"),  # price collapse, no share change
        (1.5, 1.0, "clear"),  # ordinary move
    ],
)
def test_split_rule_tolerates_position_changes(price_ratio, share_ratio, expected):
    con = duckdb.connect()
    con.execute(
        "create view security_position as select * from (values "
        "('a', date '2025-03-31', 1, 'X', 100.0, 1000.0, 100000.0, 'C'),"
        f"('a', date '2025-06-30', 2, 'X', {100 * price_ratio}, {1000 * share_ratio}, "
        f"{100 * price_ratio * 1000 * share_ratio}, 'C')"
        ") as t(accession, period_of_report, period_seq, cusip, implied_price, shares, value_usd, issuer_name)"
    )
    row = con.execute(f"select is_exception, explained from ({_control('C11').query})").fetchone()
    got = "exception" if row[0] else "explained" if row[1] else "clear"
    assert got == expected


def test_new_holdings_amendment_that_repeats_the_report_is_caught(settings, tmp_path):
    path = tmp_path / "w.duckdb"
    path.write_bytes(settings.warehouse.read_bytes())
    con = duckdb.connect(str(path))
    amend, base = con.execute(
        "select v.accession, v.base_accession from filing_version as v where v.version_role = 'added'"
    ).fetchone()
    assert (
        con.execute(f"select bool_or(is_exception) from ({_control('C18').query})").fetchone()[0]
        is False
    )
    con.execute(
        "insert into raw_holding select * replace (? as accession, line_no + 100 as line_no) "
        "from raw_holding where accession = ?",
        [amend, base],
    )
    rows = con.execute(f"select accession, is_exception from ({_control('C18').query})").fetchall()
    assert (amend, True) in rows


def test_deadline_moves_past_weekends_and_federal_holidays(con):
    """Q4 2025: day 45 is Sunday 15 Feb 2026, Monday 16 Feb is Presidents' Day, due Tuesday 17th."""
    con.execute(
        "create temp table filing as select * replace (date '2025-12-31' as period_of_report, "
        "date '2026-02-17' as filed_date, false as is_amendment) from main.filing limit 1"
    )
    detail = con.execute(f"select detail, is_exception from ({_control('C13').query})").fetchone()
    assert detail == ("filed 2026-02-17, computed 45-day date 2026-02-17", False)


def _c19(lines):
    """Run C19 on a one-filing book given as (manager, cusip, shares) tuples."""
    con = duckdb.connect()
    rows = ",".join(
        f"('a', date '2024-03-31', '{m}', '{c}', null, {s}, {s * 10.0})" for m, c, s in lines
    )
    con.execute(
        f"create view holding as select * from (values {rows}) as t"
        "(accession, period_of_report, other_manager, cusip, put_call, amount, value_usd)"
    )
    con.execute(
        "create view filing as select 'a' as accession, date '2024-03-31' as period_of_report"
    )
    return con.execute(_control("C19").query).df()


def test_double_count_is_caught_when_one_book_sits_inside_another():
    parent = [("4", f"C{i:03d}", 1000.0) for i in range(200)]
    child = [("2", f"C{i:03d}", 400.0) for i in range(80)]  # every position also under "4"
    r = _c19(parent + child).set_index("entity")
    assert r.loc["other manager 2", "is_exception"]
    assert r.loc["other manager 2", "value_usd"] == 80 * 4000.0
    assert "80 of 80" in r.loc["other manager 2", "detail"]
    assert not r.loc["other manager 4", "is_exception"]


def test_ordinary_index_overlap_is_not_a_double_count():
    parent = [("4", f"C{i:03d}", 1000.0) for i in range(200)]
    child = [("2", f"C{i:03d}", 400.0) for i in range(60)] + [
        ("2", f"D{i:03d}", 400.0) for i in range(40)
    ]
    r = _c19(parent + child).set_index("entity")
    assert not r.is_exception.any()  # 60% overlap, as between L&G entities in a normal quarter


def test_shared_discretion_lines_are_not_compared():
    book = [("4", f"C{i:03d}", 1000.0) for i in range(100)] + [
        ("4,2", f"C{i:03d}", 400.0) for i in range(100)
    ]
    assert not _c19(book).is_exception.any()
