"""Build the static dashboard from the reporting outputs in site/data."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from hdq.config import TEMPLATES_DIR, Settings
from hdq.controls import load_controls

STATUS_RANK = {"fail": 3, "warn": 2, "pass": 1, "not_applicable": 0}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
QUARTERS_SHOWN = 8
FINDINGS_SHOWN = 10


def money(v) -> str:
    if v is None or pd.isna(v):
        return "n/q"
    v = float(v)
    for size, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(v) >= size:
            return f"${v / size:,.1f}{suffix}"
    return f"${v:,.0f}"


def nice_axis(peak: float, n: int = 4) -> tuple[float, list[float]]:
    """A round upper bound and evenly spaced ticks for a share (0 to 1)."""
    steps = [m * 10**e for e in range(-6, 1) for m in (1, 2, 2.5, 5)]
    step = next((s for s in steps if s * n >= peak), 0.25)
    return step * n, [step * i for i in range(n + 1)]


def _latest_results(data) -> pd.DataFrame:
    r = pd.read_csv(data / "fact_control_result.csv")
    return r[r.run_id == r.run_id.max()]


def context(settings: Settings) -> dict:
    data = settings.site_dir / "data"
    run = json.loads((data / "run.json").read_text())
    controls = load_controls()
    results = _latest_results(data)
    filings = pd.read_csv(data / "dim_filing.csv")
    findings = pd.read_csv(data / "fact_finding.csv")
    kpis = pd.read_csv(data / "fact_period_kpi.csv")
    issues = (
        pd.read_csv(data / "fact_issue.csv")
        if (data / "fact_issue.csv").stat().st_size > 1
        else pd.DataFrame()
    )

    periods = sorted(results.period_label.unique())
    shown = periods[-QUARTERS_SHOWN:]
    latest = periods[-1]

    grid = []
    for c in controls:
        cells = []
        for p in shown:
            rows = results[(results.control_id == c.id) & (results.period_label == p)]
            if rows.empty:
                cells.append({"status": "not_applicable", "tip": f"{c.id} {p}: not applicable"})
                continue
            worst = max(rows.status, key=STATUS_RANK.get)
            parts = [
                f"{r.accession} ({r.version_role}): {r.status}, {r.exceptions} of {r.population}"
                + (
                    f", {money(r.exception_value)} affected"
                    if r.exceptions and r.exception_value
                    else ""
                )
                for r in rows.itertuples()
            ]
            cells.append({"status": worst, "tip": f"{c.id} {p}\n" + "\n".join(parts)})
        grid.append({"c": c, "cells": cells})

    latest_rows = results[results.period_label == latest]
    failing_now = sorted(
        {r.control_id for r in latest_rows.itertuples() if r.status in ("fail", "warn")}
    )
    k = kpis.set_index("period_label")
    base_latest = filings[(filings.period_label == latest) & (filings.version_role == "base")].iloc[
        0
    ]

    issue_rows = []
    if not issues.empty:
        issues = issues.assign(
            _open=issues.status.map({"open": 0, "triaged": 1, "resolved": 2, "withdrawn": 3}),
            _sev=issues.severity.map(SEVERITY_RANK),
        ).sort_values(
            ["_open", "_sev", "period_label", "control_id"], ascending=[True, True, False, True]
        )
        issues = issues.astype(object).where(issues.notna(), None)
        issue_rows = issues.to_dict("records")
    open_issues = [i for i in issue_rows if i["status"] == "open"]

    per_control = {}
    for c in controls:
        f = findings[findings.control_id == c.id]
        exc = f[f.kind == "exception"].sort_values("value_usd", ascending=False, na_position="last")
        per_control[c.id] = {
            "exceptions": len(exc),
            "explained": int((f.kind == "explained").sum()),
            "top": exc.head(FINDINGS_SHOWN).to_dict("records"),
            "explained_rows": f[f.kind == "explained"].head(5).to_dict("records"),
            "latest": latest_rows[latest_rows.control_id == c.id].to_dict("records"),
        }

    report_level = {c.id for c in controls if c.scope in ("filing", "period")}
    chart = [
        {
            "label": p,
            "share": float(k.loc[p, "clear_share"]) if p in k.index else None,
            "value": float(k.loc[p, "value_usd"]) if p in k.index else None,
            "flagged": float(k.loc[p, "flagged_value_usd"]) if p in k.index else None,
            "fail": sorted(
                {
                    r.control_id
                    for r in results[results.period_label == p].itertuples()
                    if r.status == "fail" and r.control_id in report_level
                }
            ),
        }
        for p in shown
    ]

    worst = max((1 - c["share"]) for c in chart if c["share"] is not None)
    axis_top, ticks = nice_axis(worst)

    by_dimension = []
    for dim in ["completeness", "validity", "accuracy", "consistency", "uniqueness", "timeliness"]:
        ids = [c.id for c in controls if c.dimension == dim]
        rows = latest_rows[latest_rows.control_id.isin(ids)]
        applicable = rows[rows.status != "not_applicable"]
        by_dimension.append(
            {
                "dimension": dim,
                "controls": len(ids),
                "passing": int(
                    (
                        applicable.groupby("control_id").status.apply(
                            lambda s: all(x == "pass" for x in s)
                        )
                    ).sum()
                ),
                "applicable": applicable.control_id.nunique(),
            }
        )

    return {
        "run": run,
        "generated": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "controls": controls,
        "grid": grid,
        "periods": shown,
        "latest": latest,
        "latest_filing": base_latest.to_dict(),
        "kpi": {
            "lines": int(k.loc[latest, "lines"]),
            "value": money(k.loc[latest, "value_usd"]),
            "clear_share": float(k.loc[latest, "clear_share"]),
            "flagged_value": money(k.loc[latest, "flagged_value_usd"]),
            "failing_now": failing_now,
            "open_issues": len(open_issues),
            "breached": sum(1 for i in open_issues if i.get("sla_state") == "breached"),
            "issues_total": len(issue_rows),
        },
        "by_dimension": by_dimension,
        "chart": chart,
        "axis_top": axis_top,
        "ticks": ticks,
        "issues": issue_rows,
        "per_control": per_control,
        "filings": filings.sort_values(["period_of_report", "filed_date"], ascending=False).to_dict(
            "records"
        ),
        "money": money,
    }


def build(settings: Settings) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = money
    html = env.get_template("index.html.j2").render(**context(settings))
    out = settings.site_dir / "index.html"
    out.write_text(html)
    return str(out)
