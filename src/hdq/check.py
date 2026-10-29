"""Run every control, update the issue log and write the outputs.

State kept between runs (committed by the scheduled workflow, so the history is
auditable in git):
    state/results.csv   every control result from every run
    state/runs.csv      one line per run
    state/issues.json   the issue log
    state/triage.yaml   triage decisions, written by people

Outputs for reporting (rebuilt each run): see hdq.exports.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from hdq import exports, issues
from hdq.config import Settings
from hdq.controls import clear_value_share, load_controls, run_all
from hdq.load import connect


@dataclass
class RunOutput:
    run_id: str
    results: pd.DataFrame
    findings: pd.DataFrame
    kpis: pd.DataFrame
    issues: dict


def _append(path, df: pd.DataFrame) -> pd.DataFrame:
    if path.exists():
        df = pd.concat([pd.read_csv(path), df], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def run(settings: Settings, today: date | None = None, now: datetime | None = None) -> RunOutput:
    now = now or datetime.now(UTC)
    today = today or now.date()
    run_id = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    controls = load_controls()
    con = connect(settings.warehouse)
    try:
        results, findings = run_all(con, controls)
        kpis = clear_value_share(con, findings, controls)
        filings = con.execute(
            """
            select f.*, v.version_role, v.base_accession
            from filing as f join filing_version as v using (accession)
            order by f.period_of_report, f.filed_date
            """
        ).df()
        fingerprint = hashlib.sha256(
            "".join(sorted(filings.infotable_sha256.fillna(""))).encode()
        ).hexdigest()[:16]
        lines = con.execute("select count(*) from raw_holding").fetchone()[0]
    finally:
        con.close()

    state = settings.state_dir
    results = results.assign(run_id=run_id)
    history = _append(state / "results.csv", results)
    _append(
        state / "runs.csv",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "filings": len(filings),
                    "lines": int(lines),
                    "data_fingerprint": fingerprint,
                    "controls": len(controls),
                    "results_fail": int((results.status == "fail").sum()),
                    "results_warn": int((results.status == "warn").sum()),
                }
            ]
        ),
    )
    log = issues.update(
        issues.load(state / "issues.json"),
        results,
        findings,
        controls,
        issues.load_triage(state / "triage.yaml"),
        today,
    )
    issues.save(state / "issues.json", log)
    exports.write(settings, controls, filings, history, findings, kpis, log, run_id)
    return RunOutput(run_id, results, findings, kpis, log)


def summary(out: RunOutput) -> str:
    r = out.results
    lines = [f"run {out.run_id}: {len(r)} control results"]
    for status in ("fail", "warn", "pass", "not_applicable"):
        lines.append(f"  {status:<5} {int((r.status == status).sum())}")
    open_issues = [i for i in out.issues.values() if i["status"] == "open"]
    lines.append(f"open issues: {len(open_issues)}")
    return "\n".join(lines)
