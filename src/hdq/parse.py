"""Parse 13F XML into flat records.

Filers and filing agents write the same schema with different namespace
prefixes (a default namespace, `ns1:`, `n1:` and so on), so elements are matched
by local name only. Values are kept exactly as filed; unit conversion and
version selection happen in SQL, where they can be tested and reviewed.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element | None, *path: str) -> ET.Element | None:
    for name in path:
        if elem is None:
            return None
        elem = next((c for c in elem if _local(c.tag) == name), None)
    return elem


def _text(elem: ET.Element | None, *path: str) -> str | None:
    node = _child(elem, *path)
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value or None


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    return float(value.replace(",", ""))


def _date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def _find_any(root: ET.Element, name: str) -> ET.Element | None:
    return next((e for e in root.iter() if _local(e.tag) == name), None)


def parse_primary(path: Path, meta: dict) -> tuple[dict, list[dict]]:
    root = ET.parse(path).getroot()
    cover = _find_any(root, "coverPage")
    summary = _find_any(root, "summaryPage")
    amendment = _text(cover, "isAmendment")
    period = _date(_text(cover, "reportCalendarOrQuarter")) or _date(meta.get("period"))
    filing = {
        "accession": meta["accession"],
        "form": meta["form"],
        "filed_date": date.fromisoformat(meta["filed"]),
        "period_of_report": period,
        "is_amendment": (amendment or "").lower() in ("true", "y", "yes", "1"),
        "amendment_no": _number(_text(cover, "amendmentNo")),
        "amendment_type": _text(cover, "amendmentInfo", "amendmentType"),
        "report_type": _text(cover, "reportType"),
        "manager_name": _text(cover, "filingManager", "name"),
        "other_managers_count": _number(_text(summary, "otherIncludedManagersCount")),
        "table_entry_total": _number(_text(summary, "tableEntryTotal")),
        "table_value_total": _number(_text(summary, "tableValueTotal")),
        "confidential_omitted": (_text(summary, "isConfidentialOmitted") or "").lower() == "true",
        "source_url": meta.get("sources", {}).get("infotable.xml"),
        "infotable_sha256": meta.get("sha256", {}).get("infotable.xml"),
    }
    managers = []
    info = _child(summary, "otherManagers2Info")
    for m in info if info is not None else []:
        seq = _number(_text(m, "sequenceNumber"))
        managers.append(
            {
                "accession": meta["accession"],
                "sequence_number": int(seq) if seq is not None else None,
                "name": _text(m, "otherManager", "name"),
                "file_number": _text(m, "otherManager", "form13FFileNumber"),
            }
        )
    return filing, managers


def iter_holdings(path: Path, accession: str) -> Iterator[dict]:
    line = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        if _local(elem.tag) != "infoTable":
            continue
        line += 1
        yield {
            "accession": accession,
            "line_no": line,
            "issuer_name": _text(elem, "nameOfIssuer"),
            "title_of_class": _text(elem, "titleOfClass"),
            "cusip": (_text(elem, "cusip") or "").upper() or None,
            "figi": _text(elem, "figi"),
            "value": _number(_text(elem, "value")),
            "amount": _number(_text(elem, "shrsOrPrnAmt", "sshPrnamt")),
            "amount_type": _text(elem, "shrsOrPrnAmt", "sshPrnamtType"),
            "put_call": _text(elem, "putCall"),
            "investment_discretion": _text(elem, "investmentDiscretion"),
            "other_manager": _text(elem, "otherManager"),
            "voting_sole": _number(_text(elem, "votingAuthority", "Sole")),
            "voting_shared": _number(_text(elem, "votingAuthority", "Shared")),
            "voting_none": _number(_text(elem, "votingAuthority", "None")),
        }
        elem.clear()


def read_filing(folder: Path) -> tuple[dict, list[dict], list[dict]]:
    meta = json.loads((folder / "meta.json").read_text())
    filing, managers = parse_primary(folder / "primary_doc.xml", meta)
    holdings = list(iter_holdings(folder / "infotable.xml", meta["accession"]))
    return filing, managers, holdings
