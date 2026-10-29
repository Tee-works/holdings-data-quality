/*---
id: C03
name: CUSIP is well formed with a valid check digit
dimension: validity
severity: high
scope: holding
owner: Security Master
description: >
  Every line carries a 9-character CUSIP whose ninth character is the modulus 10
  "double add double" check digit of the first eight. Written in plain SQL so it runs
  on any warehouse; the Python implementation is used only to test it.
impact: >
  A CUSIP that fails its check digit cannot be matched to the security master, so the
  position drops out of exposure, compliance and stewardship reports that join on it.
runbook:
  - Take the issuer name and class from the line and look the security up in the security master.
  - If the master holds a valid CUSIP for it, the error is in the extract or a manual override; correct at source.
  - If the master holds the same invalid CUSIP, raise a security master data fix.
  - Check whether other filings use the same invalid identifier (search exceptions by entity).
  - Close when the identifier is corrected or the line is documented as a known placeholder.
---*/
with chars as (
    select
        h.accession,
        h.line_no,
        i.pos,
        substr(h.cusip, i.pos + 1, 1) as c
    from current_holding as h
    cross join (values (0), (1), (2), (3), (4), (5), (6), (7)) as i (pos)
    where length(h.cusip) = 9
),

char_values as (
    select
        accession,
        line_no,
        case
            when c between '0' and '9' then ascii(c) - 48
            when c between 'A' and 'Z' then ascii(c) - 55
            when c = '*' then 36
            when c = '@' then 37
            when c = '#' then 38
        end * case when mod(pos, 2) = 1 then 2 else 1 end as v
    from chars
),

check_digit as (
    select
        accession,
        line_no,
        max(case when v is null then 1 else 0 end) = 1 as has_bad_char,
        cast(mod(10 - mod(sum(floor(v / 10) + mod(v, 10)), 10), 10) as integer) as expected
    from char_values
    group by accession, line_no
)

select
    h.accession,
    h.period_of_report,
    h.cusip as entity,
    h.line_no,
    coalesce(
        d.line_no is null
        or d.has_bad_char
        or substr(h.cusip, 9, 1) <> cast(d.expected as varchar),
        true
    ) as is_exception,
    h.value_usd,
    case
        when h.cusip is null then 'CUSIP missing'
        when length(h.cusip) <> 9
            then 'CUSIP ' || h.cusip || ' is ' || cast(length(h.cusip) as varchar) || ' characters, expected 9'
        when d.has_bad_char then 'CUSIP ' || h.cusip || ' contains a character outside 0-9, A-Z, *, @, #'
        else
            'CUSIP ' || h.cusip || ' (' || coalesce(h.issuer_name, '') || '): check digit should be '
            || cast(d.expected as varchar)
    end as detail
from current_holding as h
left join check_digit as d on h.accession = d.accession and h.line_no = d.line_no
