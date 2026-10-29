"""The same control SQL on Snowflake.

Two levels of evidence, both runnable without an account:
1. Every rendered control and staging statement parses as Snowflake SQL (sqlglot).
2. The whole Snowflake path (copy raw tables, create views, run controls, TrueSet parity
   with DuckDB) runs against fakesnow, a Snowflake emulator, when it is installed.
A real account is the final check: `hdq snowflake` writes docs/snowflake-parity.md.
"""

import pytest
import sqlglot

from hdq.config import SQL_DIR
from hdq.controls import load_controls
from hdq.dialect import render
from hdq.snowflake import statements


@pytest.mark.parametrize("control", load_controls(), ids=lambda c: c.id)
def test_control_renders_to_valid_snowflake_sql(control):
    sql = control.render("snowflake")
    assert "regexp_full_match" not in sql and "'g')" not in sql
    sqlglot.parse_one(sql, read="snowflake")


def test_staging_renders_to_valid_snowflake_sql():
    stmts = statements(render((SQL_DIR / "staging.sql").read_text(), "snowflake"))
    assert len(stmts) == 6  # one per view
    for s in stmts:
        sqlglot.parse_one(s, read="snowflake")


def test_duckdb_and_snowflake_give_identical_results(settings, run, tmp_path):
    fakesnow = pytest.importorskip("fakesnow")
    import snowflake.connector

    from hdq import snowflake as sf

    with fakesnow.patch():
        conn = snowflake.connector.connect()
        out = sf.run(settings, conn=conn, report_dir=tmp_path)
    assert out["parity"], (tmp_path / "snowflake-parity-sample.md").read_text()
    assert out["rows_copied"]["raw_holding"] > 1000
