/*---
id: C06
name: Other manager numbers refer to managers on the summary page
dimension: validity
severity: medium
scope: holding
owner: Regulatory Reporting
description: >
  Every number in a line's "other manager" column is a sequence number in the same
  filing's list of other included managers, which sits on the summary page. A blank
  column, or N/A, NONE or 0, means no other manager and is not checked (SEC Form 13F
  FAQ 49 allows a blank or N/A).
impact: >
  The other manager column attributes a holding to a group entity. A number that is
  not in the list means the holding cannot be attributed, so entity-level views of the
  book are incomplete.
runbook:
  - Note the unlisted number(s) from the detail column.
  - Compare with the list of other included managers on the filing's summary page for that quarter.
  - If an entity is missing from the list, the summary page and the table disagree; if the line carries a stale entity number, the mapping that fills the column is out of date.
  - Record which it is and close.
---*/
with lists as (
    select
        accession,
        line_no,
        {{ replace_all("trim(other_manager)", "[;[:space:]]+", ",") }} as list
    from current_holding
    where other_manager is not null
),

refs as (
    select
        l.accession,
        l.line_no,
        trim(split_part(l.list, ',', n.i)) as ref
    from lists as l
    cross join (values (1), (2), (3), (4), (5), (6), (7), (8), (9), (10)) as n (i)
),

unlisted as (
    select
        r.accession,
        r.line_no,
        listagg(distinct r.ref, ', ') as refs
    from refs as r
    left join raw_other_manager as m
        on r.accession = m.accession and try_cast(r.ref as integer) = m.sequence_number
    where
        r.ref <> ''
        and upper(r.ref) not in ('N/A', 'NA', 'NONE', '0', '-')
        and m.sequence_number is null
    group by r.accession, r.line_no
)

select
    h.accession,
    h.period_of_report,
    h.cusip as entity,
    h.line_no,
    u.line_no is not null as is_exception,
    h.value_usd,
    'other manager ' || coalesce(u.refs, '') || ' is not in the summary page list ('
    || coalesce(h.issuer_name, '') || ')' as detail
from current_holding as h
left join unlisted as u on h.accession = u.accession and h.line_no = u.line_no
