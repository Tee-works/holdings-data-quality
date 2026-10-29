"""An independent reading of an information table, used as the reference side of the
load reconciliation (C16).

Deliberately shares no code with hdq.parse: a different XML library (lxml) and XPath
on local names instead of ElementTree iteration. If the main parser skips, misreads or
duplicates a line, the two readings disagree and the reconciliation reports it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from lxml import etree

FIELDS = {
    "cusip": ("cusip",),
    "issuer_name": ("nameOfIssuer",),
    "value": ("value",),
    "amount": ("shrsOrPrnAmt", "sshPrnamt"),
    "amount_type": ("shrsOrPrnAmt", "sshPrnamtType"),
    "investment_discretion": ("investmentDiscretion",),
    "other_manager": ("otherManager",),
    "put_call": ("putCall",),
}
NUMERIC = {"value", "amount"}


def _xpath(path: tuple[str, ...]) -> str:
    return "./" + "/".join(f"*[local-name()='{p}']" for p in path) + "/text()"


QUERIES = {k: etree.XPath(_xpath(v)) for k, v in FIELDS.items()}


def _clean(field: str, texts: list[str]):
    text = " ".join("".join(texts).split())
    if not text:
        return None
    if field in NUMERIC:
        return float(text.replace(",", ""))
    return text.upper() if field == "cusip" else text


def read_reference(path: Path, accession: str) -> pd.DataFrame:
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)
    root = etree.parse(str(path), parser).getroot()
    rows = []
    for n, el in enumerate(root.xpath("//*[local-name()='infoTable']"), start=1):
        row = {"line_key": f"{accession}#{n}"}
        row.update({f: _clean(f, q(el)) for f, q in QUERIES.items()})
        rows.append(row)
    df = pd.DataFrame(rows, columns=["line_key", *FIELDS]).astype(object)
    return df.where(df.notna(), None)
