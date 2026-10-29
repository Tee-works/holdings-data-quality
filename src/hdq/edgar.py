"""Download 13F filings from SEC EDGAR.

For each 13F-HR or 13F-HR/A filing in the window, two documents are saved:

    raw/<accession>/primary_doc.xml   cover page and summary page
    raw/<accession>/infotable.xml     the holdings ("information table")
    raw/<accession>/meta.json         form type, dates, source URLs, SHA-256 of each file

A filing already on disk is not downloaded again, so the job is cheap to re-run
and the cache can be restored between CI runs. Requests are spaced to stay well
inside SEC's fair access limit of 10 per second.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from hdq.config import Settings, user_agent

FORMS = {"13F-HR", "13F-HR/A"}
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"

Getter = Callable[[str], bytes]


@dataclass(frozen=True)
class FilingRef:
    accession: str
    form: str
    filed: date
    period: date | None
    accepted: str | None = None


def http_getter(pause: float = 0.15) -> Getter:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"})
    last = [0.0]

    def get(url: str) -> bytes:
        wait = pause - (time.monotonic() - last[0])
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            resp = session.get(url, timeout=60)
            last[0] = time.monotonic()
            # SEC signals throttling with 403 (sometimes 429/503): back off and retry.
            if resp.status_code in (403, 429, 503) and attempt < 3:
                time.sleep(2**attempt * 10)
                continue
            resp.raise_for_status()
            return resp.content
        raise RuntimeError(f"gave up on {url}")

    return get


def _rows(block: dict) -> list[dict]:
    keys = list(block)
    return [dict(zip(keys, values, strict=True)) for values in zip(*block.values(), strict=True)]


def list_filings(cik: str, get: Getter, since: date) -> list[FilingRef]:
    """All 13F holdings reports filed on or after `since`, oldest first."""
    padded = f"CIK{int(cik):010d}"
    doc = json.loads(get(SUBMISSIONS.format(name=f"{padded}.json")))
    rows = _rows(doc["filings"]["recent"])
    # Busy filers spill older history into extra pages; read them only if needed.
    for page in doc["filings"].get("files", []):
        if date.fromisoformat(page["filingTo"]) < since:
            continue
        rows += _rows(json.loads(get(SUBMISSIONS.format(name=page["name"]))))

    refs = {}
    for r in rows:
        if r["form"] not in FORMS:
            continue
        filed = date.fromisoformat(r["filingDate"])
        if filed < since:
            continue
        period = date.fromisoformat(r["reportDate"]) if r.get("reportDate") else None
        refs[r["accessionNumber"]] = FilingRef(
            r["accessionNumber"], r["form"], filed, period, r.get("acceptanceDateTime") or None
        )
    return sorted(refs.values(), key=lambda f: (f.filed, f.accession))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(ref: FilingRef, cik: str, get: Getter, raw_dir: Path) -> bool:
    """Save one filing. Returns False if it was already on disk."""
    folder = raw_dir / ref.accession
    if (folder / "meta.json").exists():
        return False
    base = ARCHIVE.format(cik=int(cik), acc=ref.accession.replace("-", ""))
    listing = json.loads(get(f"{base}/index.json"))["directory"]["item"]
    xml = [i for i in listing if i["name"].lower().endswith(".xml")]
    primary = next((i for i in xml if i["name"].lower() == "primary_doc.xml"), None)
    tables = [i for i in xml if i is not primary]
    if primary is None or not tables:
        raise RuntimeError(f"{ref.accession}: expected primary_doc.xml and an information table")
    # The information table is the remaining XML document; if a filer adds others, take the largest.
    table = max(tables, key=lambda i: int(i.get("size") or 0))

    files = {
        "primary_doc.xml": f"{base}/{primary['name']}",
        "infotable.xml": f"{base}/{table['name']}",
    }
    folder.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, url in files.items():
        data = get(url)
        (folder / name).write_bytes(data)
        hashes[name] = _sha256(data)
    meta = {
        "accession": ref.accession,
        "form": ref.form,
        "filed": ref.filed.isoformat(),
        "period": ref.period.isoformat() if ref.period else None,
        "accepted": ref.accepted,
        "sources": files,
        "sha256": hashes,
    }
    # meta.json is written last: its presence means the filing is complete.
    (folder / "meta.json").write_text(json.dumps(meta, indent=1))
    return True


def window_start(today: date, quarters: int) -> date:
    """First filing date in scope: the first of the month, `quarters` x 3 months ago.

    A report is filed up to 45 days after its quarter ends, so this window holds the
    last `quarters` reports that have been filed (16 by default: four years, which
    reaches back past the January 2023 change from thousands to dollars).
    """
    y, m = divmod(today.year * 12 + today.month - 1 - 3 * quarters, 12)
    return date(y, m + 1, 1)


def fetch(settings: Settings, get: Getter | None = None, today: date | None = None) -> dict:
    """Download every filing in the window. One filing that cannot be fetched is reported
    and skipped, so the rest of the run still publishes."""
    get = get or http_getter()
    since = settings.since or window_start(today or date.today(), settings.quarters)
    refs = list_filings(settings.cik, get, since)
    new, failed = 0, {}
    for r in refs:
        try:
            new += download(r, settings.cik, get, settings.raw_dir)
        except (RuntimeError, requests.RequestException, KeyError, ValueError) as exc:
            failed[r.accession] = str(exc)
    return {"filings": len(refs), "downloaded": new, "failed": failed, "since": since.isoformat()}
