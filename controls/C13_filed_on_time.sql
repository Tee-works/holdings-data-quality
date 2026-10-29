/*---
id: C13
name: Report filed by the 45-day date
dimension: timeliness
severity: medium
scope: filing
owner: Regulatory Reporting
description: >
  Original reports (not amendments) carry an EDGAR filing date no later than 45 days
  after the end of the quarter, moved to the next business day when day 45 is a weekend
  or a US federal holiday (SEC Form 13F FAQ 25). The filing date is the one EDGAR
  records; this control does not know about any arrangement with the SEC that changes it.
impact: >
  Filing dates are part of a reporting timetable that data quality depends on: when a
  report lands later than planned, it is worth knowing which step moved.
runbook:
  - Confirm the filing date and acceptance time on EDGAR.
  - Check the computed date against the SEC calendar for that quarter.
  - Record what is known about the timing and close.
---*/
with candidates as (
    select
        f.accession,
        f.period_of_report,
        f.filed_date,
        f.period_of_report + (45 + d.n) as candidate_day
    from filing as f
    cross join (values (0), (1), (2), (3), (4), (5), (6), (7)) as d (n)
    where not f.is_amendment
),

deadlines as (
    select
        c.accession,
        c.period_of_report,
        c.filed_date,
        min(c.candidate_day) as deadline
    from candidates as c
    left join ref_us_holiday as h on c.candidate_day = h.holiday_date
    -- 2 Jan 2000 was a Sunday, so 0 is Sunday and 6 is Saturday on every engine.
    where mod(c.candidate_day - date '2000-01-02', 7) not in (0, 6) and h.holiday_date is null
    group by c.accession, c.period_of_report, c.filed_date
)

select
    accession,
    period_of_report,
    accession as entity,
    cast(null as integer) as line_no,
    filed_date > deadline as is_exception,
    cast(null as double) as value_usd,
    case
        when filed_date > deadline
            then
                'EDGAR filing date ' || cast(filed_date as varchar) || ' is '
                || cast(filed_date - deadline as varchar) || ' day(s) after the computed 45-day date '
                || cast(deadline as varchar)
        else 'filed ' || cast(filed_date as varchar) || ', computed 45-day date ' || cast(deadline as varchar)
    end as detail
from deadlines
