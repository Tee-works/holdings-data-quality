/*---
id: C18
name: A new-holdings amendment adds lines rather than repeating the report
dimension: uniqueness
severity: high
scope: filing
owner: Regulatory Reporting
description: >
  A 13F-HR/A of type NEW HOLDINGS adds lines to the quarter's report; a full
  replacement should be a RESTATEMENT. If more than half of an amendment's lines
  match a line in the base report on CUSIP, shares and value, the amendment is probably
  a full report filed under the wrong type, and adding it would count those holdings
  twice. Only NEW HOLDINGS amendments are in scope.
impact: >
  The staging layer adds NEW HOLDINGS amendments to the base report. If an amendment is
  really a restatement, every total for the quarter is inflated by the repeated lines.
runbook:
  - Open the amendment and the base report on EDGAR and compare line counts.
  - If the amendment is a full report, treat it as a restatement for this quarter (record the decision) so staging stops adding it.
  - If the matching lines are genuinely new positions that happen to match, record that and close.
---*/
with amendments as (
    select
        f.accession,
        f.period_of_report,
        v.base_accession
    from filing as f
    inner join filing_version as v on f.accession = v.accession
    where f.is_amendment and upper(coalesce(f.amendment_type, '')) = 'NEW HOLDINGS'
),

matched as (
    select
        a.accession,
        a.period_of_report,
        count(*) as lines,
        count(b.line_no) as matching,
        sum(h.value * f.value_multiplier) as value_usd
    from amendments as a
    inner join raw_holding as h on a.accession = h.accession
    inner join filing as f on h.accession = f.accession
    left join raw_holding as b
        on
            a.base_accession = b.accession
            and h.cusip = b.cusip
            and h.amount = b.amount
            and h.value = b.value
    group by a.accession, a.period_of_report
)

select
    accession,
    period_of_report,
    accession as entity,
    cast(null as integer) as line_no,
    matching > 0.5 * lines as is_exception,
    value_usd,
    cast(matching as varchar) || ' of ' || cast(lines as varchar)
    || ' amendment lines repeat a line in the base report' as detail
from matched
