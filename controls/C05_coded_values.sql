/*---
id: C05
name: Coded fields use the values the form allows
dimension: validity
severity: high
scope: holding
owner: Investment Data Operations
description: >
  Amount type is SH or PRN; investment discretion is SOLE, DFND or OTR; put/call is
  empty, Put or Call.
impact: >
  These codes decide how a line is aggregated. An unknown discretion code drops the
  line from the "sole versus shared" splits used in stewardship reporting; a wrong
  amount type mixes share counts with bond principal.
runbook:
  - Read the failing field and value from the detail column.
  - Find the mapping that produces the field in the reporting extract and the source value that fed it.
  - Add the missing mapping or correct the source value; never hand-edit the filing output.
  - Close when the next run passes or an amendment is filed.
---*/
select
    accession,
    period_of_report,
    cusip as entity,
    line_no,
    coalesce(upper(amount_type) not in ('SH', 'PRN'), true)
    or coalesce(upper(investment_discretion) not in ('SOLE', 'DFND', 'OTR'), true)
    or (put_call is not null and upper(put_call) not in ('PUT', 'CALL')) as is_exception,
    value_usd,
    case
        when coalesce(upper(amount_type) not in ('SH', 'PRN'), true)
            then 'amount type ' || coalesce(amount_type, 'missing') || '; '
        else ''
    end
    || case
        when coalesce(upper(investment_discretion) not in ('SOLE', 'DFND', 'OTR'), true)
            then 'investment discretion ' || coalesce(investment_discretion, 'missing') || '; '
        else ''
    end
    || case
        when put_call is not null and upper(put_call) not in ('PUT', 'CALL')
            then 'put/call ' || put_call || '; '
        else ''
    end
    || '(' || coalesce(issuer_name, '') || ')' as detail
from current_holding
