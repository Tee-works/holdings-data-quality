/*---
id: C19
name: One entity's positions are not repeated in full under another
dimension: uniqueness
severity: critical
scope: filing
owner: Regulatory Reporting
description: >
  For each included manager in a report, the share of its positions (security and
  put/call) that another included manager in the same report also reports, with at
  least as many shares. Group entities that run index funds always overlap, often by
  half or more, so overlap alone is normal. A manager whose book sits almost entirely
  inside another's (95% or more of its positions) is the pattern left when one
  entity's holdings are reported under itself and again inside a parent or sister
  entity, instead of once as shared discretion (other manager "4,2"). Managers with
  fewer than 50 positions are left out. Every version of a report is checked, because
  the original is the document that was filed and relied on.
impact: >
  Holdings counted twice overstate the report's total value and every position
  involved, and the error survives quarter-on-quarter checks because each report is
  inflated in the same way. Anyone aggregating the filing (data vendors, regulators,
  researchers) inherits the overstatement until a restatement is filed.
runbook:
  - Read the detail to see which manager's positions sit inside which, and how many.
  - Check whether the contained manager was new to the report this quarter, or changed its mandate; the pattern usually starts there.
  - Pull a few contained positions and confirm with Investment Data Operations whether they are one holding under shared discretion or two separate holdings.
  - If they are one holding, raise with Regulatory Reporting to report them once under the combined manager code, and restate the affected quarters.
  - If they are genuinely separate (for example a sub-advised fund holding the same index), record the business reason and close as explained.
---*/
with positions as (
    select
        accession,
        period_of_report,
        other_manager as manager,
        cusip,
        coalesce(put_call, '') as put_call,
        sum(amount) as shares,
        sum(value_usd) as value_usd
    from holding
    where other_manager is not null and other_manager not like '%,%'
    group by accession, period_of_report, other_manager, cusip, coalesce(put_call, '')
),

books as (
    select
        accession,
        manager,
        count(*) as n_positions,
        sum(value_usd) as book_usd
    from positions
    group by accession, manager
),

contained as (
    select
        inner_book.accession,
        inner_book.manager,
        outer_book.manager as outer_manager,
        count(*) as n_contained,
        sum(inner_book.value_usd) as contained_usd
    from positions as inner_book
    inner join positions as outer_book
        on
            inner_book.accession = outer_book.accession
            and inner_book.cusip = outer_book.cusip
            and inner_book.put_call = outer_book.put_call
            and inner_book.manager <> outer_book.manager
            and inner_book.shares <= outer_book.shares
    group by inner_book.accession, inner_book.manager, outer_book.manager
),

worst as (
    select
        b.accession,
        b.manager,
        b.n_positions,
        b.book_usd,
        c.outer_manager,
        coalesce(c.n_contained, 0) as n_contained,
        coalesce(c.contained_usd, 0) as contained_usd,
        row_number() over (
            partition by b.accession, b.manager order by coalesce(c.n_contained, 0) desc, c.outer_manager
        ) as rank_in_book
    from books as b
    left join contained as c on b.accession = c.accession and b.manager = c.manager
    where b.n_positions >= 50
)

select
    w.accession,
    f.period_of_report,
    'other manager ' || w.manager as entity,
    cast(null as integer) as line_no,
    w.n_contained >= 0.95 * w.n_positions as is_exception,
    w.contained_usd as value_usd,
    cast(w.n_contained as varchar) || ' of ' || cast(w.n_positions as varchar)
    || ' positions for other manager "' || w.manager || '" ('
    || cast(cast(round(100.0 * w.n_contained / w.n_positions, 1) as decimal(5, 1)) as varchar)
    || '%) are also reported, with at least as many shares, under other manager "'
    || coalesce(w.outer_manager, 'none') || '"' as detail
from worst as w
inner join filing as f on w.accession = f.accession
where w.rank_in_book = 1
