"""US federal holidays, for the SEC filing deadline (C13).

When day 45 after quarter end falls on a weekend or a federal holiday, a 13F is due
on the next business day (SEC Form 13F FAQ 25). Rules as in 5 U.S.C. 6103, with the
usual observance: a Saturday holiday is observed on the Friday, a Sunday one on the Monday.
"""

from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


MON, THU = 0, 3


def us_federal_holidays(year: int) -> dict[date, str]:
    days = {
        _observed(date(year, 1, 1)): "New Year's Day",
        _nth_weekday(year, 1, MON, 3): "Martin Luther King Jr. Day",
        _nth_weekday(year, 2, MON, 3): "Washington's Birthday",
        _last_weekday(year, 5, MON): "Memorial Day",
        _observed(date(year, 7, 4)): "Independence Day",
        _nth_weekday(year, 9, MON, 1): "Labor Day",
        _nth_weekday(year, 10, MON, 2): "Columbus Day",
        _observed(date(year, 11, 11)): "Veterans Day",
        _nth_weekday(year, 11, THU, 4): "Thanksgiving Day",
        _observed(date(year, 12, 25)): "Christmas Day",
    }
    if year >= 2021:
        days[_observed(date(year, 6, 19))] = "Juneteenth"
    return days


def holiday_rows(first_year: int, last_year: int) -> list[dict]:
    return [
        {"holiday_date": d, "name": name}
        for y in range(first_year, last_year + 1)
        for d, name in sorted(us_federal_holidays(y).items())
    ]
