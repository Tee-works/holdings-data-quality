/*---
id: C04
name: FIGI, where reported, is well formed with a valid check digit
dimension: validity
severity: medium
scope: holding
owner: Security Master
description: >
  FIGI is optional on Form 13F. Where it is reported it must be 12 characters: a
  two-letter prefix without vowels, "G" in third place, eight consonants or digits,
  and a check digit computed like the CUSIP one over the first eleven characters.
  Lines without a FIGI are outside the population, so the control reports n/a when
  no FIGIs are reported.
impact: >
  An invalid FIGI breaks the cross-reference between identifiers. Teams that key on
  FIGI rather than CUSIP (for example, vendor data and newer reference data feeds)
  silently lose the position.
runbook:
  - Compare the reported FIGI with the one held in the security master for the same CUSIP.
  - If the master value is valid, correct the extract mapping.
  - If the master value is also invalid, raise a reference data fix with the vendor feed owner.
  - Close when corrected or documented.
---*/
with scoped as (
    select * from current_holding
    where figi is not null
),

chars as (
    select
        h.accession,
        h.line_no,
        i.pos,
        substr(upper(h.figi), i.pos + 1, 1) as c
    from scoped as h
    cross join (values (0), (1), (2), (3), (4), (5), (6), (7), (8), (9), (10)) as i (pos)
    where length(h.figi) = 12
),

check_digit as (
    select
        accession,
        line_no,
        cast(mod(10 - mod(sum(floor(v / 10) + mod(v, 10)), 10), 10) as integer) as expected
    from (
        select
            accession,
            line_no,
            case
                when c between '0' and '9' then ascii(c) - 48
                else ascii(c) - 55
            end * case when mod(pos, 2) = 1 then 2 else 1 end as v
        from chars
    ) as cv
    group by accession, line_no
)

select
    h.accession,
    h.period_of_report,
    h.figi as entity,
    h.line_no,
    not coalesce(
        {{ full_match("upper(h.figi)", "[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]") }}
        and substr(upper(h.figi), 1, 2) not in ('BS', 'BM', 'GG', 'GB', 'GH', 'KY', 'VG')
        and substr(h.figi, 12, 1) = cast(d.expected as varchar),
        false
    ) as is_exception,
    h.value_usd,
    'FIGI ' || h.figi || ' on CUSIP ' || coalesce(h.cusip, '') || ' (' || coalesce(h.issuer_name, '')
    || '); check digit should be ' || coalesce(cast(d.expected as varchar), 'n/a') as detail
from scoped as h
left join check_digit as d on h.accession = d.accession and h.line_no = d.line_no
