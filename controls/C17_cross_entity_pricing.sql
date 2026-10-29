/*---
id: C17
name: Group entities value each security at a consistent price
dimension: consistency
severity: low
scope: holding
owner: Pricing
description: >
  For securities reported under more than one entity (the "other manager" column),
  each entity's implied price (its total value over its total shares) is compared
  with the median across entities in the same filing. An entity-security pair more than
  2% away is listed. Informational: entities in a group can legitimately value at
  different times of day or from different sources. The control measures how often
  that happens and by how much, which is the first question in any pricing
  consistency review.
impact: >
  When one firm reports the same security at different prices, group-level exposure
  depends on which entity's figures are used, and the difference flows into any
  aggregate built from the filing.
runbook:
  - Check whether the entities concerned use a different pricing point or source by policy.
  - If they do, record the policy as the explanation and close; if they should not differ, raise with the pricing team.
  - Look for a pattern: one entity consistently away from the others points to a policy difference rather than a data error.
---*/
with per_entity as (
    select
        accession,
        cusip,
        coalesce(other_manager, '') as entity_key,
        min(period_of_report) as period_of_report,
        min(issuer_name) as issuer_name,
        sum(value_usd) as value_usd,
        sum(value_usd) / sum(amount) as entity_price,
        max(value_multiplier) as value_multiplier
    from current_holding
    where is_plain_equity and amount > 0 and value_usd is not null and cusip is not null
    group by accession, cusip, coalesce(other_manager, '')
),

compared as (
    select
        *,
        median(entity_price) over (partition by accession, cusip) as median_price,
        count(*) over (partition by accession, cusip) as n_entities
    from per_entity
)

select
    accession,
    period_of_report,
    cusip || ' / ' || entity_key as entity,
    cast(null as integer) as line_no,
    median_price > 0
    and abs(entity_price / median_price - 1)
    > 0.02 + value_multiplier / greatest(value_usd, 1) as is_exception,
    value_usd,
    'other manager "' || entity_key || '" values ' || coalesce(issuer_name, '') || ' at '
    || cast(cast(round(entity_price, 4) as decimal(18, 4)) as varchar)
    || ' against a median of ' || cast(cast(round(median_price, 4) as decimal(18, 4)) as varchar)
    || ' across ' || cast(n_entities as varchar) || ' entities ('
    || cast(cast(round(100 * (entity_price / nullif(median_price, 0) - 1), 1) as decimal(10, 1)) as varchar)
    || '% off)' as detail
from compared
where n_entities > 1
