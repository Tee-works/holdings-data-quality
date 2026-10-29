"""A small synthetic filing history in the exact SEC 13F XML layout.

Used by the tests and by `hdq demo`, so the whole pipeline can run without
network access. Every issuer, CUSIP and FIGI here is invented. Known defects are
planted on purpose and listed in PLANTED, so tests can prove each control finds
its defect and nothing else.

Timeline (one filer, two other included managers):
    2022Q3  filed 2022-11-10, values in thousands (the pre-2023 rule)
    2022Q4  filed 2023-02-10, values in dollars
    2023Q1  original filed 2023-05-12 (entry count and value total wrong),
            restated 2023-06-01 (holdings defects planted here)
    2023Q2  filed 2023-08-18 (late), one 4-for-1 split, one unexplained price jump,
            plus a NEW HOLDINGS amendment on 2023-09-01
    2023Q3  filed 2023-11-13, but values mistakenly still in thousands
"""

from __future__ import annotations

import json
import random
import string
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from hdq.identifiers import _luhn_like

FILER_NS = "http://www.sec.gov/edgar/thirteenffiler"
TABLE_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"

WORDS = [
    "ALDER",
    "BRISTOW",
    "CALDER",
    "DUNMORE",
    "ELMSTEAD",
    "FARRANT",
    "GLENHOLM",
    "HARCOURT",
    "INGLEBY",
    "JARROW",
    "KESTREL",
    "LANGLEY",
    "MARLOW",
    "NORTHGATE",
    "ORWELL",
    "PENROSE",
    "QUAYSIDE",
    "REDFERN",
    "SALTASH",
    "THORNBURY",
    "UPTON",
    "VANTAGE",
    "WESTCOTT",
    "YARDLEY",
]
SUFFIXES = ["INC", "CORP", "HOLDINGS INC", "GROUP INC", "TECHNOLOGIES INC", "PLC", "CO"]
CONSONANTS = "BCDFGHJKLMNPQRSTVWXYZ"

# control id -> (period label, what was planted)
PLANTED = {
    "C01": ("2023Q1", "original report lists one line fewer than its summary page"),
    "C02": ("2023Q1", "original report's value total is 250,000 dollars too high"),
    "C03": ("2023Q1", "one CUSIP with a wrong check digit"),
    "C04": ("2023Q1", "one FIGI with a wrong check digit"),
    "C05": ("2023Q1", "one line with investment discretion 'SHR'"),
    "C06": ("2023Q1", "one line referencing other manager 3, which is not on the cover page"),
    "C07": ("2023Q1", "one line whose voting authority covers half the position"),
    "C08": ("2023Q1", "one line repeated exactly"),
    "C09": ("2023Q1", "one CUSIP reported under two issuer names"),
    "C10": ("2023Q1", "two lines for one security and entity, one valued 25% higher"),
    "C11": ("2023Q2", "one security whose price jumps 5x with no change in shares"),
    "C12": ("2023Q3", "whole report in thousands instead of dollars"),
    "C13": ("2023Q2", "report filed four days after the deadline"),
    "C14": ("2023Q1", "one line with zero shares"),
    "C15": ("2023Q1", "one security priced at a fraction of a cent"),
    "C17": ("2023Q1", "one entity valuing a security held by three entities 10% higher"),
}


@dataclass
class Security:
    cusip: str
    figi: str
    name: str
    price: float


@dataclass
class Line:
    sec: Security
    shares: float
    discretion: str = "DFND"
    manager: str | None = "1"
    put_call: str | None = None
    amount_type: str = "SH"
    value_override: float | None = None
    name_override: str | None = None
    cusip_override: str | None = None
    figi_override: str | None = None
    voting: tuple[float, float, float] | None = None


@dataclass
class Filing:
    accession: str
    form: str
    filed: date
    period: date
    lines: list[Line]
    unit: int  # 1000 = thousands, 1 = dollars
    amendment_type: str | None = None
    entry_total_delta: int = 0
    value_total_delta: float = 0.0
    prefixed: bool = False
    managers: list[tuple[int, str]] = field(
        default_factory=lambda: [(1, "Example Asset Management Ltd"), (2, "Example Pensions Ltd")]
    )


def _cusip(rng: random.Random) -> str:
    body = (
        "".join(rng.choice(string.digits) for _ in range(6))
        + rng.choice(string.ascii_uppercase + string.digits)
        + rng.choice(string.digits)
    )
    return body + str(_luhn_like(body))


def _figi(rng: random.Random) -> str:
    body = "BBG" + "".join(rng.choice(CONSONANTS + string.digits) for _ in range(8))
    return body + str(_luhn_like(body))


def _securities(rng: random.Random, n: int) -> list[Security]:
    out, names = [], set()
    while len(out) < n:
        name = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {rng.choice(SUFFIXES)}"
        if name in names:
            continue
        names.add(name)
        out.append(Security(_cusip(rng), _figi(rng), name, round(rng.uniform(8, 450), 2)))
    return out


def _book(rng: random.Random, secs: list[Security]) -> list[Line]:
    lines = []
    for s in secs:
        for manager in rng.sample(["1", "2", None], k=rng.choice([1, 1, 2, 3])):
            lines.append(
                Line(
                    s,
                    float(rng.randrange(1_000, 400_000, 100)),
                    "SOLE" if manager is None else "DFND",
                    manager,
                )
            )
    return lines


def _move_prices(rng: random.Random, secs: list[Security]) -> None:
    for s in secs:
        s.price = round(s.price * rng.uniform(0.9, 1.1), 2)


def _snapshot(lines: list[Line]) -> list[Line]:
    """Freeze prices for one period (securities are shared between periods)."""
    frozen = {}
    out = []
    for ln in lines:
        s = ln.sec
        if s.cusip not in frozen:
            frozen[s.cusip] = Security(s.cusip, s.figi, s.name, s.price)
        out.append(Line(**{**ln.__dict__, "sec": frozen[s.cusip]}))
    return out


def build_history(seed: int = 13) -> list[Filing]:
    rng = random.Random(seed)
    secs = _securities(rng, 120)
    book = _book(rng, secs)
    filings: list[Filing] = []
    acc = iter(
        f"0009999999-{y}-{n:06d}"
        for y, n in [(22, 1), (23, 1), (23, 2), (23, 3), (23, 4), (23, 5), (23, 6)]
    )

    # 2022Q3, thousands.
    filings.append(
        Filing(
            next(acc),
            "13F-HR",
            date(2022, 11, 10),
            date(2022, 9, 30),
            _snapshot(book),
            unit=1000,
            prefixed=True,
        )
    )
    _move_prices(rng, secs)

    # 2022Q4, first report in dollars.
    filings.append(
        Filing(next(acc), "13F-HR", date(2023, 2, 10), date(2022, 12, 31), _snapshot(book), unit=1)
    )
    _move_prices(rng, secs)

    # 2023Q1 original: clean holdings, wrong summary page.
    q1 = _snapshot(book)
    filings.append(
        Filing(
            next(acc),
            "13F-HR",
            date(2023, 5, 12),
            date(2023, 3, 31),
            q1,
            unit=1,
            entry_total_delta=1,
            value_total_delta=250_000,
        )
    )

    # 2023Q1 restatement: summary page right, holdings defects planted.
    r = _snapshot(book)
    by_cusip: dict[str, list[int]] = {}
    for i, ln in enumerate(r):
        by_cusip.setdefault(ln.sec.cusip, []).append(i)
    multi = [ix for ix in by_cusip.values() if len(ix) >= 2]
    single = [ix[0] for ix in by_cusip.values() if len(ix) == 1]
    c = r[single[0]].sec.cusip
    r[single[0]].cusip_override = c[:8] + str((int(c[8]) + 1) % 10)  # C03
    f = r[single[1]].sec.figi
    r[single[1]].figi_override = f[:11] + str((int(f[11]) + 3) % 10)  # C04
    r[single[2]].discretion = "SHR"  # C05
    r[single[3]].manager = "3"  # C06
    sh = r[single[4]].shares
    r[single[4]].voting = (sh / 2, 0.0, 0.0)  # C07
    r.append(Line(**r[single[5]].__dict__))  # C08 exact repeat
    r[multi[0][1]].name_override = " ".join(r[multi[0][1]].sec.name.split()[:2]) + " LTD"  # C09
    # C10: split one entity's holding over two lines (different discretion), one mispriced.
    a = r[single[7]]
    b = Line(**{**a.__dict__, "discretion": "OTR"})
    a.shares = b.shares = a.shares / 2
    b.value_override = round(b.shares * b.sec.price * 1.25)
    r.append(b)
    # C17: three entities hold one security; one of them values it 10% higher.
    three = next(ix for ix in by_cusip.values() if len(ix) == 3)
    odd = r[three[2]]
    odd.value_override = round(odd.shares * odd.sec.price * 1.10)
    r[single[6]].shares = 0.0  # C14
    penny = Security(_cusip(rng), _figi(rng), "STRANDED RESOURCES PLC", 0.000005)  # C15
    r.append(Line(penny, 1_000_000.0, "SOLE", None))
    filings.append(
        Filing(
            next(acc),
            "13F-HR/A",
            date(2023, 6, 1),
            date(2023, 3, 31),
            r,
            unit=1,
            amendment_type="RESTATEMENT",
            prefixed=True,
        )
    )
    _move_prices(rng, secs)

    # 2023Q2: a 4-for-1 split and an unexplained 5x price jump; filed late.
    split_sec, jump_sec = secs[10], secs[11]
    split_sec.price = round(split_sec.price / 4, 2)
    for ln in book:
        if ln.sec is split_sec:
            ln.shares *= 4
    jump_sec.price = round(jump_sec.price * 5, 2)
    filings.append(
        Filing(next(acc), "13F-HR", date(2023, 8, 18), date(2023, 6, 30), _snapshot(book), unit=1)
    )
    extra = _securities(rng, 2)
    filings.append(
        Filing(
            next(acc),
            "13F-HR/A",
            date(2023, 9, 1),
            date(2023, 6, 30),
            [Line(s, 50_000.0, "SOLE", None) for s in extra],
            unit=1,
            amendment_type="NEW HOLDINGS",
        )
    )
    jump_sec.price = round(jump_sec.price / 5, 2)  # back to normal next quarter
    _move_prices(rng, secs)

    # 2023Q3: reported in thousands by mistake.
    filings.append(
        Filing(
            next(acc),
            "13F-HR",
            date(2023, 11, 13),
            date(2023, 9, 30),
            _snapshot(book),
            unit=1000,
            prefixed=True,
        )
    )
    return filings


def _value(ln: Line, unit: int) -> int:
    raw = ln.value_override if ln.value_override is not None else ln.shares * ln.sec.price
    return round(raw / unit)


def _info_table_xml(f: Filing) -> str:
    p = "ns1:" if f.prefixed else ""
    decl = f'xmlns:ns1="{TABLE_NS}"' if f.prefixed else f'xmlns="{TABLE_NS}"'
    rows = []
    for ln in f.lines:
        vote = ln.voting or (ln.shares, 0.0, 0.0)
        parts = [
            f"<{p}nameOfIssuer>{escape(ln.name_override or ln.sec.name)}</{p}nameOfIssuer>",
            f"<{p}titleOfClass>COM</{p}titleOfClass>",
            f"<{p}cusip>{ln.cusip_override or ln.sec.cusip}</{p}cusip>",
            f"<{p}figi>{ln.figi_override or ln.sec.figi}</{p}figi>",
            f"<{p}value>{_value(ln, f.unit)}</{p}value>",
            f"<{p}shrsOrPrnAmt><{p}sshPrnamt>{int(ln.shares)}</{p}sshPrnamt>"
            f"<{p}sshPrnamtType>{ln.amount_type}</{p}sshPrnamtType></{p}shrsOrPrnAmt>",
        ]
        if ln.put_call:
            parts.append(f"<{p}putCall>{ln.put_call}</{p}putCall>")
        parts.append(f"<{p}investmentDiscretion>{ln.discretion}</{p}investmentDiscretion>")
        if ln.manager:
            parts.append(f"<{p}otherManager>{ln.manager}</{p}otherManager>")
        parts.append(
            f"<{p}votingAuthority><{p}Sole>{int(vote[0])}</{p}Sole>"
            f"<{p}Shared>{int(vote[1])}</{p}Shared><{p}None>{int(vote[2])}</{p}None>"
            f"</{p}votingAuthority>"
        )
        rows.append(f"<{p}infoTable>{''.join(parts)}</{p}infoTable>")
    body = "\n".join(rows)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<{p}informationTable {decl}>\n{body}\n</{p}informationTable>\n'


def _primary_xml(f: Filing) -> str:
    total = sum(_value(ln, f.unit) for ln in f.lines) + f.value_total_delta / f.unit
    managers = "".join(
        f"<otherManager2><sequenceNumber>{n}</sequenceNumber><otherManager>"
        f"<form13FFileNumber>028-{9000 + n}</form13FFileNumber><name>{escape(name)}</name>"
        f"</otherManager></otherManager2>"
        for n, name in f.managers
    )
    amendment = (
        f"<isAmendment>true</isAmendment><amendmentNo>1</amendmentNo>"
        f"<amendmentInfo><amendmentType>{f.amendment_type}</amendmentType></amendmentInfo>"
        if f.amendment_type
        else "<isAmendment>false</isAmendment>"
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<edgarSubmission xmlns="{FILER_NS}" xmlns:com="http://www.sec.gov/edgar/common">'
        f"<headerData><submissionType>{f.form}</submissionType><filerInfo>"
        f"<periodOfReport>{f.period:%m-%d-%Y}</periodOfReport></filerInfo></headerData>"
        f"<formData><coverPage><reportCalendarOrQuarter>{f.period:%m-%d-%Y}"
        f"</reportCalendarOrQuarter>{amendment}<filingManager><name>Example Group Plc</name>"
        f"</filingManager><reportType>13F COMBINATION REPORT</reportType></coverPage>"
        f"<summaryPage><otherIncludedManagersCount>{len(f.managers)}</otherIncludedManagersCount>"
        f"<tableEntryTotal>{len(f.lines) + f.entry_total_delta}</tableEntryTotal>"
        f"<tableValueTotal>{round(total)}</tableValueTotal>"
        f"<isConfidentialOmitted>false</isConfidentialOmitted>"
        f"<otherManagers2Info>{managers}</otherManagers2Info></summaryPage></formData>"
        f"</edgarSubmission>\n"
    )


def write_sample(raw_dir: Path, seed: int = 13) -> int:
    filings = build_history(seed)
    for f in filings:
        folder = raw_dir / f.accession
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "primary_doc.xml").write_text(_primary_xml(f))
        (folder / "infotable.xml").write_text(_info_table_xml(f))
        meta = {
            "accession": f.accession,
            "form": f.form,
            "filed": f.filed.isoformat(),
            "period": f.period.isoformat(),
            "sources": {"infotable.xml": "sample data, generated by hdq.sample"},
            "sha256": {},
        }
        (folder / "meta.json").write_text(json.dumps(meta, indent=1))
    return len(filings)
