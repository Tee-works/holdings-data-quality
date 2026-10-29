/*---
id: C08
name: No line is repeated exactly
dimension: uniqueness
severity: high
scope: holding
owner: Regulatory Reporting
description: >
  No two lines in a filing agree on every field (security, class, amounts, value,
  discretion, other manager, put/call and voting authority). The first copy passes;
  each further copy is an exception and its value is the amount double counted.
impact: >
  An exact repeat is either two genuine holdings that happen to match on every field,
  or a line produced twice. Until that is established, totals that include it may
  count the position twice.
runbook:
  - Confirm both lines are identical in the source extract (not just in the filing).
  - Find the join or union in the extract that produced the second copy.
  - Decide with Regulatory Reporting whether the overstatement needs an amendment.
  - Close when the extract is fixed and the next run passes.
---*/
with numbered as (
    select
        *,
        row_number() over (
            partition by
                accession, cusip, issuer_name, title_of_class, figi, value, amount, amount_type,
                put_call, investment_discretion, other_manager, voting_sole, voting_shared, voting_none
            order by line_no
        ) as copy_no,
        min(line_no) over (
            partition by
                accession, cusip, issuer_name, title_of_class, figi, value, amount, amount_type,
                put_call, investment_discretion, other_manager, voting_sole, voting_shared, voting_none
        ) as first_line
    from current_holding
)

select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    copy_no > 1 as is_exception,
    value_usd,
    'line ' || cast(line_no as varchar) || ' repeats line ' || cast(first_line as varchar)
    || ' (' || coalesce(issuer_name, '') || ')' as detail
from numbered
