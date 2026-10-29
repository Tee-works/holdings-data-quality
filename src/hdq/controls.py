"""Load control definitions and run them.

A control is one SQL file in controls/. Its header (YAML inside a /*--- ---*/
comment) says what it checks, who owns it, how severe a failure is and how to
triage it. The query returns one row per item checked:

    accession, period_of_report, entity, line_no, is_exception, value_usd, detail
    [, explained]   optional: true where the control recognised and cleared a case itself

The engine never interprets the SQL; adding a control is adding a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from hdq.config import CONTROLS_DIR
from hdq.dialect import render

HEADER = re.compile(r"/\*---\n(.*?)\n---\*/", re.S)
REQUIRED_KEYS = {
    "id",
    "name",
    "dimension",
    "severity",
    "scope",
    "owner",
    "description",
    "impact",
    "runbook",
}
DIMENSIONS = {"completeness", "accuracy", "validity", "consistency", "uniqueness", "timeliness"}
SEVERITIES = ["critical", "high", "medium", "low"]
SCOPES = {"filing", "holding", "period"}
COLUMNS = [
    "accession",
    "period_of_report",
    "entity",
    "line_no",
    "is_exception",
    "value_usd",
    "detail",
]
MAX_EXCEPTIONS_KEPT = 5000  # per control per filing, so one systemic fault cannot flood the outputs


@dataclass(frozen=True)
class Control:
    id: str
    name: str
    dimension: str
    severity: str
    scope: str
    owner: str
    description: str
    impact: str
    runbook: list[str]
    sql: str = field(repr=False)
    path: Path | None = None

    @property
    def query(self) -> str:
        """The control's SQL for DuckDB."""
        return self.render("duckdb")

    def render(self, dialect: str) -> str:
        return render(HEADER.sub("", self.sql).strip(), dialect)


def parse_control(path: Path) -> Control:
    text = path.read_text()
    match = HEADER.search(text)
    if not match:
        raise ValueError(f"{path.name}: missing /*--- ---*/ header")
    meta = yaml.safe_load(match.group(1))
    missing = REQUIRED_KEYS - set(meta)
    if missing:
        raise ValueError(f"{path.name}: header missing {sorted(missing)}")
    if meta["dimension"] not in DIMENSIONS:
        raise ValueError(f"{path.name}: unknown dimension {meta['dimension']!r}")
    if meta["severity"] not in SEVERITIES:
        raise ValueError(f"{path.name}: unknown severity {meta['severity']!r}")
    if meta["scope"] not in SCOPES:
        raise ValueError(f"{path.name}: unknown scope {meta['scope']!r}")
    if not path.stem.startswith(meta["id"] + "_"):
        raise ValueError(f"{path.name}: file name must start with the control id {meta['id']}")
    clean = {k: " ".join(v.split()) if isinstance(v, str) else v for k, v in meta.items()}
    return Control(**{k: clean[k] for k in REQUIRED_KEYS}, sql=text, path=path)


def load_controls(folder: Path = CONTROLS_DIR) -> list[Control]:
    controls = [parse_control(p) for p in sorted(folder.glob("C*.sql"))]
    ids = [c.id for c in controls]
    if len(set(ids)) != len(ids):
        raise ValueError(f"duplicate control ids: {ids}")
    return controls


def query_df(con, sql: str) -> pd.DataFrame:
    """Run SQL on DuckDB, or on any engine wrapper that offers .df(sql) and .dialect
    (see hdq.snowflake). Column names come back lower case either way."""
    df = con.df(sql) if hasattr(con, "dialect") else con.execute(sql).df()
    return df.rename(columns=str.lower)


def _dialect(con) -> str:
    return getattr(con, "dialect", "duckdb")


def _expected(con) -> dict[str, pd.DataFrame]:
    """Which filings each scope is accountable for, so a silent control shows as n/a."""
    q = """
        select f.accession, f.period_of_report, f.period_label, v.version_role
        from filing as f join filing_version as v using (accession)
    """
    filings = query_df(con, q)
    return {
        "filing": filings,
        "holding": filings[filings.version_role.isin(["base", "added"])],
        "period": filings[filings.version_role == "base"],
    }


def run_control(con, control: Control) -> pd.DataFrame:
    df = query_df(con, control.render(_dialect(con)))
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{control.id}: query must return {missing}")
    if "explained" not in df.columns:
        df["explained"] = False
    df["explained"] = df["explained"].fillna(False).astype(bool)
    df["is_exception"] = df["is_exception"].fillna(True).astype(bool)
    return df[[*COLUMNS, "explained"]]


def _status(population: int, exceptions: int, severity: str) -> str:
    if population == 0:
        return "not_applicable"
    if exceptions == 0:
        return "pass"
    return "fail" if severity in ("critical", "high") else "warn"


def run_all(con, controls: list[Control]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (results: one row per control per filing, findings: exception and explained rows)."""
    expected = _expected(con)
    results, findings = [], []
    for c in controls:
        rows = run_control(con, c)
        for f in expected[c.scope].itertuples():
            mine = rows[rows.accession == f.accession]
            exc = mine[mine.is_exception]
            results.append(
                {
                    "control_id": c.id,
                    "accession": f.accession,
                    "period_of_report": f.period_of_report,
                    "period_label": f.period_label,
                    "version_role": f.version_role,
                    "population": len(mine),
                    "exceptions": len(exc),
                    "explained": int(mine.explained.sum()),
                    "population_value": float(mine.value_usd.fillna(0).sum()),
                    "exception_value": float(exc.value_usd.fillna(0).sum()),
                    "status": _status(len(mine), len(exc), c.severity),
                }
            )
            keep = pd.concat(
                [
                    exc.head(MAX_EXCEPTIONS_KEPT).assign(kind="exception"),
                    mine[mine.explained & ~mine.is_exception].assign(kind="explained"),
                ]
            )
            if not keep.empty:
                findings.append(keep.assign(control_id=c.id, period_label=f.period_label))
    result_df = pd.DataFrame(results)
    finding_df = (
        pd.concat(findings, ignore_index=True)
        if findings
        else pd.DataFrame(columns=[*COLUMNS, "explained", "kind", "control_id", "period_label"])
    )
    return result_df, finding_df.drop(columns=["is_exception", "explained"])


def clear_value_share(
    con: duckdb.DuckDBPyConnection, findings: pd.DataFrame, controls: list[Control]
) -> pd.DataFrame:
    """Per period: share of reported value on lines with no exception of medium severity or above."""
    serious = {c.id for c in controls if c.scope == "holding" and c.severity != "low"}
    flagged = findings[
        (findings.kind == "exception")
        & findings.control_id.isin(serious)
        & findings.line_no.notna()
    ][["accession", "line_no"]].drop_duplicates()
    flagged = flagged.assign(line_no=flagged.line_no.astype(int))  # noqa: F841 (read by DuckDB)
    return (
        con.execute(
            """
        select
            h.period_of_report,
            h.period_label,
            count(*) as lines,
            sum(h.value_usd) as value_usd,
            count(f.line_no) as flagged_lines,
            coalesce(sum(case when f.line_no is not null then h.value_usd end), 0) as flagged_value_usd
        from current_holding as h
        left join flagged as f on h.accession = f.accession and h.line_no = f.line_no
        group by h.period_of_report, h.period_label
        order by h.period_of_report
        """
        )
        .df()
        .assign(clear_share=lambda d: 1 - d.flagged_value_usd / d.value_usd.where(d.value_usd > 0))
    )
