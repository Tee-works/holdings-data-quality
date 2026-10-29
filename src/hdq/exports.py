"""Reporting outputs: a star schema of CSV files that Power BI (or any BI tool) loads directly.

    site/data/dim_control.csv          one row per control, with owner, severity and SLA
    site/data/dim_filing.csv           one row per filing, with version role and source link
    site/data/fact_control_result.csv  every control result from every run
    site/data/fact_finding.csv         exceptions (and auto-explained cases) from the latest run
    site/data/fact_issue.csv           the issue log
    site/data/fact_period_kpi.csv      share of reported value clear of exceptions, per quarter

Relationships and suggested measures are in docs/powerbi.md.
"""

from __future__ import annotations

import json

import pandas as pd

from hdq.config import Settings
from hdq.controls import Control
from hdq.issues import SLA_DAYS


def control_table(controls: list[Control]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "control_id": c.id,
                "name": c.name,
                "dimension": c.dimension,
                "severity": c.severity,
                "scope": c.scope,
                "owner": c.owner,
                "sla_business_days": SLA_DAYS[c.severity],
                "description": c.description,
                "impact": c.impact,
            }
            for c in controls
        ]
    )


def issue_table(issues: dict) -> pd.DataFrame:
    rows = []
    for i in issues.values():
        t = i.get("triage", {})
        rows.append(
            {k: v for k, v in i.items() if k != "triage"}
            | {
                "triage_decision": t.get("decision"),
                "triage_note": t.get("note"),
                "triage_by": t.get("by"),
                "triage_on": t.get("on"),
            }
        )
    return pd.DataFrame(rows)


def write(
    settings: Settings,
    controls: list[Control],
    filings: pd.DataFrame,
    history: pd.DataFrame,
    findings: pd.DataFrame,
    kpis: pd.DataFrame,
    issues: dict,
    run_id: str,
) -> None:
    out = settings.site_dir / "data"
    out.mkdir(parents=True, exist_ok=True)
    control_table(controls).to_csv(out / "dim_control.csv", index=False)
    cols = [
        "accession", "form", "filed_date", "period_of_report", "period_label", "version_role",
        "is_amendment", "amendment_type", "table_entry_total", "table_value_total_usd",
        "value_multiplier", "source_url",
    ]  # fmt: skip
    filings[cols].to_csv(out / "dim_filing.csv", index=False)
    history.to_csv(out / "fact_control_result.csv", index=False)
    findings.assign(run_id=run_id).to_csv(out / "fact_finding.csv", index=False)
    issue_table(issues).to_csv(out / "fact_issue.csv", index=False)
    kpis.to_csv(out / "fact_period_kpi.csv", index=False)
    (out / "run.json").write_text(
        json.dumps({"run_id": run_id, "sample": settings.sample, "filer": settings.filer_name,
                    "cik": settings.cik}, indent=1)
    )  # fmt: skip
