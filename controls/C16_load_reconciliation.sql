/*---
id: C16
name: Warehouse reconciles to the source document (TrueSet)
dimension: completeness
severity: critical
scope: filing
owner: Data Engineering
description: >
  At load time every information table is read twice, by the main parser and by an
  independent reader that shares no code with it (a different XML library and XPath),
  and the warehouse is reconciled against the independent reading with TrueSet, an
  open-source data quality library: by count, then line by line on identifiers, values
  and codes. Keys missing on either side, duplicated keys and changed values are all
  reported. A document that cannot be read at all is reported here too, and the rest
  of the run carries on.
impact: >
  Every other control assumes the warehouse holds exactly what was filed. If parsing
  or loading drops, duplicates or alters lines, the other controls check the wrong
  data, and nothing else would show it.
runbook:
  - Read the TrueSet message and observed counts in the detail column (missing, extra, mismatched or duplicated keys), or the parse error.
  - Pick one failing line key and compare the XML element with the warehouse row to see which reader is wrong.
  - Fix the reader, add the case to the tests, and re-run `hdq build`.
  - Treat other control results for the filing as unreliable until this passes.
---*/
select
    accession,
    period_of_report,
    check_type as entity,
    cast(null as integer) as line_no,
    status <> 'pass' as is_exception,
    cast(null as double) as value_usd,
    suite || ' ' || check_type || ': ' || status
    || case when coalesce(message, '') <> '' then ' (' || message || ')' else '' end
    || case when observed is not null then '; observed ' || observed else '' end as detail
from raw_load_check
