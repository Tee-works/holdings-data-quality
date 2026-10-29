import json

from hdq.parse import iter_holdings, parse_primary, read_filing
from hdq.sample import build_history


def test_prefixed_and_default_namespaces_parse_the_same(settings):
    prefixed, plain = [], []
    for folder in sorted(settings.raw_dir.iterdir()):
        text = (folder / "infotable.xml").read_text()
        (prefixed if "ns1:" in text else plain).append(folder)
    assert prefixed and plain
    for folder in prefixed + plain:
        rows = list(iter_holdings(folder / "infotable.xml", folder.name))
        assert rows and all(r["cusip"] and r["value"] is not None for r in rows)
        assert {"voting_sole", "voting_none", "investment_discretion"} <= rows[0].keys()


def test_primary_doc_amendment_fields(settings):
    restated = next(f for f in build_history() if f.amendment_type == "RESTATEMENT").accession
    meta = json.loads((settings.raw_dir / restated / "meta.json").read_text())
    filing, managers = parse_primary(settings.raw_dir / restated / "primary_doc.xml", meta)
    assert filing["is_amendment"] and filing["amendment_type"] == "RESTATEMENT"
    assert str(filing["period_of_report"]) == "2023-03-31"
    assert [m["sequence_number"] for m in managers] == [1, 2]


def test_values_are_kept_as_filed_and_converted_in_sql(settings, con):
    folder = sorted(settings.raw_dir.iterdir())[0]  # 2022Q3, filed in thousands
    filing, _, rows = read_filing(folder)
    raw, usd = con.execute(
        "select sum(value), sum(value_usd) from holding where accession = ?", [filing["accession"]]
    ).fetchone()
    assert raw == sum(r["value"] for r in rows)
    assert usd == raw * 1000


def test_amendments_resolve_to_one_current_version_per_quarter(con):
    roles = con.execute(
        "select f.period_label, f.form, v.version_role from filing as f "
        "join filing_version as v using (accession) order by f.period_of_report, f.filed_date"
    ).fetchall()
    assert ("2023Q1", "13F-HR", "superseded") in roles
    assert ("2023Q1", "13F-HR/A", "base") in roles
    assert ("2023Q2", "13F-HR/A", "added") in roles
    bases = [r for r in roles if r[2] == "base"]
    assert len(bases) == len({r[0] for r in roles})
    superseded_lines = con.execute(
        "select count(*) from current_holding where version_role = 'superseded'"
    ).fetchone()[0]
    assert superseded_lines == 0
