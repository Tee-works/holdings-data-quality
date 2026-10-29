/*---
id: C11
name: Large quarter-on-quarter price moves, for review
dimension: accuracy
severity: low
scope: period
owner: Pricing
description: >
  For each security held in two consecutive quarters, an implied price that moves by
  more than a factor of three is listed for review. Stock splits and consolidations are
  recognised and cleared automatically: for a price that falls to roughly 1/k (or rises
  to roughly k times) for a whole number k of 2 or more, with the share count moving by
  between 0.67k and 1.5k the other way, the move is recorded as a likely k-for-1 split
  (or 1-for-k consolidation). The tolerance allows for the position itself growing or
  shrinking in the same quarter. Genuine large moves (takeovers, distressed securities,
  momentum stocks) will appear here every quarter; that is expected.
impact: >
  A price that moves threefold in a quarter is a real market event, a corporate action
  the reference data must reflect, or an error in shares or value. Telling these apart
  early keeps performance and quarter-on-quarter reporting honest.
runbook:
  - Check corporate action records for a split, consolidation, spin-off or rights issue in the quarter.
  - If there was one, confirm the security master and position history reflect it, then mark explained.
  - If not, compare the quarter-end market price with the implied price in both quarters to see which side moved.
  - Record the explanation (market move, corporate action or data error) and close.
---*/
with paired as (
    select
        cur.accession,
        cur.period_of_report,
        cur.cusip,
        cur.issuer_name,
        cur.value_usd,
        cur.implied_price / prev.implied_price as price_ratio,
        cur.shares / prev.shares as share_ratio,
        prev.implied_price as prev_price,
        cur.implied_price as cur_price
    from security_position as cur
    inner join security_position as prev
        on cur.cusip = prev.cusip and cur.period_seq = prev.period_seq + 1
    where prev.implied_price > 0 and cur.implied_price > 0 and prev.shares > 0
),

classified as (
    select
        *,
        price_ratio > 3 or price_ratio < 1.0 / 3 as big_move,
        case
            when price_ratio < 1 then round(1 / price_ratio)
            else round(price_ratio)
        end as k
    from paired
),

judged as (
    select
        *,
        k >= 2
        and (
            (price_ratio < 1 and share_ratio / k between 0.67 and 1.5)
            or (price_ratio > 1 and share_ratio * k between 0.67 and 1.5)
        ) as likely_split
    from classified
)

select
    accession,
    period_of_report,
    cusip as entity,
    cast(null as integer) as line_no,
    big_move and not likely_split as is_exception,
    big_move and likely_split as explained,
    value_usd,
    'price ' || cast(cast(round(prev_price, 4) as decimal(18, 4)) as varchar)
    || ' to ' || cast(cast(round(cur_price, 4) as decimal(18, 4)) as varchar)
    || ' (x' || cast(cast(round(price_ratio, 3) as decimal(18, 3)) as varchar)
    || '); shares x' || cast(cast(round(share_ratio, 3) as decimal(18, 3)) as varchar)
    || case
        when big_move and likely_split
            then
                ': likely '
                || case
                    when price_ratio < 1 then cast(cast(k as integer) as varchar) || '-for-1 split'
                    else '1-for-' || cast(cast(k as integer) as varchar) || ' consolidation'
                end
        else ''
    end
    || ' (' || coalesce(issuer_name, '') || ')' as detail
from judged
