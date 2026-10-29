/*---
id: C07
name: Voting authority split matches shares held
dimension: consistency
severity: low
scope: holding
owner: Stewardship Data
description: >
  For plain share lines, sole, shared and no voting authority together equal the
  number of shares. Informational: the form does not require the three columns to add
  up to the holding (SEC Form 13F FAQ 50a), so a difference is a question for a
  stewardship team, not a reporting error. Options and principal amounts are excluded.
impact: >
  Voting and engagement reporting reads these columns. Where they do not cover the
  position, the votes a firm reports controlling will not reconcile to what it holds,
  and someone will ask why.
runbook:
  - Compare the voting split with the voting authority held on the proxy voting platform for the same date.
  - Shares on loan or held in accounts where voting is delegated are common, legitimate reasons; record them as explained.
  - Otherwise, find the step that fills the voting columns and check it against the position.
---*/
select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    abs(coalesce(voting_sole, 0) + coalesce(voting_shared, 0) + coalesce(voting_none, 0) - amount)
    > 0.5 as is_exception,
    value_usd,
    'voting authority '
    || cast(cast(coalesce(voting_sole, 0) + coalesce(voting_shared, 0) + coalesce(voting_none, 0) as bigint) as varchar)
    || ' (sole ' || cast(cast(coalesce(voting_sole, 0) as bigint) as varchar)
    || ', shared ' || cast(cast(coalesce(voting_shared, 0) as bigint) as varchar)
    || ', none ' || cast(cast(coalesce(voting_none, 0) as bigint) as varchar)
    || ') against ' || cast(cast(amount as bigint) as varchar) || ' shares ('
    || coalesce(issuer_name, '') || ')' as detail
from current_holding
where is_plain_equity and amount is not null
