import re

import pandas as pd

from hdq import docs, site
from hdq.config import ROOT


def test_power_bi_exports_have_keys_for_the_star_schema(run, settings):
    data = settings.site_dir / "data"
    dim_control = pd.read_csv(data / "dim_control.csv")
    dim_filing = pd.read_csv(data / "dim_filing.csv")
    fact = pd.read_csv(data / "fact_control_result.csv", keep_default_na=False)
    assert dim_control.control_id.is_unique and dim_filing.accession.is_unique
    assert set(fact.control_id) <= set(dim_control.control_id)
    assert set(fact.accession) <= set(dim_filing.accession)
    assert set(fact.status) <= {"pass", "warn", "fail", "not_applicable"}
    issues = pd.read_csv(data / "fact_issue.csv")
    assert {"issue_id", "sla_due", "sla_state", "owner", "severity"} <= set(issues.columns)


def test_site_builds_and_says_what_the_data_is(run, settings):
    site.build(settings)
    html = (settings.site_dir / "index.html").read_text()
    assert "Sample data." in html
    assert not re.search(r"\bnan\b|\bNone\b", html)  # no leaked missing values
    for c in ["C01", "C08", "C12", "C15"]:
        assert f'id="{c}"' in html


def test_control_catalogue_is_current():
    assert (ROOT / "docs" / "controls.md").read_text() == docs.render(), "run `hdq docs`"
