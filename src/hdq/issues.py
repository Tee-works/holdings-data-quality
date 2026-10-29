"""Issue log: turns control results into tracked issues with owners and SLAs.

One issue per control per filing with exceptions. Detection opens it; a triage
decision recorded in state/triage.yaml (reviewed like code, through a pull request)
stops the SLA clock; a later run with no exceptions resolves it; if the filing leaves
the window or the control stops applying, it is withdrawn.

SLA, in business days from first detection to a triage decision:
    critical 1, high 3, medium 10, low 20
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from hdq.controls import Control

SLA_DAYS = {"critical": 1, "high": 3, "medium": 10, "low": 20}
DECISIONS = {"explained", "accepted", "raised_with_source", "fixed_upstream"}


def issue_id(row) -> str:
    base = f"{row['period_label']}-{row['control_id']}"
    # Amendments and superseded reports get the filing's own sequence (e.g. 26-000011).
    return base if row["version_role"] == "base" else f"{base}-{row['accession'].split('-', 1)[1]}"


def _due(first_seen: date, severity: str) -> date:
    return np.busday_offset(first_seen, SLA_DAYS[severity], roll="forward").astype(object)


def load_triage(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    for key, entry in data.items():
        if entry.get("decision") not in DECISIONS:
            raise ValueError(f"triage {key}: decision must be one of {sorted(DECISIONS)}")
        for field in ("note", "by", "on"):
            if not entry.get(field):
                raise ValueError(f"triage {key}: '{field}' is required")
    return data


def update(
    issues: dict,
    results: pd.DataFrame,
    findings: pd.DataFrame,
    controls: list[Control],
    triage: dict,
    today: date,
) -> dict:
    by_id = {c.id: c for c in controls}
    issues = {k: dict(v) for k, v in issues.items()}
    first_detail = (
        findings[findings.kind == "exception"].groupby(["control_id", "accession"]).detail.first()
    )

    for row in results.to_dict("records"):
        key = issue_id(row)
        c = by_id[row["control_id"]]
        if row["exceptions"] > 0:
            issue = issues.setdefault(
                key,
                {
                    "issue_id": key,
                    "control_id": c.id,
                    "accession": row["accession"],
                    "period_label": row["period_label"],
                    "severity": c.severity,
                    "owner": c.owner,
                    "first_seen": today.isoformat(),
                    "status": "open",
                },
            )
            if issue["status"] == "resolved":  # it came back
                issue.update(status="open", reopened_on=today.isoformat())
                issue.pop("resolved_on", None)
            issue.update(
                last_seen=today.isoformat(),
                exceptions=int(row["exceptions"]),
                exception_value=float(row["exception_value"]),
                example=first_detail.get((c.id, row["accession"]), ""),
            )
        elif key in issues and issues[key]["status"] != "resolved" and row["status"] == "pass":
            issues[key].update(status="resolved", resolved_on=today.isoformat())

    # A filing that left the window, or a control that no longer applies to it, can no
    # longer confirm or clear the issue: withdraw it rather than leave it open forever.
    evaluated = {issue_id(r) for r in results.to_dict("records") if r["status"] != "not_applicable"}
    for key, issue in issues.items():
        if key not in evaluated and issue["status"] in ("open", "triaged"):
            issue.update(status="withdrawn", withdrawn_on=today.isoformat())

    for key, issue in issues.items():
        t = triage.get(key)
        if t and issue["status"] == "open":
            issue["status"] = "triaged"
        if t:
            issue["triage"] = {k: str(v) for k, v in t.items()}
        _apply_sla(issue, today)
    return dict(sorted(issues.items()))


def _apply_sla(issue: dict, today: date) -> None:
    first = date.fromisoformat(issue["first_seen"])
    due = _due(first, issue["severity"])
    issue["sla_due"] = due.isoformat()
    if issue["status"] == "open":
        issue["age_business_days"] = int(np.busday_count(first, today))
        issue["sla_state"] = "breached" if today > due else "within"
        return
    closed_on = (
        issue.get("triage", {}).get("on") or issue.get("resolved_on") or issue.get("withdrawn_on")
    )
    closed = date.fromisoformat(str(closed_on))
    issue["age_business_days"] = int(np.busday_count(first, closed))
    issue["sla_state"] = "met" if closed <= due else "missed"


def load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save(path: Path, issues: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(issues, indent=1, sort_keys=True) + "\n")
