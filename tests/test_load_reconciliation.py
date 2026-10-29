"""The TrueSet reconciliation that C16 reports: warehouse against SEC document."""

import json

import duckdb
import pytest
from trueset import Suite

from hdq.config import CONTRACTS_DIR
from hdq.load import reconcile


@pytest.fixture()
def tampered(settings, tmp_path):
    """A writable copy of the warehouse, so a test can damage the load."""
    path = tmp_path / "w.duckdb"
    path.write_bytes(settings.warehouse.read_bytes())
    con = duckdb.connect(str(path))
    yield con
    con.close()


def _run(con, settings, accession):
    suite = Suite.from_yaml(CONTRACTS_DIR / "load_reconciliation.yml")
    folder = settings.raw_dir / accession
    meta = json.loads((folder / "meta.json").read_text())
    return {r["check_type"]: r for r in reconcile(con, folder, meta, None, suite)}


def _first_accession(con):
    return con.execute("select min(accession) from raw_filing").fetchone()[0]


def test_every_sample_filing_reconciles(run, con):
    rows = con.execute("select status, count(*) from raw_load_check group by status").fetchall()
    assert rows == [("pass", 2 * con.execute("select count(*) from raw_filing").fetchone()[0])]
    assert (run.results[run.results.control_id == "C16"].status == "pass").all()


def test_a_changed_value_is_caught(tampered, settings):
    acc = _first_accession(tampered)
    tampered.execute(
        "update raw_holding set value = value + 1 where accession = ? and line_no = 7", [acc]
    )
    out = _run(tampered, settings, acc)
    assert out["row_count_parity"]["status"] == "pass"
    assert out["value_parity"]["status"] == "fail"
    assert '"mismatched_values": 1' in out["value_parity"]["observed"]


def test_a_dropped_and_a_duplicated_line_are_caught(tampered, settings):
    acc = _first_accession(tampered)
    tampered.execute("delete from raw_holding where accession = ? and line_no = 3", [acc])
    tampered.execute(
        "insert into raw_holding select * from raw_holding where accession = ? and line_no = 4",
        [acc],
    )
    out = _run(tampered, settings, acc)
    assert out["row_count_parity"]["status"] == "pass"  # counts alone can hide it...
    observed = out["value_parity"]["observed"]
    assert '"only_in_reference": 1' in observed and '"duplicate_keys_primary": 1' in observed


def test_an_unreadable_document_is_recorded_and_the_run_carries_on(tmp_path):
    from hdq import load, sample
    from hdq.config import Settings

    s = Settings.from_env(base=tmp_path, sample=True)
    sample.write_sample(s.raw_dir)
    broken = sorted(s.raw_dir.iterdir())[1]
    (broken / "infotable.xml").write_text("<informationTable><infoTable><value>12x</value>")
    out = load.build(s)
    assert out["filings"] == 7 and out["load_problems"] == 1
    con = duckdb.connect(str(s.warehouse), read_only=True)
    status = con.execute(
        "select check_type, status from raw_load_check where accession = ?", [broken.name]
    ).fetchall()
    assert status == [("parse_infotable", "error")]
    assert con.execute("select count(*) from raw_filing").fetchone()[0] == 7
