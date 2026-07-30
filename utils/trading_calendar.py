# utils/trading_calendar.py
"""Trading-day arithmetic for calendar-aware strategies.

Flow keeps no state between runs, so a workflow cannot remember the previous
run's date to notice that a new day, week, month or quarter has begun. It does
not need to: "a new month started" is the same statement as "today is the first
trading day of this month", and that is answerable from the exchange calendar
alone, with no memory.

Answering it from the calendar is also more correct than the obvious
alternatives. ``day == 1`` misses a 1st that falls on a Sunday or a holiday,
and ``weekday == Monday`` misses a week whose Monday is a holiday.

Deliberately not exchange-aware: a date is a trading holiday if the exchange
calendar lists it as one. MCX keeps a slightly different calendar from NSE on a
few days a year, and modelling that here would put an exchange selector on
every calendar question for a difference that almost no strategy depends on.

All dates are IST trading-session dates - see ``utils.session``.
"""

from datetime import date, timedelta

from cachetools import TTLCache

from utils.logging import get_logger

logger = get_logger(__name__)

# One entry per year, refreshed daily. The holiday list for a year changes only
# when the exchange publishes a revision, and the key space is years.
_HOLIDAY_CACHE: TTLCache = TTLCache(maxsize=8, ttl=60 * 60 * 24)

PERIODS = ("day", "week", "month", "quarter", "year")


def quarter_of(day: date) -> int:
    """Calendar quarter, 1 through 4."""
    return (day.month - 1) // 3 + 1


def _calendar_entries(year: int) -> tuple[frozenset[date], frozenset[date]]:
    """(dates the exchange is closed, dates it holds a special session).

    The feed mixes three kinds of entry and they mean opposite things:

    * ``TRADING_HOLIDAY`` closes equity trading. Most carry an open MCX
      session, which this module ignores by design (not exchange-aware).
    * ``SPECIAL_SESSION`` is the reverse - a session held on a day the market
      would otherwise be shut, such as Diwali Muhurat trading, which falls on a
      Sunday. Treating it as a closure would hide a real trading day and shift
      every adjacent-day and new-period answer around it.
    * Anything else (for example a settlement-only holiday) does not stop
      trading, so it is not a closure either.

    Empty sets on failure, never raising: that degrades to "weekends only",
    which errs toward treating a day as tradable rather than skipping a real
    session.
    """
    cached = _HOLIDAY_CACHE.get(year)
    if cached is not None:
        return cached

    closed: set[date] = set()
    special: set[date] = set()
    try:
        from services.market_calendar_service import get_holidays

        success, response, _ = get_holidays(year=year)
        if success:
            for entry in response.get("data") or []:
                raw = entry.get("date")
                if not raw:
                    continue
                try:
                    day = date.fromisoformat(str(raw)[:10])
                except ValueError:
                    continue
                kind = str(entry.get("holiday_type") or "").upper()
                if kind == "SPECIAL_SESSION" or not (entry.get("closed_exchanges") or []):
                    special.add(day)
                elif kind == "TRADING_HOLIDAY":
                    closed.add(day)
                # Other entry types leave trading open, so they are neither.
        else:
            logger.warning(f"Holiday list for {year} unavailable; assuming weekends only")
    except Exception:
        logger.exception(f"Could not load holidays for {year}; assuming weekends only")

    result = (frozenset(closed), frozenset(special))
    _HOLIDAY_CACHE[year] = result
    return result


def trading_holidays(year: int) -> frozenset[date]:
    """Dates the exchange is closed for trading in `year`."""
    return _calendar_entries(year)[0]


def special_sessions(year: int) -> frozenset[date]:
    """Dates with a session the calendar would otherwise not have, e.g. Muhurat."""
    return _calendar_entries(year)[1]


def is_trading_day(day: date) -> bool:
    """Whether the exchange trades on this date.

    A special session wins over the weekend rule: Muhurat trading is held on a
    Sunday, and returning False for it would hide a real session.
    """
    if day in special_sessions(day.year):
        return True
    if day in trading_holidays(day.year):
        return False
    return day.weekday() < 5


def prev_trading_day(day: date) -> date:
    """The most recent trading day strictly before `day`."""
    cursor = day - timedelta(days=1)
    for _ in range(30):  # a 30-day gap has never occurred; bounds the loop
        if is_trading_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return cursor


def next_trading_day(day: date) -> date:
    """The next trading day strictly after `day`."""
    cursor = day + timedelta(days=1)
    for _ in range(30):
        if is_trading_day(cursor):
            return cursor
        cursor += timedelta(days=1)
    return cursor


def _period_start(day: date, period: str) -> date:
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())  # Monday
    if period == "month":
        return day.replace(day=1)
    if period == "quarter":
        return day.replace(month=3 * (quarter_of(day) - 1) + 1, day=1)
    if period == "year":
        return day.replace(month=1, day=1)
    raise ValueError(f"Unknown period '{period}'; expected one of {PERIODS}")


def _period_end(day: date, period: str) -> date:
    if period == "day":
        return day
    if period == "week":
        return _period_start(day, "week") + timedelta(days=6)
    if period == "month":
        following = day.replace(day=28) + timedelta(days=4)
        return following.replace(day=1) - timedelta(days=1)
    if period == "quarter":
        last_month = 3 * quarter_of(day)
        return _period_end(day.replace(month=last_month, day=1), "month")
    if period == "year":
        return day.replace(month=12, day=31)
    raise ValueError(f"Unknown period '{period}'; expected one of {PERIODS}")


def first_trading_day_of(day: date, period: str) -> date:
    """The first trading day of the period containing `day`."""
    cursor = _period_start(day, period)
    end = _period_end(day, period)
    while cursor <= end and not is_trading_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def last_trading_day_of(day: date, period: str) -> date:
    """The last trading day of the period containing `day`."""
    cursor = _period_end(day, period)
    start = _period_start(day, period)
    while cursor >= start and not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def is_first_trading_day_of(day: date, period: str) -> bool:
    """Whether a new period began on this trading day.

    This is the stateless form of "is a new week/month/quarter starting".
    False on a non-trading day: nothing starts on a day the exchange is shut.
    """
    if not is_trading_day(day):
        return False
    return day == first_trading_day_of(day, period)


def is_last_trading_day_of(day: date, period: str) -> bool:
    """Whether this trading day closes the period - the squaring-off case."""
    if not is_trading_day(day):
        return False
    return day == last_trading_day_of(day, period)


def describe(day: date) -> dict:
    """Everything a workflow might branch on for one date."""
    return {
        "date": day.isoformat(),
        "is_trading_day": is_trading_day(day),
        # Closed by the calendar rather than by the weekend.
        "is_trading_holiday": day in trading_holidays(day.year),
        # A pure calendar property: a special session can fall on a weekend, so
        # this does not imply the market is shut.
        "is_weekend": day.weekday() >= 5,
        "is_special_session": day in special_sessions(day.year),
        "weekday": day.strftime("%A"),
        "weekday_num": day.isoweekday(),  # 1 = Monday
        "day": day.day,
        "month": day.month,
        "quarter": quarter_of(day),
        "year": day.year,
        "week_of_year": day.isocalendar().week,
        "day_of_year": day.timetuple().tm_yday,
        "is_new_day": is_first_trading_day_of(day, "day"),
        "is_new_week": is_first_trading_day_of(day, "week"),
        "is_new_month": is_first_trading_day_of(day, "month"),
        "is_new_quarter": is_first_trading_day_of(day, "quarter"),
        "is_new_year": is_first_trading_day_of(day, "year"),
        "is_last_day_of_week": is_last_trading_day_of(day, "week"),
        "is_last_day_of_month": is_last_trading_day_of(day, "month"),
        "is_last_day_of_quarter": is_last_trading_day_of(day, "quarter"),
        "is_last_day_of_year": is_last_trading_day_of(day, "year"),
        "prev_trading_day": prev_trading_day(day).isoformat(),
        "next_trading_day": next_trading_day(day).isoformat(),
        "first_trading_day_of_week": first_trading_day_of(day, "week").isoformat(),
        "first_trading_day_of_month": first_trading_day_of(day, "month").isoformat(),
        "first_trading_day_of_quarter": first_trading_day_of(day, "quarter").isoformat(),
        "last_trading_day_of_week": last_trading_day_of(day, "week").isoformat(),
        "last_trading_day_of_month": last_trading_day_of(day, "month").isoformat(),
        "last_trading_day_of_quarter": last_trading_day_of(day, "quarter").isoformat(),
    }
