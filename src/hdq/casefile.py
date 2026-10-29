"""Facts for the case studies at the top of the dashboard.

Everything here is computed from the warehouse at build time, so the page says
only what the filings show. A case appears only when its control fires; on a
clean history (or the sample) the section is left out.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from hdq.controls import load_controls, run_control


def _months(a: date, b: date) -> float:
    return round((pd.Timestamp(b) - pd.Timestamp(a)).days / 30.44, 1)


def _manager_names(con) -> dict[tuple[str, str], str]:
    rows = con.execute("select accession, sequence_number, name from raw_other_manager").fetchall()
    return {(acc, str(int(seq))): name for acc, seq, name in rows}


def double_count(con) -> dict | None:
    """C19: one entity's book reported again inside another entity's."""
    c19 = next(c for c in load_controls() if c.id == "C19")
    rows = run_control(con, c19)
    if rows.empty or not rows.is_exception.any():
        return None
    rows["pct"] = rows.detail.str.extract(r"\(([\d.]+)%\)")[0].astype(float)
    rows["inner"] = rows.detail.str.extract(r'other manager "([^"]+)" \(')[0]
    rows["outer"] = rows.detail.str.extract(r'under other manager "([^"]+)"')[0]
    names = _manager_names(con)
    versions = con.execute(
        """
        select f.accession, f.period_of_report, f.period_label, f.form, f.filed_date,
               v.version_role, f.table_value_total_usd as total_usd
        from filing_version as v inner join filing as f on v.accession = f.accession
        """
    ).df()
    versions["filed_date"] = pd.to_datetime(versions.filed_date).dt.date
    hits = rows[rows.is_exception].merge(versions, on=["accession", "period_of_report"])

    quarters = []
    for label, g in hits.groupby("period_label"):
        first = g.sort_values(["filed_date", "accession"]).iloc[0]
        base = versions[(versions.period_label == label) & (versions.version_role == "base")].iloc[
            0
        ]
        quarters.append(
            {
                "label": label,
                "filed": first.filed_date,
                "fixed": base.filed_date,
                "months": _months(first.filed_date, base.filed_date),
                "reported": float(first.total_usd),
                "restated": float(base.total_usd),
                "counted_twice": float(first.value_usd),
                "share": float(first.value_usd) / float(first.total_usd),
                "positions": int(g.detail.str.extract(r"^(\d+) of")[0].astype(int).max()),
                "documents": [
                    {"accession": r.accession, "form": r.form, "filed": r.filed_date}
                    for r in g.sort_values(["filed_date", "accession"]).itertuples()
                ],
                "inner_name": names.get(
                    (first.accession, str(int(first.inner))), f"manager {first.inner}"
                ),
                "outer_name": names.get(
                    (first.accession, str(int(first.outer))), f"manager {first.outer}"
                ),
            }
        )
    quarters.sort(key=lambda q: q["label"])

    # Context: the quarter either side, where the books were reported once.
    labels = sorted(versions.period_label.unique())
    lo = labels.index(quarters[0]["label"])
    hi = labels.index(quarters[-1]["label"])
    context = []
    for label in labels[max(lo - 1, 0) : hi + 2]:
        q = next((q for q in quarters if q["label"] == label), None)
        base = versions[(versions.period_label == label) & (versions.version_role == "base")].iloc[
            0
        ]
        context.append(
            {
                "label": label,
                "restated": float(base.total_usd),
                "counted_twice": q["counted_twice"] if q else 0.0,
            }
        )

    strip = rows.merge(versions[["accession", "period_label", "version_role"]], on="accession")
    normal = strip[~strip.is_exception]
    first_filed = quarters[0]["filed"]
    return {
        "quarters": quarters,
        "context": context,
        "strip": strip[["period_label", "pct", "is_exception", "version_role"]].to_dict("records"),
        "normal_max": float(normal.pct.max()) if not normal.empty else 0.0,
        "normal_count": len(normal),
        "flagged_count": int(strip.is_exception.sum()),
        "total_counted_twice": sum(q["counted_twice"] for q in quarters),
        "peak_share": max(q["share"] for q in quarters),
        "first_filed": first_filed,
        "inner_name": quarters[0]["inner_name"],
        "outer_name": quarters[0]["outer_name"],
        "sql": c19.render("duckdb"),
    }


def count_mismatch(con) -> dict | None:
    """C01/C02 on an original report, and the version that put it right."""
    df = con.execute(
        """
        with lines as (
            select accession, count(*) as n, sum(value_usd) as v from holding group by accession
        )
        select f.accession, f.period_label, f.filed_date, f.form,
               f.table_entry_total as declared_n, f.table_value_total_usd as declared_v,
               l.n, l.v
        from filing as f
        inner join lines as l on f.accession = l.accession
        where l.n <> f.table_entry_total
        order by f.filed_date
        """
    ).df()
    if df.empty:
        return None
    r = df.iloc[0]
    fix = con.execute(
        """
        select accession, form, filed_date, table_entry_total, table_value_total_usd
        from filing
        where period_label = ? and filed_date >= ? and accession <> ?
        order by filed_date, accepted_at nulls last, accession limit 1
        """,
        [r.period_label, r.filed_date, r.accession],
    ).fetchone()
    return {
        "label": r.period_label,
        "accession": r.accession,
        "filed": pd.Timestamp(r.filed_date).date(),
        "declared_n": int(r.declared_n),
        "lines": int(r.n),
        "declared_v": float(r.declared_v),
        "line_v": float(r.v),
        "fix": {
            "accession": fix[0],
            "form": fix[1],
            "filed": pd.Timestamp(fix[2]).date(),
            "n": int(fix[3]),
            "v": float(fix[4]),
        }
        if fix
        else None,
    }


def build(warehouse) -> dict:
    con = duckdb.connect(str(warehouse), read_only=True)
    try:
        totals = con.execute("select count(distinct accession), count(*) from holding").fetchone()
        return {
            "reports": int(totals[0]),
            "lines": int(totals[1]),
            "double_count": double_count(con),
            "count_mismatch": count_mismatch(con),
        }
    finally:
        con.close()
