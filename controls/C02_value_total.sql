/*---
id: C02
name: Line values add up to the summary page total
dimension: accuracy
severity: critical
scope: filing
owner: Regulatory Reporting
description: >
  The sum of line values equals the "table value total" on the summary page, within
  the rounding that whole-unit line values can explain (half a unit per line).
impact: >
  The value total is the headline figure readers take from a 13F. A difference larger
  than rounding means the lines and the total were not produced from the same data,
  and one of them needs explaining.
runbook:
  - Note the difference and its sign from the detail column.
  - Look for a single line whose value equals the difference (a dropped or duplicated line).
  - Check whether the total was taken from a different extract time than the lines.
  - Agree the corrected figure with Regulatory Reporting and decide whether an amendment is needed.
  - Close when amended or explained in the issue log.
---*/
with line_total as (
    select
        accession,
        sum(value) as total,
        count(*) as n
    from raw_holding
    group by accession
)

select
    f.accession,
    f.period_of_report,
    f.accession as entity,
    cast(null as integer) as line_no,
    abs(coalesce(t.total, 0) - f.table_value_total) > greatest(0.5 * coalesce(t.n, 0), 1)
        as is_exception,
    abs(coalesce(t.total, 0) - f.table_value_total) * f.value_multiplier as value_usd,
    'lines add up to ' || cast(cast(coalesce(t.total, 0) as bigint) as varchar)
    || case when f.value_multiplier = 1000 then ' thousand USD' else ' USD' end
    || '; summary page says ' || cast(cast(f.table_value_total as bigint) as varchar)
    || ' (difference ' || cast(cast(coalesce(t.total, 0) - f.table_value_total as bigint) as varchar)
    || ')' as detail
from filing as f
left join line_total as t on f.accession = t.accession
