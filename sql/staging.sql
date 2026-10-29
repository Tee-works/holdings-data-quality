-- Staging views over the raw tables loaded from the SEC documents.
-- Written in SQL that both DuckDB and Snowflake accept (see src/hdq/dialect.py).
-- Raw tables hold values exactly as filed; every interpretation lives here.

-- 1. Units. From 3 January 2023 the SEC requires 13F values in whole dollars;
--    before that they were reported in thousands of dollars. The rule follows
--    the filing date, so an amendment filed in 2023 for a 2022 quarter is in dollars.
create or replace view filing as
select
    f.*,
    case when f.filed_date < date '2023-01-03' then 1000 else 1 end as value_multiplier,
    f.table_value_total
    * case when f.filed_date < date '2023-01-03' then 1000 else 1 end as table_value_total_usd,
    cast(year(f.period_of_report) as varchar) || 'Q' || cast(quarter(f.period_of_report) as varchar)
        as period_label
from raw_filing as f;

-- 2. Versions. For each reporting period, the latest of the original report and any
--    RESTATEMENT amendments is the base; NEW HOLDINGS amendments filed after the base
--    add lines to it; everything else has been superseded. Order is EDGAR's acceptance
--    time where known (two filings can share a date, and accession prefixes differ
--    between filing agents), then filing date.
create or replace view filing_version as
with candidates as (
    select
        accession,
        period_of_report,
        filed_date,
        accepted_at,
        row_number() over (
            partition by period_of_report
            order by filed_date desc, accepted_at desc nulls last, accession desc
        ) as rn
    from filing
    where not is_amendment or upper(coalesce(amendment_type, '')) = 'RESTATEMENT'
),

base as (
    select * from candidates
    where rn = 1
)

select
    f.accession,
    f.period_of_report,
    b.accession as base_accession,
    case
        when f.accession = b.accession then 'base'
        when
            f.is_amendment
            and upper(coalesce(f.amendment_type, '')) = 'NEW HOLDINGS'
            and (
                f.filed_date > b.filed_date
                or (f.filed_date = b.filed_date and f.accepted_at > b.accepted_at)
                or (
                    f.filed_date = b.filed_date
                    and (f.accepted_at is null or b.accepted_at is null)
                    and f.accession > b.accession
                )
            )
            then 'added'
        else 'superseded'
    end as version_role
from filing as f
inner join base as b on f.period_of_report = b.period_of_report;

create or replace view report_period as
select
    period_of_report,
    min(period_label) as period_label,
    -- Quarter number, not a rank: a quarter missing from the data leaves a gap, so
    -- period-over-period controls never compare non-adjacent quarters.
    min(year(period_of_report) * 4 + quarter(period_of_report)) as period_seq
from filing
group by period_of_report;

-- 3. Holdings with values in US dollars and the version each line belongs to.
create or replace view holding as
select
    h.*,
    f.period_of_report,
    f.period_label,
    f.filed_date,
    f.value_multiplier,
    v.version_role,
    v.base_accession,
    h.value * f.value_multiplier as value_usd,
    coalesce(upper(h.amount_type) = 'SH' and h.put_call is null, false) as is_plain_equity
from raw_holding as h
inner join filing as f on h.accession = f.accession
inner join filing_version as v on h.accession = v.accession;

-- What the filer currently reports for each period.
create or replace view current_holding as
select * from holding
where version_role in ('base', 'added');

-- 4. One row per security per period (plain shares only, no options), for
--    period-over-period checks.
create or replace view security_position as
select
    h.period_of_report,
    p.period_seq,
    h.cusip,
    min(h.issuer_name) as issuer_name,
    min(h.base_accession) as accession,
    sum(h.amount) as shares,
    sum(h.value_usd) as value_usd,
    sum(h.value_usd) / nullif(sum(h.amount), 0) as implied_price
from current_holding as h
inner join report_period as p on h.period_of_report = p.period_of_report
where h.is_plain_equity and h.amount > 0 and h.cusip is not null
group by h.period_of_report, p.period_seq, h.cusip;
