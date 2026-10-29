/*---
id: C15
name: Implied share prices are plausible
dimension: accuracy
severity: medium
scope: holding
owner: Pricing
description: >
  Value divided by shares lies between 1 cent and 2 million dollars. Catches a value or
  quantity off by orders of magnitude on a single line, which line-level and total
  checks can miss. Securities written down to near zero (for example, suspended
  listings) also appear here, and are expected to be closed as explained.
impact: >
  An implausible price on one line misstates that position by orders of magnitude.
  For a large position, that alone can move headline exposure figures.
runbook:
  - Compare the implied price with the quarter-end market or evaluated price.
  - If the security is suspended or written down, confirm the valuation policy applied and mark explained.
  - Otherwise identify whether shares or value is wrong and raise with the owning team.
---*/
select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    value_usd / amount not between 0.01 and 2000000 as is_exception,
    value_usd,
    'implied price ' || cast(cast(round(value_usd / amount, 6) as decimal(24, 6)) as varchar)
    || ' USD (' || cast(cast(amount as bigint) as varchar) || ' shares, value '
    || cast(cast(value_usd as bigint) as varchar) || ' USD) (' || coalesce(issuer_name, '') || ')' as detail
from current_holding
where is_plain_equity and amount > 0 and value_usd is not null
