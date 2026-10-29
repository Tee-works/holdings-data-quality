/*---
id: C09
name: Each CUSIP has one issuer name within a filing
dimension: consistency
severity: low
scope: holding
owner: Security Master
description: >
  All lines for the same CUSIP in a filing carry the same issuer name, compared after
  ignoring case, spaces and punctuation so that "APPLE INC" and "Apple Inc." agree.
impact: >
  Two names for one security usually means two reference data records. Reports that
  group by name split the position and understate the largest exposures.
runbook:
  - List the names reported for the CUSIP (see the detail column).
  - Check the security master for duplicate records or a stale name on one record.
  - Merge or correct the records; the reporting extract should take the name from the master only.
---*/
with names as (
    select
        *,
        upper({{ replace_all("coalesce(issuer_name, '')", "[^A-Za-z0-9]", "") }}) as name_key
    from current_holding
    where cusip is not null
),

per_cusip as (
    select
        accession,
        cusip,
        count(distinct name_key) as n_names,
        listagg(distinct issuer_name, ' | ') as names
    from names
    group by accession, cusip
)

select
    n.accession,
    n.period_of_report,
    n.cusip as entity,
    n.line_no,
    p.n_names > 1 as is_exception,
    n.value_usd,
    'CUSIP ' || n.cusip || ' reported as: ' || coalesce(p.names, '') as detail
from names as n
inner join per_cusip as p on n.accession = p.accession and n.cusip = p.cusip
