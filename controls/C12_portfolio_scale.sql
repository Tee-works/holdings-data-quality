/*---
id: C12
name: Report scale is consistent with the previous quarter
dimension: consistency
severity: critical
scope: period
owner: Regulatory Reporting
description: >
  Guards the unit rule. Two tests against the previous quarter: total value must stay
  within a factor of two, and the median price move across securities held in both
  quarters must stay within a factor of two. A whole report filed in thousands when it
  should be in dollars (or the reverse) moves both by about a thousandfold. The detail
  shows the raw ratio before unit conversion, so a reviewer can see the conversion
  doing its job on the 2022 to 2023 change.
impact: >
  A unit error misstates every value in the report by a factor of a thousand, and every
  downstream consumer of the data (including commercial data vendors that redistribute
  13F data) inherits it.
runbook:
  - Compare a handful of line values with known quarter-end prices to establish the unit actually used.
  - Check the filing date against the 3 January 2023 rule (dollars from then on).
  - If the filing used the wrong unit, raise with Regulatory Reporting for an amendment.
  - If the move is real (a large transfer of assets in or out), record the business event and close as explained.
---*/
with totals as (
    select
        f.period_of_report,
        p.period_seq,
        f.accession,
        sum(h.value_usd) as total_usd,
        sum(h.value) as total_raw
    from current_holding as h
    inner join filing as f on h.base_accession = f.accession
    inner join report_period as p on f.period_of_report = p.period_of_report
    group by f.period_of_report, p.period_seq, f.accession
),

price_moves as (
    select
        cur.period_seq,
        median(cur.implied_price / prev.implied_price) as median_price_ratio,
        count(*) as n_common
    from security_position as cur
    inner join security_position as prev
        on cur.cusip = prev.cusip and cur.period_seq = prev.period_seq + 1
    where prev.implied_price > 0
    group by cur.period_seq
)

select
    cur.accession,
    cur.period_of_report,
    cur.accession as entity,
    cast(null as integer) as line_no,
    cur.total_usd / prev.total_usd not between 0.5 and 2
    or coalesce(m.median_price_ratio not between 0.5 and 2, false) as is_exception,
    cur.total_usd as value_usd,
    'total value x' || cast(cast(round(cur.total_usd / prev.total_usd, 3) as decimal(18, 3)) as varchar)
    || ' on previous quarter (raw, before unit conversion: x'
    || cast(cast(round(cur.total_raw / prev.total_raw, 3) as decimal(18, 3)) as varchar)
    || '); median price move x'
    || cast(cast(round(coalesce(m.median_price_ratio, 0), 3) as decimal(18, 3)) as varchar)
    || ' across ' || cast(coalesce(m.n_common, 0) as varchar) || ' securities' as detail
from totals as cur
inner join totals as prev on cur.period_seq = prev.period_seq + 1
left join price_moves as m on cur.period_seq = m.period_seq
