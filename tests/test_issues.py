from datetime import date

import pandas as pd
import pytest

from hdq import issues
from hdq.controls import load_controls

CONTROLS = load_controls()


def result(
    control_id="C10",
    exceptions=2,
    status=None,
    period="2026Q1",
    role="base",
    acc="0000764068-26-000011",
):
    return pd.DataFrame([{
        "control_id": control_id, "accession": acc, "period_label": period, "version_role": role,
        "exceptions": exceptions, "exception_value": 1e6 * exceptions,
        "status": status or ("fail" if exceptions else "pass"),
    }])  # fmt: skip


NO_FINDINGS = pd.DataFrame(columns=["control_id", "accession", "kind", "detail"])


def step(log, res, today, triage=None):
    return issues.update(log, res, NO_FINDINGS, CONTROLS, triage or {}, today)


def test_detection_opens_an_issue_with_owner_and_sla():
    log = step({}, result(), date(2026, 10, 23))  # a Friday
    i = log["2026Q1-C10"]
    assert i["status"] == "open" and i["owner"] == "Pricing" and i["severity"] == "high"
    assert i["sla_due"] == "2026-10-28"  # 3 business days, skipping the weekend
    assert i["sla_state"] == "within"


def test_sla_breach_then_triage_late_is_missed():
    log = step({}, result(), date(2026, 10, 23))
    log = step(log, result(), date(2026, 10, 30))
    assert log["2026Q1-C10"]["sla_state"] == "breached"
    triage = {
        "2026Q1-C10": {
            "decision": "explained",
            "note": "two pricing sources",
            "by": "IA",
            "on": "2026-10-30",
        }
    }
    log = step(log, result(), date(2026, 10, 30), triage)
    assert log["2026Q1-C10"]["status"] == "triaged"
    assert log["2026Q1-C10"]["sla_state"] == "missed"


def test_triage_on_time_is_met_and_first_seen_is_kept():
    log = step({}, result(), date(2026, 10, 26))
    triage = {
        "2026Q1-C10": {
            "decision": "raised_with_source",
            "note": "ticket",
            "by": "IA",
            "on": "2026-10-27",
        }
    }
    log = step(log, result(), date(2026, 11, 20), triage)
    assert log["2026Q1-C10"]["first_seen"] == "2026-10-26"
    assert log["2026Q1-C10"]["sla_state"] == "met"


def test_clean_run_resolves_and_recurrence_reopens():
    log = step({}, result(), date(2026, 10, 26))
    log = step(log, result(exceptions=0), date(2026, 10, 27))
    assert log["2026Q1-C10"]["status"] == "resolved"
    log = step(log, result(), date(2026, 11, 2))
    assert (
        log["2026Q1-C10"]["status"] == "open" and log["2026Q1-C10"]["reopened_on"] == "2026-11-02"
    )


def test_not_applicable_withdraws_rather_than_resolves():
    log = step({}, result(), date(2026, 10, 26))
    log = step(log, result(exceptions=0, status="not_applicable"), date(2026, 10, 27))
    assert log["2026Q1-C10"]["status"] == "withdrawn"


def test_issue_for_a_filing_that_left_the_window_is_withdrawn():
    log = step({}, result(), date(2026, 10, 26))
    log = step(log, result(period="2026Q2", acc="0000764068-26-000020"), date(2026, 11, 2))
    assert log["2026Q1-C10"]["status"] == "withdrawn"
    assert log["2026Q2-C10"]["status"] == "open"


def test_amendment_issues_are_keyed_by_filing():
    log = step({}, result(role="added", acc="0000764068-26-000020"), date(2026, 10, 26))
    assert list(log) == ["2026Q1-C10-26-000020"]


def test_triage_file_is_validated(tmp_path):
    p = tmp_path / "triage.yaml"
    p.write_text("2026Q1-C10:\n  decision: ignored\n  note: x\n  by: me\n  on: 2026-10-27\n")
    with pytest.raises(ValueError, match="decision"):
        issues.load_triage(p)
    p.write_text("2026Q1-C10:\n  decision: explained\n  by: me\n  on: 2026-10-27\n")
    with pytest.raises(ValueError, match="note"):
        issues.load_triage(p)


def test_sample_run_opens_one_issue_per_failing_control_and_filing(run):
    failing = run.results[run.results.exceptions > 0]
    assert len(run.issues) == len(failing)
    assert all(i["status"] == "open" for i in run.issues.values())
