"""The facts an OpenScript run needs about its instrument, from the platform.

The openalgo-script engine reads one record about the instrument a script runs
on (``Instrument`` in the package's ``engine/host.d.ts``, ``host-interface.md``
section 4.1): the tick size, the lot size, what kind of instrument it is, whether
it reports volume and open interest, the IANA zone its clock is read in, and its
trading session. A script's session facts (``session.isFirstBar``,
``session.isLastBar``, the bar ``vwap`` restarts on) come from that session and
that zone and from nothing else, so a host that holds a schedule and does not
state it gets every one of them absent, with nothing on the chart to say why.

Every fact here is read from the platform's own data and none is restated:

* **The contract** comes from the master contract through
  ``services.symbol_service.get_symbol_info``, the lookup behind
  ``/api/v1/symbol``.
* **The zone and the session** come from the market calendar
  (``database.market_calendar_db``). Its timings are admin-editable and its
  holiday table carries special sessions such as Muhurat trading, so no time of
  day, weekday or holiday is written in this module.

**The engine holds one window per run, and a special day is a second window.**
It cannot represent a day whose hours differ from the rest of the chart (4.3 and
4.4): Muhurat is 18:00 to 19:15 on a Sunday, and MCX trades an evening session
on an equity holiday. So the record states the exchange's regular window with
the calendar's weekday rule, which is what every historical bar on a chart is
read against, and today's effective window travels beside it under its own key.
A caller running live today may prefer that one; a caller drawing history
should not, because every other day on the chart would fall outside it.
"""

import copy
import math
import threading
from datetime import date, datetime
from typing import Any

from cachetools import TTLCache

from database.market_calendar_db import IST, get_effective_session_window, get_market_timing
from services.strategy_module.symbol_resolver import CASH_EXCHANGE_FOR
from services.symbol_service import get_symbol_info
from utils.constants import (
    CRYPTO_EXCHANGES,
    EXCHANGE_BSE,
    EXCHANGE_BSE_INDEX,
    EXCHANGE_GLOBAL_INDEX,
    EXCHANGE_MCX_INDEX,
    EXCHANGE_NSE,
    EXCHANGE_NSE_INDEX,
    FNO_EXCHANGES,
    INSTRUMENT_PERPFUT,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# One answer per (symbol, exchange, date), reused briefly. Short because the
# calendar's timings are admin-editable and an edit should reach the next chart
# within a minute; long enough that a chart restoring several studies on one
# instrument asks the master contract and the calendar once. Bounded, because
# production is a single worker that never restarts.
_CACHE_TTL_SECONDS = 60
_CACHE_MAXSIZE = 256
_cache: TTLCache = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()

# The exchanges that list only indices. A quote feed, never a contract.
_INDEX_EXCHANGES = frozenset(
    {EXCHANGE_NSE_INDEX, EXCHANGE_BSE_INDEX, EXCHANGE_MCX_INDEX, EXCHANGE_GLOBAL_INDEX}
)

# The weekday rule the calendar applies, in the record's numbering.
#
# ``market_calendar_db`` closes every exchange except a crypto one on a date
# whose ``weekday()`` is 5 or 6 unless a special session is held there, and never
# closes a crypto exchange. The record numbers Monday as 1 through Sunday as 7,
# which is ``date.isoweekday()``. The calendar exports no constant for the rule,
# so it is stated once here, and a test holds it to the calendar's own answer for
# every day of a week.
_TRADING_WEEKDAYS = (1, 2, 3, 4, 5)
_EVERY_DAY = (1, 2, 3, 4, 5, 6, 7)

_MINUTE_MS = 60_000
_DAY_MINUTES = 24 * 60


def clear_instrument_facts_cache() -> None:
    """Forget every cached answer."""
    with _cache_lock:
        _cache.clear()


def _calendar_exchange(exchange: str) -> str:
    """The exchange whose calendar an instrument trades on.

    An index has no calendar entry of its own: it is computed while the cash
    market of its exchange trades. ``CASH_EXCHANGE_FOR`` is the platform's
    statement of which cash exchange that is, and it is reused here rather than
    written again. An index exchange it does not name (MCX_INDEX, GLOBAL_INDEX)
    stays unknown to the calendar and so is stated with no session.
    """
    return CASH_EXCHANGE_FOR.get(exchange, exchange)


def _clock(offset_ms: int, *, closing: bool) -> str:
    """A calendar offset from IST midnight as the record's ``"HH:MM"``.

    The calendar treats both ends of a window as inside it
    (``start_ms <= now <= end_ms``), and the record's close is exclusive
    (openalgo-script ``session/hours.d.ts``). On a whole minute the two agree.
    A close the calendar states to the second, which is how it writes the
    crypto day (to 23:59:59), is rounded up to the next minute, so that day ends
    at ``"24:00"``, the record's spelling of midnight at the end of the day. A
    close past midnight (MCX Muhurat runs to 00:15 the next morning) is written
    as the clock reads it, and the record takes an end before its start as a
    window that crosses midnight.
    """
    minutes = -(-offset_ms // _MINUTE_MS) if closing else offset_ms // _MINUTE_MS
    if closing and minutes == _DAY_MINUTES:
        return "24:00"
    minutes %= _DAY_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _midnight_ms(on_date: date) -> int:
    """Epoch milliseconds of IST midnight on a date, the calendar's own anchor."""
    return int(IST.localize(datetime.combine(on_date, datetime.min.time())).timestamp() * 1000)


def _regular_session(calendar_exchange: str) -> dict[str, Any] | None:
    """The exchange's regular window from the calendar's timing table.

    None when the calendar holds no timing for the exchange. That is stated as
    no session rather than a borrowed one: host-interface.md 4.3 reads a missing
    session as an instrument whose schedule the host does not hold, which is
    true, and a wrong one would move every session fact on the chart.
    """
    timing = get_market_timing(calendar_exchange)
    if not timing:
        return None
    days = _EVERY_DAY if calendar_exchange in CRYPTO_EXCHANGES else _TRADING_WEEKDAYS
    return {
        "start": _clock(int(timing["start_offset"]), closing=False),
        "end": _clock(int(timing["end_offset"]), closing=True),
        "days": list(days),
    }


def _today(calendar_exchange: str, on_date: date) -> dict[str, Any]:
    """The calendar's effective window on one date.

    ``get_effective_session_window`` already resolves special sessions, holiday
    evening windows, holidays and weekends in that order, so this only restates
    its answer in the record's spelling. ``session`` names the one day it holds
    for, so it can stand in for the regular session on a run that is about that
    day alone.
    """
    window = get_effective_session_window(on_date, calendar_exchange)
    today: dict[str, Any] = {
        "date": on_date.isoformat(),
        "open": window is not None,
        "isSpecial": bool(window and window.get("is_special")),
    }
    if window:
        midnight = _midnight_ms(on_date)
        today["session"] = {
            "start": _clock(int(window["start_ms"]) - midnight, closing=False),
            "end": _clock(int(window["end_ms"]) - midnight, closing=True),
            "days": [on_date.isoweekday()],
        }
    return today


def _instrument_type(exchange: str, code: str | None) -> str | None:
    """The record's word for an instrument, from its exchange and contract code.

    host-interface.md 4.1 allows seven words and says a host with none of them
    to say states nothing rather than inventing an eighth. The master contract
    code is each broker's own spelling (FUT and CE, FUTIDX and OPTSTK, INDEX,
    IDX or AMXIDX for an index, CUR and COM for a whole currency or commodity
    segment), so the families are read rather than any one broker's list.
    ``code`` is None when there is no contract, and then only an index exchange
    says what the instrument is.
    """
    if exchange in _INDEX_EXCHANGES:
        return "index"
    if code is None:
        return None
    kind = code.strip().upper()
    if kind in ("INDEX", "IDX", "AMXIDX"):
        return "index"
    if kind in ("CE", "PE") or kind.startswith("OPT"):
        return "option"
    if kind == INSTRUMENT_PERPFUT or kind.startswith("FUT"):
        return "future"
    if kind in ("EQ", "BE"):
        return "equity"
    # Some brokers write no code at all on their cash rows, which is the whole
    # cash segment, the same set every other broker calls EQ.
    if not kind and exchange in (EXCHANGE_NSE, EXCHANGE_BSE):
        return "equity"
    if kind == "CUR":
        return "currency"
    if kind == "COM":
        return "commodity"
    return None


def _has_open_interest(exchange: str, code: str | None, kind: str | None) -> bool:
    """Whether open interest means anything for this instrument.

    Derivatives carry open interest and nothing else does. The contract's own
    type answers when it names one; otherwise the exchange does, because every
    contract on a derivatives exchange is a derivative, except a crypto spot
    pair, which the master contract marks SPOT.
    """
    if kind in ("future", "option"):
        return True
    if kind in ("equity", "index"):
        return False
    if code is not None and code.strip().upper() == "SPOT":
        return False
    return exchange in FNO_EXCHANGES


def _positive(value: Any) -> int | float | None:
    """A tick or lot size, or None. host-interface.md 4.1: zero is not a size."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return int(number) if number.is_integer() else number


def _contract(symbol: str, exchange: str) -> tuple[dict[str, Any] | None, bool]:
    """The master contract row, and whether the answer can be trusted.

    Trusted means the lookup ran: a row, or a clean "no such symbol". A lookup
    that failed says nothing about the symbol, so the caller does not cache it.
    """
    if not symbol or not exchange:
        return None, True
    try:
        found, response, status = get_symbol_info(symbol=symbol, exchange=exchange)
    except Exception:
        logger.exception(f"Master contract lookup failed for {symbol} on {exchange}")
        return None, False
    if found:
        row = response.get("data")
        return (row if isinstance(row, dict) else None), True
    if status == 404:
        return None, True
    # get_symbol_info has already logged the failure with its traceback.
    return None, False


def get_instrument_facts(symbol: str, exchange: str, on_date: date | None = None) -> dict[str, Any]:
    """The instrument record for one symbol, plus the calendar's window on a date.

    Args:
        symbol: OpenAlgo symbol, as the master contract stores it.
        exchange: OpenAlgo exchange code, in any case.
        on_date: The date ``today`` describes. Defaults to today in the
            calendar's own zone.

    Returns:
        ``{"symbol", "contractFound", "instrument", "today"}``. ``instrument``
        uses the engine's field names and leaves out every fact the platform
        does not hold, which the engine reads as absent. ``today`` is None when
        the calendar does not know the exchange, since there is then no window
        to state and "closed" would be a guess.
    """
    symbol = (symbol or "").strip()
    exchange = (exchange or "").strip().upper()
    on_date = on_date or datetime.now(IST).date()

    key = (symbol, exchange, on_date.isoformat())
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return copy.deepcopy(cached)

    row, trusted = _contract(symbol, exchange)
    code = None
    if row is not None:
        raw = row.get("instrumenttype")
        code = raw if isinstance(raw, str) else ""
    kind = _instrument_type(exchange, code)

    # The calendar reads every exchange it holds in one zone, crypto included,
    # so that zone's own name is the record's timezone.
    instrument: dict[str, Any] = {"exchange": exchange, "timezone": IST.zone}
    if row is not None:
        tick = _positive(row.get("tick_size"))
        lot = _positive(row.get("lotsize"))
        if tick is not None:
            instrument["tickSize"] = tick
        if lot is not None:
            instrument["lotSize"] = lot
    if kind is not None:
        instrument["instrumentType"] = kind
    # host-interface.md 4.2: the one fact a host must state. An index is a
    # computed value with no trades behind it, so it has no volume; everything
    # else on this platform reports one.
    instrument["hasVolume"] = kind != "index"
    instrument["hasOpenInterest"] = _has_open_interest(exchange, code, kind)

    calendar_exchange = _calendar_exchange(exchange)
    session = _regular_session(calendar_exchange)
    if session is not None:
        instrument["session"] = session

    facts = {
        "symbol": symbol,
        "contractFound": row is not None,
        "instrument": instrument,
        "today": _today(calendar_exchange, on_date) if session is not None else None,
    }

    if trusted:
        with _cache_lock:
            _cache[key] = facts
    return copy.deepcopy(facts)
