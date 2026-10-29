import json
from datetime import date

from hdq import edgar
from hdq.config import Settings


def fake_sec(calls):
    recent = {
        "accessionNumber": ["0000764068-26-000011", "0000764068-26-000009", "0000764068-25-000001"],
        "filingDate": ["2026-05-08", "2026-04-02", "2025-02-10"],
        "reportDate": ["2026-03-31", "", "2024-12-31"],
        "form": ["13F-HR", "SC 13G", "13F-HR"],
        "primaryDocument": ["primary_doc.xml", "x.htm", "primary_doc.xml"],
    }
    older = {
        "accessionNumber": ["0000764068-22-000005"],
        "filingDate": ["2022-11-10"],
        "reportDate": ["2022-09-30"],
        "form": ["13F-HR/A"],
        "primaryDocument": ["primary_doc.xml"],
    }
    pages = [
        {
            "name": "CIK0000764068-submissions-001.json",
            "filingFrom": "2021-01-01",
            "filingTo": "2022-12-31",
        },
        {
            "name": "CIK0000764068-submissions-002.json",
            "filingFrom": "2015-01-01",
            "filingTo": "2020-12-31",
        },
    ]
    index = {"directory": {"item": [
        {"name": "primary_doc.xml", "size": "3000"},
        {"name": "0000764068-26-000011.txt", "size": "9"},
        {"name": "small_table.xml", "size": "10"},
        {"name": "sec_13F-InfoTable.xml", "size": "3299422"},
    ]}}  # fmt: skip

    def get(url):
        calls.append(url)
        if url.endswith("CIK0000764068.json"):
            return json.dumps({"filings": {"recent": recent, "files": pages}}).encode()
        if url.endswith("submissions-001.json"):
            return json.dumps(older).encode()
        if url.endswith("submissions-002.json"):
            raise AssertionError("page entirely before the window should not be read")
        if url.endswith("index.json"):
            return json.dumps(index).encode()
        return b"<xml/>"

    return get


def test_lists_only_13f_holdings_reports_in_window():
    refs = edgar.list_filings("764068", fake_sec([]), since=date(2022, 1, 1))
    assert [r.accession for r in refs] == [
        "0000764068-22-000005", "0000764068-25-000001", "0000764068-26-000011",
    ]  # fmt: skip
    assert refs[0].form == "13F-HR/A"


def test_download_takes_the_information_table_and_is_idempotent(tmp_path):
    calls = []
    s = Settings.from_env(base=tmp_path)
    get = fake_sec(calls)
    out = edgar.fetch(s, get=get, today=date(2026, 10, 26))
    assert out["filings"] == 3 and out["downloaded"] == 3
    folder = s.raw_dir / "0000764068-26-000011"
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["sources"]["infotable.xml"].endswith("/000076406826000011/sec_13F-InfoTable.xml")
    assert meta["sha256"]["infotable.xml"]

    calls.clear()
    again = edgar.fetch(s, get=get, today=date(2026, 10, 26))
    assert again["downloaded"] == 0
    assert not any("Archives" in c for c in calls)


def test_window_start_covers_the_requested_quarters():
    # At 26 Oct 2026 the latest filed report is 2026Q2; 16 reports back is 2022Q3,
    # filed in November 2022 (still in thousands).
    assert edgar.window_start(date(2026, 10, 26), 16) == date(2022, 10, 1)
    assert edgar.window_start(date(2026, 2, 1), 1) == date(2025, 11, 1)
