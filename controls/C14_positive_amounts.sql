/*---
id: C14
name: Values and quantities are present and positive
dimension: validity
severity: medium
scope: holding
owner: Investment Data Operations
description: >
  Every line has a value and a share or principal amount, and both are greater than
  zero. Form 13F lists long positions, so a zero or negative amount is unusual and
  worth a look.
impact: >
  A zero or missing amount usually means a closed position leaked into the extract, or
  a quantity was lost. Either way the line distorts counts of holdings and any
  per-share calculation.
runbook:
  - Check the position record for the security and date.
  - If the position was closed before quarter end, remove it from the extract scope.
  - If the position is open, find where the quantity or value was lost.
---*/
select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    coalesce(value <= 0 or amount <= 0, true) as is_exception,
    value_usd,
    'value ' || coalesce(cast(value as varchar), 'missing') || ' and amount '
    || coalesce(cast(amount as varchar), 'missing') || ' (' || coalesce(issuer_name, '') || ')' as detail
from current_holding
