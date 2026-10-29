/*---
id: C01
name: Line count matches the summary page
dimension: completeness
severity: critical
scope: filing
owner: Regulatory Reporting
description: >
  The number of lines in the information table equals the "table entry total"
  declared on the summary page of the same filing.
impact: >
  The summary page is a control total for the table. If the two disagree, a reader
  cannot tell which is right without going back to the source, so totals built
  from the filing need checking first.
runbook:
  - Re-run the control for the filing and note both counts from the detail column.
  - Count the lines in the extract that fed the submission; compare with both numbers.
  - If the extract matches the summary page, the information table lost lines in generation; raise with the reporting platform team.
  - If the extract matches the table, the summary page was keyed or calculated wrongly; raise with Regulatory Reporting.
  - Close when an amendment is filed or the difference is documented as explained.
---*/
select
    f.accession,
    f.period_of_report,
    f.accession as entity,
    cast(null as integer) as line_no,
    coalesce(h.n, 0) <> f.table_entry_total as is_exception,
    cast(null as double) as value_usd,
    cast(coalesce(h.n, 0) as varchar) || ' lines in the information table; summary page declares '
    || cast(cast(f.table_entry_total as bigint) as varchar) as detail
from filing as f
left join (
    select
        accession,
        count(*) as n
    from raw_holding
    group by accession
) as h on f.accession = h.accession
