"""Load downloaded filings into DuckDB and create the staging views."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from trueset import DuckDBBackend, PandasBackend, Suite

from hdq.calendar import holiday_rows
from hdq.config import CONTRACTS_DIR, SQL_DIR, Settings
from hdq.dialect import render
from hdq.parse import iter_holdings, parse_primary
from hdq.reference import FIELDS, read_reference

RAW_FILING_COLUMNS = {
    "accession": "VARCHAR",
    "form": "VARCHAR",
    "filed_date": "DATE",
    "period_of_report": "DATE",
    "is_amendment": "BOOLEAN",
    "amendment_no": "DOUBLE",
    "amendment_type": "VARCHAR",
    "report_type": "VARCHAR",
    "manager_name": "VARCHAR",
    "other_managers_count": "DOUBLE",
    "table_entry_total": "DOUBLE",
    "table_value_total": "DOUBLE",
    "confidential_omitted": "BOOLEAN",
    "source_url": "VARCHAR",
    "infotable_sha256": "VARCHAR",
    "accepted_at": "TIMESTAMP",
}
RAW_HOLDING_COLUMNS = {
    "accession": "VARCHAR",
    "line_no": "INTEGER",
    "issuer_name": "VARCHAR",
    "title_of_class": "VARCHAR",
    "cusip": "VARCHAR",
    "figi": "VARCHAR",
    "value": "DOUBLE",
    "amount": "DOUBLE",
    "amount_type": "VARCHAR",
    "put_call": "VARCHAR",
    "investment_discretion": "VARCHAR",
    "other_manager": "VARCHAR",
    "voting_sole": "DOUBLE",
    "voting_shared": "DOUBLE",
    "voting_none": "DOUBLE",
}
RAW_LOAD_CHECK_COLUMNS = {
    "accession": "VARCHAR",
    "period_of_report": "DATE",
    "suite": "VARCHAR",
    "check_type": "VARCHAR",
    "status": "VARCHAR",
    "failing_rows": "INTEGER",
    "message": "VARCHAR",
    "observed": "VARCHAR",
    "owner": "VARCHAR",
}
RECONCILED = list(FIELDS)
HOLIDAY_COLUMNS = {"holiday_date": "DATE", "name": "VARCHAR"}
RAW_MANAGER_COLUMNS = {
    "accession": "VARCHAR",
    "sequence_number": "INTEGER",
    "name": "VARCHAR",
    "file_number": "VARCHAR",
}


def _create(con: duckdb.DuckDBPyConnection, name: str, columns: dict[str, str]) -> None:
    cols = ", ".join(f"{c} {t}" for c, t in columns.items())
    con.execute(f"create or replace table {name} ({cols})")


def _insert(con, name: str, columns: dict[str, str], rows: list[dict]) -> None:
    if not rows:
        return
    df = pd.DataFrame(rows, columns=list(columns))  # noqa: F841 (read by DuckDB below)
    con.execute(f"insert into {name} select * from df")


def _minimal_filing(meta: dict) -> dict:
    """What we know about a filing whose primary document could not be read."""
    row = dict.fromkeys(RAW_FILING_COLUMNS)
    row.update(
        accession=meta["accession"],
        form=meta["form"],
        filed_date=date.fromisoformat(meta["filed"]),
        period_of_report=date.fromisoformat(meta["period"]) if meta.get("period") else None,
        is_amendment=meta["form"].endswith("/A"),
        confidential_omitted=False,
    )
    return row


def _load_check(meta: dict, period, check: str, status: str, message: str = "", **kw) -> dict:
    return {
        "accession": meta["accession"],
        "period_of_report": period,
        "suite": kw.get("suite", "parse"),
        "check_type": check,
        "status": status,
        "failing_rows": kw.get("failing_rows"),
        "message": message,
        "observed": kw.get("observed"),
        "owner": kw.get("owner", "Data Engineering"),
    }


def build(settings: Settings) -> dict:
    """Load every downloaded filing. A document that cannot be read is recorded, not fatal:
    the run carries on and C16 reports the failure."""
    folders = sorted(p.parent for p in settings.raw_dir.glob("*/meta.json"))
    if not folders:
        raise SystemExit(f"no filings in {settings.raw_dir}; run `hdq fetch` (or `hdq sample`)")
    settings.warehouse.parent.mkdir(parents=True, exist_ok=True)
    if settings.warehouse.exists():
        settings.warehouse.unlink()
    suite = Suite.from_yaml(CONTRACTS_DIR / "load_reconciliation.yml")
    con = duckdb.connect(str(settings.warehouse))
    lines, errors = 0, 0
    try:
        for name, cols in (
            ("raw_filing", RAW_FILING_COLUMNS),
            ("raw_holding", RAW_HOLDING_COLUMNS),
            ("raw_other_manager", RAW_MANAGER_COLUMNS),
            ("raw_load_check", RAW_LOAD_CHECK_COLUMNS),
        ):
            _create(con, name, cols)
        for folder in folders:
            meta = json.loads((folder / "meta.json").read_text())
            checks = []
            try:
                filing, managers = parse_primary(folder / "primary_doc.xml", meta)
            except Exception as exc:  # noqa: BLE001 (any unreadable document is recorded)
                filing, managers = _minimal_filing(meta), []
                checks.append(
                    _load_check(
                        meta, filing["period_of_report"], "parse_primary", "error", str(exc)
                    )
                )
            filing["accepted_at"] = meta.get("accepted")
            try:
                holdings = list(iter_holdings(folder / "infotable.xml", meta["accession"]))
            except Exception as exc:  # noqa: BLE001
                holdings = None
                checks.append(
                    _load_check(
                        meta, filing["period_of_report"], "parse_infotable", "error", str(exc)
                    )
                )
            _insert(con, "raw_filing", RAW_FILING_COLUMNS, [filing])
            _insert(con, "raw_other_manager", RAW_MANAGER_COLUMNS, managers)
            if holdings is not None:
                _insert(con, "raw_holding", RAW_HOLDING_COLUMNS, holdings)
                lines += len(holdings)
                checks += reconcile(con, folder, meta, filing["period_of_report"], suite)
            errors += sum(c["status"] != "pass" for c in checks)
            _insert(con, "raw_load_check", RAW_LOAD_CHECK_COLUMNS, checks)

        _create(con, "ref_us_holiday", HOLIDAY_COLUMNS)
        _insert(
            con,
            "ref_us_holiday",
            HOLIDAY_COLUMNS,
            holiday_rows(2000, date.today().year + 2),
        )
        con.execute(render((SQL_DIR / "staging.sql").read_text(), "duckdb"))
    finally:
        con.close()
    return {"filings": len(folders), "lines": lines, "load_problems": errors}


def reconcile(
    con: duckdb.DuckDBPyConnection, folder, meta: dict, period, suite: Suite
) -> list[dict]:
    """TrueSet reconciliation for one filing: warehouse rows against an independent reading
    of the document (hdq.reference)."""
    accession = meta["accession"]
    try:
        source = read_reference(folder / "infotable.xml", accession)
    except Exception as exc:  # noqa: BLE001
        return [_load_check(meta, period, "reference_read", "error", str(exc))]
    con.execute(
        "create or replace temp table loaded as "
        f"select accession || '#' || line_no as line_key, {', '.join(RECONCILED)} "
        "from raw_holding where accession = ?",
        [accession],
    )
    result = suite.run(DuckDBBackend(con, "loaded"), references={"source": PandasBackend(source)})
    return [
        _load_check(
            meta,
            period,
            r.check,
            r.status.value,
            r.message,
            suite=result.name,
            failing_rows=r.failing_rows,
            observed=json.dumps(r.observed, default=str),
            owner=r.meta.owner,
        )
        for r in result.results
    ]


def connect(path: Path, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)
