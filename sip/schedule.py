"""Generating the dates and amounts of a SIP.

Separated from the simulation because the schedule is where most of the
real-world awkwardness lives -- month ends, market holidays, annual step-ups --
and it is far easier to test as a pure function of (start, end, frequency) than
tangled into a price loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

FREQUENCIES = ("monthly", "fortnightly", "weekly", "quarterly")

#: SIP dates above 28 are rejected rather than clamped. A user who picks the
#: 31st means "month end", and silently turning that into the 28th in February
#: while leaving it on the 31st in March produces an irregular schedule the
#: user never asked for. Month-end is available explicitly instead.
MAX_DAY_OF_MONTH = 28


class ScheduleError(ValueError):
    """The requested SIP schedule cannot be built."""


@dataclass(frozen=True)
class Installment:
    """One scheduled investment.

    ``requested`` is the calendar date the user asked for; ``executed`` is the
    trading session it actually landed on. Keeping both means the results page
    can show that a 1st-of-month SIP really transacted on the 2nd because the
    1st was a holiday, instead of quietly rewriting history.
    """

    requested: date
    executed: date
    amount: float


def _month_add(anchor: date, months: int) -> date:
    """Add whole months, holding the day of month fixed.

    Day is capped at 28 by validation upstream, so this never has to decide
    what "31 February" means.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    return date(year, month, anchor.day)


def requested_dates(
    start: date,
    end: date,
    frequency: str = "monthly",
    day_of_month: int = 1,
) -> list[date]:
    """The calendar dates a SIP would target, ignoring market holidays."""
    if frequency not in FREQUENCIES:
        raise ScheduleError(
            f"frequency must be one of {', '.join(FREQUENCIES)}, got {frequency!r}"
        )
    if end < start:
        raise ScheduleError("end date is before start date")

    if frequency in ("monthly", "quarterly"):
        if not 1 <= day_of_month <= MAX_DAY_OF_MONTH:
            raise ScheduleError(
                f"day_of_month must be between 1 and {MAX_DAY_OF_MONTH}; "
                "days after the 28th do not exist in every month"
            )
        step = 1 if frequency == "monthly" else 3
        # Anchor on the requested day in the start month, then step forward.
        try:
            anchor = date(start.year, start.month, day_of_month)
        except ValueError as exc:  # pragma: no cover - guarded above
            raise ScheduleError(str(exc)) from exc
        if anchor < start:
            anchor = _month_add(anchor, step)
        out = []
        i = 0
        while True:
            when = _month_add(anchor, i * step)
            if when > end:
                break
            out.append(when)
            i += 1
        return out

    delta = timedelta(days=7 if frequency == "weekly" else 14)
    out, when = [], start
    while when <= end:
        out.append(when)
        when += delta
    return out


def apply_step_up(
    dates: list[date],
    base_amount: float,
    step_up_percent: float = 0.0,
) -> list[float]:
    """Amount per installment, raised by ``step_up_percent`` each year.

    Step-up SIPs are common in India because contributions track salary growth,
    and ignoring them understates the final corpus badly over long horizons.
    The increase applies on each anniversary of the first installment, not on
    calendar-year boundaries, so a SIP started in October steps up in October.
    """
    if not dates:
        return []
    if step_up_percent < 0:
        raise ScheduleError("step_up_percent cannot be negative")

    first = dates[0]
    amounts = []
    for when in dates:
        years_elapsed = (when - first).days // 365
        amounts.append(base_amount * ((1.0 + step_up_percent / 100.0) ** years_elapsed))
    return amounts


def build_schedule(
    sessions: pd.DatetimeIndex,
    start: date,
    end: date,
    amount: float,
    *,
    frequency: str = "monthly",
    day_of_month: int = 1,
    step_up_percent: float = 0.0,
) -> list[Installment]:
    """Map requested SIP dates onto real trading sessions.

    A SIP scheduled for a Sunday or a market holiday executes on the next
    available session, which is what a broker or fund house actually does. An
    installment whose next session falls beyond ``end`` is dropped rather than
    executed late, because money that was never invested should not appear in
    the cash flows.

    Args:
        sessions: trading dates available in the price data, ascending.
        start, end: the SIP window.
        amount: the base installment before any step-up.
        frequency: one of ``FREQUENCIES``.
        day_of_month: target day for monthly and quarterly SIPs.
        step_up_percent: annual increase applied on each anniversary.

    Returns:
        Installments in date order. Empty if no requested date has a session.
    """
    if amount <= 0:
        raise ScheduleError("SIP amount must be positive")
    if sessions is None or len(sessions) == 0:
        raise ScheduleError("no trading sessions available for this period")

    wanted = requested_dates(start, end, frequency, day_of_month)
    if not wanted:
        raise ScheduleError(
            "the SIP window is too short to contain a single installment"
        )

    amounts = apply_step_up(wanted, amount, step_up_percent)
    session_dates = [d.date() if hasattr(d, "date") else d for d in sessions]

    out: list[Installment] = []
    cursor = 0
    for when, value in zip(wanted, amounts, strict=True):
        # Sessions are sorted, and requested dates are ascending, so the search
        # only ever moves forward -- linear overall rather than per-installment.
        while cursor < len(session_dates) and session_dates[cursor] < when:
            cursor += 1
        if cursor >= len(session_dates):
            break
        executed = session_dates[cursor]
        if executed > end:
            break
        out.append(Installment(requested=when, executed=executed, amount=value))

    if not out:
        raise ScheduleError(
            "no SIP installment could be placed on a trading session in this window"
        )
    return out
