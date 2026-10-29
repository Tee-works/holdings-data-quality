"""Run the same controls on Snowflake and prove the results match DuckDB.

    pip install -e ".[snowflake]"
    export SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...   # or SNOWFLAKE_AUTHENTICATOR=externalbrowser
    export SNOWFLAKE_WAREHOUSE=COMPUTE_WH                                    # optional: SNOWFLAKE_ROLE, _DATABASE, _SCHEMA
    hdq demo            # or hdq all, for the real filings
    hdq snowflake       # add --sample after `hdq demo`

Steps:
1. Copy the raw tables (exactly as loaded from the SEC documents) from the DuckDB
   warehouse into Snowflake.
2. Create the staging views and run every control from the same SQL files, rendered
   for Snowflake (src/hdq/dialect.py).
3. Reconcile the Snowflake results with the DuckDB results with TrueSet value_parity,
   per control and filing, and write the outcome to docs/snowflake-parity.md.

Credentials come from the environment only; nothing is written to the repository but
the parity report, which names no account.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from trueset import PandasBackend, Suite

from hdq.config import ROOT, SQL_DIR, Settings
from hdq.controls import load_controls, run_all
from hdq.dialect import render
from hdq.load import connect as duckdb_connect

RAW_TABLES = ["raw_filing", "raw_holding", "raw_other_manager", "raw_load_check", "ref_us_holiday"]
SNOWFLAKE_TYPES = {
    "VARCHAR": "varchar",
    "DATE": "date",
    "BOOLEAN": "boolean",
    "DOUBLE": "double",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "TIMESTAMP": "timestamp_ntz",
}
PARITY = {
    "suite": "duckdb_vs_snowflake",
    "checks": [
        {"type": "row_count_parity", "reference": "duckdb", "owner": "Data Engineering"},
        {
            "type": "value_parity",
            "key": "result_key",
            "columns": ["population", "exceptions", "explained", "status", "exception_value"],
            "reference": "duckdb",
            "owner": "Data Engineering",
            "description": "Every control gives the same result for every filing on both engines.",
        },
    ],
}


class SnowflakeEngine:
    """The two methods the control runner needs, on a Snowflake connection."""

    dialect = "snowflake"

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str) -> None:
        self.conn.cursor().execute(sql)

    def df(self, sql: str) -> pd.DataFrame:
        cur = self.conn.cursor()
        cur.execute(sql)
        df = cur.fetch_pandas_all()
        if df.columns.empty:  # an empty result can come back without a schema
            df = pd.DataFrame(columns=[d[0] for d in cur.description])
        return df


def connect_from_env():
    import snowflake.connector  # optional dependency: pip install -e ".[snowflake]"

    params = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE"),
        "role": os.environ.get("SNOWFLAKE_ROLE"),
    }
    if os.environ.get("SNOWFLAKE_AUTHENTICATOR"):
        params["authenticator"] = os.environ["SNOWFLAKE_AUTHENTICATOR"]
    else:
        params["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    return snowflake.connector.connect(**{k: v for k, v in params.items() if v})


def statements(sql: str) -> list[str]:
    """Split a script on semicolons that end a line of code (comments may contain them)."""
    out, buf = [], []
    for line in sql.splitlines():
        buf.append(line)
        if not line.lstrip().startswith("--") and line.rstrip().endswith(";"):
            out.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    tail = "\n".join(buf).strip()
    if tail and not all(ln.lstrip().startswith("--") for ln in tail.splitlines()):
        out.append(tail)
    return out


def _copy_table(duck, conn, engine: SnowflakeEngine, name: str) -> int:
    """Copy one DuckDB table into Snowflake with the same column types.

    Values travel as text and are cast on the Snowflake side, so no type is left to
    a file format's interpretation (dates in particular)."""
    from snowflake.connector import pandas_tools  # optional dependency

    cols = duck.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_name = ? order by ordinal_position",
        [name],
    ).fetchall()
    df = duck.execute(f"select * from {name}").df()
    as_text = {
        "DATE": lambda v: pd.Timestamp(v).strftime("%Y-%m-%d"),
        "TIMESTAMP": lambda v: pd.Timestamp(v).strftime("%Y-%m-%d %H:%M:%S"),
        "INTEGER": lambda v: str(int(v)),
        "BIGINT": lambda v: str(int(v)),
        "DOUBLE": lambda v: repr(float(v)),
    }
    text = df.astype(object).where(df.notna(), None)
    for col, typ in cols:
        fmt = as_text.get(typ.split("(")[0], str)
        text[col] = text[col].map(lambda v, f=fmt: None if v is None else f(v))
    text.columns = [c.upper() for c in text.columns]
    stage = f"LOAD_{name.upper()}"
    engine.execute(
        f"create or replace temporary table {stage} ("
        + ", ".join(f"{c.upper()} varchar" for c, _ in cols)
        + ")"
    )
    if len(text):
        pandas_tools.write_pandas(conn, text, stage, quote_identifiers=False)
    select = ", ".join(
        f"try_cast({c.upper()} as {SNOWFLAKE_TYPES[t.split('(')[0]]}) as {c}" for c, t in cols
    )
    engine.execute(f"create or replace table {name} as select {select} from {stage}")
    return len(df)


def _keyed(results: pd.DataFrame) -> pd.DataFrame:
    out = results.assign(
        result_key=results.control_id + "|" + results.accession,
        exception_value=results.exception_value.round(0),
    )
    out = out[["result_key", *PARITY["checks"][1]["columns"]]].astype(object)
    return out.where(out.notna(), None)


def run(settings: Settings, conn=None, report_dir: Path | None = None) -> dict:
    conn = conn or connect_from_env()
    engine = SnowflakeEngine(conn)
    database = os.environ.get("SNOWFLAKE_DATABASE", "HDQ")
    schema = os.environ.get("SNOWFLAKE_SCHEMA", "SAMPLE_DATA" if settings.sample else "SEC_13F")
    engine.execute(f"create database if not exists {database}")
    engine.execute(f"use database {database}")
    engine.execute(f"create schema if not exists {schema}")
    engine.execute(f"use schema {schema}")

    duck = duckdb_connect(settings.warehouse)
    try:
        copied = {t: _copy_table(duck, conn, engine, t) for t in RAW_TABLES}
        controls = load_controls()
        duck_results, _ = run_all(duck, controls)
    finally:
        duck.close()

    for stmt in statements(render((SQL_DIR / "staging.sql").read_text(), "snowflake")):
        engine.execute(stmt)
    sf_results, _ = run_all(engine, controls)

    parity = Suite.from_dict(PARITY).run(
        PandasBackend(_keyed(sf_results)),
        references={"duckdb": PandasBackend(_keyed(duck_results))},
    )
    report = _report(
        settings, copied, controls, duck_results, sf_results, parity, report_dir or ROOT / "docs"
    )
    return {"rows_copied": copied, "parity": parity.passed, "report": str(report)}


def _report(settings, copied, controls, duck_results, sf_results, parity, folder: Path) -> Path:
    by_control = (
        duck_results.groupby("control_id")[["population", "exceptions"]].sum()
        .join(
            sf_results.groupby("control_id")[["population", "exceptions"]].sum(),
            rsuffix="_sf",
        )
    )  # fmt: skip
    lines = [
        "# Same controls, two engines: DuckDB and Snowflake",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `hdq snowflake` on "
        f"{'the bundled synthetic sample' if settings.sample else 'the SEC filings'}. "
        "The raw tables were copied from DuckDB to Snowflake unchanged; staging and all "
        f"{len(controls)} controls then ran from the same SQL files on both engines.",
        "",
        f"**TrueSet parity: {'passed' if parity.passed else 'FAILED'}.**",
        "",
        "| TrueSet check | Status | Detail |",
        "|---|---|---|",
    ]
    for r in parity.results:
        lines.append(f"| {r.check} | {r.status.value} | {r.message or r.observed} |")
    lines += [
        "",
        "Rows copied: " + ", ".join(f"{t} {n:,}" for t, n in copied.items()) + ".",
        "",
        "| Control | Items checked (DuckDB / Snowflake) | Exceptions (DuckDB / Snowflake) |",
        "|---|---|---|",
    ]
    for cid, r in by_control.iterrows():
        lines.append(
            f"| {cid} | {int(r.population):,} / {int(r.population_sf):,} "
            f"| {int(r.exceptions):,} / {int(r.exceptions_sf):,} |"
        )
    path = folder / ("snowflake-parity-sample.md" if settings.sample else "snowflake-parity.md")
    path.write_text("\n".join(lines) + "\n")
    return path
