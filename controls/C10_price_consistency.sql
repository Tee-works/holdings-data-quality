/*---
id: C10
name: Lines for one security and one entity imply the same price
dimension: accuracy
severity: high
scope: holding
owner: Pricing
description: >
  Within one filing, lines for the same CUSIP attributed to the same entity (the same
  "other manager" value) should be valued at the same price, so value divided by shares
  should agree. A line is an exception if its implied price differs from the median for
  that security and entity by more than 0.5% plus what rounding the value to a whole
  unit can explain. Differences between entities are expected (they can price at
  different times or from different sources) and are measured separately by C17.
  Shares only: options and principal amounts are excluded.
impact: >
  One entity valuing one security at two prices on the same date means a quantity or a
  value on at least one line does not match the rest. Reports that read different lines
  will disagree.
runbook:
  - Compare the line's shares and value with the other lines for the same security and entity.
  - If the shares look wrong, check the position records; if the value looks wrong, check the price applied.
  - With two lines there is no majority, so both are flagged; establish which one is right before closing.
---*/
with scoped as (
    select
        *,
        value_usd / amount as implied_price,
        coalesce(other_manager, '') as entity_key
    from current_holding
    where is_plain_equity and amount > 0 and value_usd is not null and cusip is not null
),

priced as (
    select
        *,
        median(implied_price) over (partition by accession, cusip, entity_key) as median_price,
        count(*) over (partition by accession, cusip, entity_key) as n_lines
    from scoped
)

select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    median_price > 0
    and abs(implied_price / median_price - 1)
    > 0.005 + value_multiplier / greatest(value_usd, 1) as is_exception,
    value_usd,
    'implied price ' || cast(cast(round(implied_price, 4) as decimal(18, 4)) as varchar)
    || ' against median ' || cast(cast(round(median_price, 4) as decimal(18, 4)) as varchar)
    || ' across ' || cast(n_lines as varchar) || ' lines for other manager "' || entity_key || '" ('
    || cast(cast(round(100 * (implied_price / nullif(median_price, 0) - 1), 1) as decimal(10, 1)) as varchar)
    || '% off) (' || coalesce(issuer_name, '') || ')' as detail
from priced
where n_lines > 1
