"""Pocketful market data over REST: quotes, depth, multiquotes, LTP and history.

Every request goes through ``baseurl.pocketful_request`` and through this
module's pacer. Nothing here opens the Pocketful WebSocket: quotes and depth
used to subscribe on the feed and wait for a packet; the API now answers them
over REST.

Sources (offline copy of https://api.pocketful.in/docs/curl, 2026-11-17, and
the official Python SDK ``pocketful`` 0.1.2, ``pocketful.py``):

Quotes. ``GET /api/v1/marketdata/{exchange}/{segment}?token=<token>``
(get-market-data.md; SDK routes ``api.marketdata`` and ``api.fnodata``). The
segment is ``Capital`` for NSE and BSE, ``FutOpt`` for NFO, BFO and MCX and
``Currency`` for CDS. The market data pages print every exchange under
``/Capital``, but the segment table on chart-data.md ("Segment Mapping for F&O
and Market Data") and the SDK's separate ``FutOpt`` routes agree on the
mapping used here. Indices are quoted on their cash exchange: the docs' own LTP
and closing price examples ask for ``('NSE', 26009)``, an index token, on the
``Capital`` route. BSE indices follow by analogy; no page shows one.

LTP. The same route with ``&key=last_trade_price`` (get-last-traded-price.md;
SDK ``api.ltpdata`` and ``api.fnoLtpdata``), answering a bare number.

Depth. The REST API has no five level book: the market data answer carries the
best bid and ask only (``bid_price``, ``bid_qty``, ``ask_price``, ``ask_qty``).
get_depth returns that as level one and pads levels two to five with zeros.
The five level book exists only on the WebSocket (snapquote-data.md).

Price units. The documented market data answer gives ``last_trade_price``,
``open_price``, ``high_price``, ``low_price``, ``close_price`` and
``average_trade_price`` in rupees but ``bid_price`` and ``ask_price`` in paise:
token 14366 at 12.90 with a bid of 1285 and an ask of 1290 (``yearly_high``
and ``yearly_low`` read the same way). The book prices are divided by 100,
unless the undivided figure is the one near the rupee prices, so an answer
that sends rupees is read correctly too (see _book_price).

Multiquotes. The market data route takes one token, and no page or SDK route
takes several, so get_multiquotes sends one request per symbol, paced.

Rate limits (annexure.md): Data APIs 10 a second, 1,000 a minute, 5,000 an
hour, 10,000 a day; HTTP 429 when exceeded. Every data request here is paced
at about 8 a second from module-level state (services build a new BrokerData
per request), and a 429 is retried twice with backoff. The hourly and daily
budgets are not paced: Pocketful's 429 is the signal, and the trader is told.

History. Two endpoints:

* ``GET /api/v1/charts`` (chart-data.md): any exchange, by token, with
  ``candletype``. The page documents one value only, ``1`` for one minute
  candles, so this module asks for one minute candles and builds every other
  interval from them (minute bins aligned to the session start, daily bars
  from each IST date). Candles are ``[timestamp, open, high, low, close,
  volume]``.
* ``POST /api/data/v1/historical`` (getting-started.md, "Historical Data
  NFO"): NFO futures and options by underlying, expiry, strike and type, with
  the interval enum ``1minute`` to ``60minute`` and ``1day``, and open
  interest as a seventh candle column. NFO contracts use it; when it answers
  with an error or with nothing, the charts endpoint is used instead (no OI).

The page's ``/api/data/v1/status/{job_id}`` belongs to the Export API: it
reports a CSV export job and hands back a download link. The call that creates
such a job and the layout of the CSV are not documented, and the historical
endpoint answers with candles directly, so nothing here polls.

Neither page states a per-request range cap. Requests are chunked small (7
days of minute candles, a year of daily ones) and a chunk that fails fails the
whole request rather than leaving a gap.
"""

import math
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from broker.pocketful.api.baseurl import client_id, pocketful_request
from database.token_db import get_token, get_tokens_bulk
from utils.broker_backpressure import BrokerBusyError, cap_server_delay, check_queue_wait
from utils.logging import get_logger

logger = get_logger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))

# OpenAlgo exchange -> (exchange in Pocketful's path, segment). See the module
# docstring for where each pair comes from.
_ROUTES = {
    "NSE": ("NSE", "Capital"),
    "BSE": ("BSE", "Capital"),
    "NSE_INDEX": ("NSE", "Capital"),
    "BSE_INDEX": ("BSE", "Capital"),
    "NFO": ("NFO", "FutOpt"),
    "BFO": ("BFO", "FutOpt"),
    "MCX": ("MCX", "FutOpt"),
    "CDS": ("CDS", "Currency"),
}

# Minutes after midnight IST at which each exchange's session opens, so a
# built 5 minute or hourly bar starts at 09:15 on NSE and at 09:00 on MCX.
_SESSION_OPEN_MINUTES = {"MCX": 0, "CDS": 0}
_DEFAULT_SESSION_OPEN_MINUTES = 15

# --- Pacing -------------------------------------------------------------------
# Module-level: services create a fresh BrokerData per request, so state kept
# on the instance would pace nothing. The slot is booked inside the lock and
# slept outside it.
_MIN_INTERVAL = 0.12  # about 8 a second against the documented 10
_pace_lock = threading.Lock()
_next_slot = 0.0

_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_BACKOFF = 1.0  # seconds, doubled per retry; no Retry-After is documented

_QUOTE_TIMEOUT = 15.0
_HISTORY_TIMEOUT = 30.0

_CHART_CHUNK_DAYS = 7
_HISTORICAL_INTRADAY_CHUNK_DAYS = 7
_HISTORICAL_DAILY_CHUNK_DAYS = 365

_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]

# OpenAlgo interval -> the interval enum of /api/data/v1/historical
# (getting-started.md, "Supported Intervals").
_TIMEFRAMES = {
    "1m": "1minute",
    "3m": "3minute",
    "5m": "5minute",
    "10m": "10minute",
    "15m": "15minute",
    "30m": "30minute",
    "1h": "60minute",
    "D": "1day",
}
_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "1h": 60}

# The candletype chart-data.md documents: "1 for 1-minute candles".
_CHART_ONE_MINUTE = "1"

# An OpenAlgo NFO symbol: NIFTY28MAR24FUT, NIFTY28MAR2420800CE, VEDL25APR24292.5CE.
_FNO_SYMBOL = re.compile(
    r"^(?P<base>.+?)(?P<expiry>\d{2}[A-Z]{3}\d{2})"
    r"(?:(?P<future>FUT)|(?P<strike>\d+(?:\.\d+)?)(?P<kind>CE|PE))$"
)

_SESSION_ENDED = (
    "Your Pocketful session has ended. Log in to Pocketful again from OpenAlgo and retry."
)
_UNREACHABLE = (
    "OpenAlgo could not reach Pocketful for market data. Check this server's internet "
    "connection and try again."
)
_RATE_LIMITED = (
    "Pocketful is refusing more market data requests because its request limit was "
    "reached (10 a second, 5,000 an hour, 10,000 a day). Wait a few minutes and try again."
)


class PocketfulAPIError(Exception):
    """A market data request that could not be answered; ``str()`` is for a trader."""


class PocketfulUnavailableError(PocketfulAPIError):
    """Every request would fail the same way: the session ended or Pocketful is unreachable."""


def _pace():
    """Wait for this request's turn at about 8 data requests a second.

    Raises:
        BrokerBusyError: Under gthread, when the turn is further away than the
            data ceiling of utils.broker_backpressure. Nothing is booked then.
    """
    global _next_slot
    with _pace_lock:
        now = time.monotonic()
        wait = max(0.0, _next_slot - now)
        check_queue_wait(wait, "data")
        _next_slot = now + wait + _MIN_INTERVAL
    if wait > 0:
        time.sleep(wait)


def _data_request(
    method, path, token, params=None, payload=None, timeout=_QUOTE_TIMEOUT, headers=None
):
    """Send one paced data request, retrying a 429 with backoff.

    ``headers`` adds an endpoint's documented extras (the charts endpoint's
    ``clientid``) to the session headers.

    Returns:
        The PocketfulResponse of any answer other than 429.

    Raises:
        BrokerBusyError: Pocketful still answered 429 after the retries, or
            (under gthread) the turn or the backoff would take too long.
        PocketfulUnavailableError: The request could not be sent or answered.
    """
    attempt = 0
    while True:
        _pace()
        try:
            response = pocketful_request(
                method,
                path,
                token,
                params=params,
                payload=payload,
                timeout=timeout,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.exception(f"Pocketful {method} {path} failed in transport")
            raise PocketfulUnavailableError(_UNREACHABLE) from exc
        if response.status_code != 429:
            return response
        delay = None
        if attempt < _RATE_LIMIT_RETRIES:
            delay = cap_server_delay(_RATE_LIMIT_BACKOFF * (2**attempt), "data")
        if delay is None:
            logger.warning(f"Pocketful {method} {path} still rate limited after {attempt} retries")
            raise BrokerBusyError(_RATE_LIMITED)
        attempt += 1
        logger.warning(f"Pocketful {method} {path} rate limited; retry {attempt} in {delay}s")
        time.sleep(delay)


def _refusal(response, what):
    """The error for an answer that carried no usable data, naming what was asked for."""
    logger.warning(
        f"Pocketful refused {what}: HTTP {response.status_code}, message {response.message!r}"
    )
    if response.status_code in (401, 403):
        return PocketfulUnavailableError(_SESSION_ENDED)
    broker_message = response.message.strip().rstrip(".")
    if broker_message:
        return PocketfulAPIError(f"Pocketful did not return {what}: {broker_message}.")
    return PocketfulAPIError(f"Pocketful did not return {what}. Try again in a moment.")


def _route(exchange):
    route = _ROUTES.get(exchange)
    if route is None:
        raise PocketfulAPIError(f"Pocketful market data does not cover the {exchange} exchange.")
    return route


def _not_found(symbol, exchange):
    return PocketfulAPIError(
        f"{symbol} on {exchange} is not in the Pocketful symbol list. Check the symbol, "
        "or download the master contract again."
    )


def _num(value):
    """A finite float from a number or numeric string, else 0.0."""
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _int(value):
    return int(_num(value))


_rupee_book_noted = False


def _book_price(raw, reference):
    """A best bid or ask in rupees.

    The documented answer gives them in paise (see the module docstring), so
    the figure is divided by 100, unless the undivided figure is the nearer of
    the two to ``reference`` (the LTP or another rupee price of the same
    answer). The two readings differ a hundredfold, so only a book more than
    tenfold away from its last trade could be read the wrong way.
    """
    global _rupee_book_noted
    value = _num(raw)
    if value <= 0:
        return 0.0
    in_paise = value / 100
    if reference > 0 and abs(math.log(value / reference)) < abs(math.log(in_paise / reference)):
        if not _rupee_book_noted:
            _rupee_book_noted = True
            logger.info(
                "Pocketful sent bid and ask in rupees, not in paise as its documentation shows"
            )
        return value
    return in_paise


def _quote_from(raw):
    """OpenAlgo's quote from a market data answer (field names: get-market-data.md)."""
    ltp = _num(raw.get("last_trade_price"))
    prev_close = _num(raw.get("close_price"))
    open_price = _num(raw.get("open_price"))
    reference = ltp or prev_close or open_price or _num(raw.get("average_trade_price"))
    return {
        "ask": _book_price(raw.get("ask_price"), reference),
        "bid": _book_price(raw.get("bid_price"), reference),
        "ask_qty": _int(raw.get("ask_qty")),
        "bid_qty": _int(raw.get("bid_qty")),
        "high": _num(raw.get("high_price")),
        "low": _num(raw.get("low_price")),
        "ltp": ltp,
        "open": open_price,
        "prev_close": prev_close,
        "volume": _int(raw.get("trade_volume")),
        # Not on the market data page, whose example is an equity. Pocketful's
        # REST name for open interest is ``current_open_interest`` (greek-data.md);
        # the derivatives answer is undocumented, so it is read when present.
        "oi": _int(raw.get("current_open_interest")),
    }


def _depth_from(raw):
    """OpenAlgo's five level depth: REST carries the best bid and ask only."""
    quote = _quote_from(raw)
    bids = [{"price": quote["bid"], "quantity": quote["bid_qty"]}]
    asks = [{"price": quote["ask"], "quantity": quote["ask_qty"]}]
    while len(bids) < 5:
        bids.append({"price": 0.0, "quantity": 0})
    while len(asks) < 5:
        asks.append({"price": 0.0, "quantity": 0})
    return {
        "asks": asks,
        "bids": bids,
        "high": quote["high"],
        "low": quote["low"],
        "ltp": quote["ltp"],
        "ltq": _int(raw.get("last_trade_qty")),
        "oi": quote["oi"],
        "open": quote["open"],
        "prev_close": quote["prev_close"],
        "totalbuyqty": _int(raw.get("total_buy_qty")),
        "totalsellqty": _int(raw.get("total_sell_qty")),
        "volume": quote["volume"],
    }


# --- History helpers ------------------------------------------------------------


def _chunks(start, end, days):
    """Contiguous (first, last) date pairs covering start..end, ``days`` long at most."""
    current = start
    while current <= end:
        last = min(current + timedelta(days=days - 1), end)
        yield current, last
        current = last + timedelta(days=1)


def _ist_today():
    return datetime.now(_IST).date()


def _empty_history():
    return pd.DataFrame(columns=_COLUMNS)


def _candle_frame(rows):
    """A frame of IST-aware candles from Pocketful's candle arrays.

    Rows are ``[timestamp, open, high, low, close, volume]`` (charts) or carry
    open interest as a seventh member (historical); missing OI is 0.
    """
    records = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            logger.warning(f"Skipping a Pocketful candle that is not a candle: {row!r}")
            continue
        records.append(list(row[:6]) + [row[6] if len(row) > 6 else 0])
    frame = pd.DataFrame(records, columns=_COLUMNS)
    if frame.empty:
        return frame
    try:
        stamps = pd.to_datetime(frame["timestamp"], format="ISO8601", errors="coerce")
    except ValueError:  # offsets that differ between candles
        stamps = pd.to_datetime(frame["timestamp"], format="ISO8601", errors="coerce", utc=True)
    # The documented candles carry +0530; one without an offset is IST.
    stamps = stamps.dt.tz_localize(_IST) if stamps.dt.tz is None else stamps.dt.tz_convert(_IST)
    frame["timestamp"] = stamps
    frame = frame.dropna(subset=["timestamp"])
    for column in _COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    return frame


def _within(frame, start, end):
    if frame.empty:
        return frame
    days = frame["timestamp"].dt.date
    frame = frame[(days >= start) & (days <= end)]
    return frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")


def _epoch_seconds(stamps):
    return (stamps - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)


def _finish(frame, timeframe, exchange, build_bars):
    """OpenAlgo's history frame: epoch seconds, IST bar times, daily bars at IST midnight.

    Args:
        frame: IST-aware candles inside the requested dates.
        timeframe: OpenAlgo interval.
        exchange: OpenAlgo exchange, for the session open of built bars.
        build_bars: True when ``frame`` holds one minute candles to build
            ``timeframe`` from; False when it already holds ``timeframe`` bars.
    """
    if frame.empty:
        return _empty_history()
    aggregate = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "oi": "last",
    }
    if timeframe == "D":
        # Daily bars carry the IST date at 00:00 UTC, as zerodha's shifted bars do.
        bars = frame.groupby(frame["timestamp"].dt.date, sort=True).agg(aggregate)
        dates = pd.to_datetime(pd.Series(bars.index, dtype="object"))
        stamps = (dates - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
        bars = bars.reset_index(drop=True)
    else:
        minutes = _MINUTES[timeframe]
        if build_bars and minutes > 1:
            offset = _SESSION_OPEN_MINUTES.get(exchange, _DEFAULT_SESSION_OPEN_MINUTES)
            bars = (
                frame.set_index("timestamp")
                .resample(
                    f"{minutes}min",
                    origin="start_day",
                    offset=pd.Timedelta(minutes=offset),
                    closed="left",
                    label="left",
                )
                .agg(aggregate)
                .dropna(subset=["open"])
                .reset_index()
            )
        else:
            bars = frame.reset_index(drop=True)
        stamps = _epoch_seconds(bars["timestamp"])
        bars = bars.drop(columns=["timestamp"])
    out = pd.DataFrame({"timestamp": stamps.to_numpy().astype("int64")})
    for column in ("open", "high", "low", "close"):
        out[column] = bars[column].to_numpy().astype(float)
    out["volume"] = bars["volume"].to_numpy().astype("int64")
    out["oi"] = bars["oi"].to_numpy().astype("int64")
    return out


def _fno_contract(symbol):
    """The /api/data/v1/historical body fields for an OpenAlgo NFO symbol, or None.

    Field names and values from getting-started.md: ``symbol`` (the underlying,
    "NIFTY"), ``product_type`` ("futures" or "options"), ``expiry_date``
    (YYYY-MM-DD), and for options ``type`` ("CE" or "PE") and ``strike_price``.
    """
    match = _FNO_SYMBOL.match(symbol or "")
    if not match:
        return None
    try:
        expiry = datetime.strptime(match["expiry"], "%d%b%y").date()
    except ValueError:
        return None
    body = {"symbol": match["base"], "expiry_date": expiry.isoformat()}
    if match["future"]:
        body["product_type"] = "futures"
        return body
    strike = float(match["strike"])
    body["product_type"] = "options"
    body["type"] = match["kind"]
    body["strike_price"] = int(strike) if strike.is_integer() else strike
    return body


def _history_dates(from_date, to_date):
    try:
        start = pd.Timestamp(from_date).date()
        end = pd.Timestamp(to_date).date()
    except (TypeError, ValueError) as exc:
        raise PocketfulAPIError("The start and end dates must be in YYYY-MM-DD form.") from exc
    return start, end


class _HistoricalUnavailable(Exception):
    """The NFO historical endpoint gave no candles; the charts endpoint is tried instead."""


class BrokerData:
    """Pocketful market data for OpenAlgo's quotes, depth, multiquotes, LTP and history."""

    def __init__(self, auth_token):
        self.auth_token = auth_token
        # OpenAlgo interval -> the documented /api/data/v1/historical interval.
        # On the charts endpoint every interval is built from one minute candles.
        self.timeframe_map = dict(_TIMEFRAMES)

    # --- Quotes and depth --------------------------------------------------

    def _market_data(self, symbol, exchange, token=None):
        """The market data answer (the ``data`` object) for one symbol."""
        pf_exchange, segment = _route(exchange)
        token = token or get_token(symbol, exchange)
        if not token:
            raise _not_found(symbol, exchange)
        response = _data_request(
            "GET",
            f"/api/v1/marketdata/{pf_exchange}/{segment}",
            self.auth_token,
            params={"token": str(token)},
        )
        payload = response.payload
        if not response.ok or not isinstance(payload, dict) or not payload:
            raise _refusal(response, f"a quote for {symbol} on {exchange}")
        return payload

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Quote for one symbol: ask, bid, ask_qty, bid_qty, high, low, ltp, open,
        prev_close, volume, oi.

        Raises:
            PocketfulAPIError: No quote; the message is for a trader.
            BrokerBusyError: Pacing refused it, or Pocketful's rate limit held.
        """
        return _quote_from(self._market_data(symbol, exchange))

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Five level depth. REST carries the best bid and ask only, so levels
        two to five are zeros; the totals, OHLC, LTP and LTQ are the broker's.
        """
        return _depth_from(self._market_data(symbol, exchange))

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """Alias of get_depth, the name this module used before."""
        return self.get_depth(symbol, exchange)

    def get_ltp(self, symbol: str, exchange: str) -> float:
        """Last traded price from one request; 0.0 when no price is available.

        Never raises: a symbol not in the master contract, an exchange Pocketful
        does not quote, a refusal, a transport failure or a refused turn all
        log their cause and return 0.0.
        """
        try:
            pf_exchange, segment = _route(exchange)
            token = get_token(symbol, exchange)
            if not token:
                logger.warning(f"No Pocketful token for {exchange}:{symbol}; no LTP")
                return 0.0
            response = _data_request(
                "GET",
                f"/api/v1/marketdata/{pf_exchange}/{segment}",
                self.auth_token,
                params={"token": str(token), "key": "last_trade_price"},
            )
            if not response.ok:
                logger.warning(
                    f"Pocketful gave no LTP for {exchange}:{symbol}: HTTP "
                    f"{response.status_code}, message {response.message!r}"
                )
                return 0.0
            price = _num(response.payload)
            return price if price > 0 else 0.0
        except Exception:
            logger.exception(f"Could not read the Pocketful LTP of {exchange}:{symbol}")
            return 0.0

    def get_multiquotes(self, symbols: list) -> list:
        """Quotes for several symbols, one paced request each, in the order given.

        Args:
            symbols: ``[{"symbol": "SBIN", "exchange": "NSE"}, ...]``

        Returns:
            ``[{"symbol", "exchange", "data": quote}]``, or ``"error"`` in place
            of ``"data"`` for a symbol that could not be quoted.

        Raises:
            PocketfulUnavailableError: The session ended or Pocketful could not
                be reached; the symbols after it would fail the same way.
            BrokerBusyError: Pacing refused a request, or Pocketful's rate limit
                held; the rest would be refused too.
        """
        pairs = [(item["symbol"], item["exchange"]) for item in symbols]
        tokens = get_tokens_bulk(pairs) if pairs else []
        results = []
        for (symbol, exchange), token in zip(pairs, tokens, strict=True):
            try:
                quote = _quote_from(self._market_data(symbol, exchange, token=token))
                results.append({"symbol": symbol, "exchange": exchange, "data": quote})
            except PocketfulUnavailableError:
                raise
            except PocketfulAPIError as exc:
                results.append({"symbol": symbol, "exchange": exchange, "error": str(exc)})
        return results

    # --- History -------------------------------------------------------------

    def get_intervals(self) -> list:
        """The OpenAlgo intervals get_history serves."""
        return list(self.timeframe_map.keys())

    def get_history(
        self, symbol: str, exchange: str, timeframe: str, from_date, to_date
    ) -> pd.DataFrame:
        """Candles as a DataFrame of timestamp, open, high, low, close, volume, oi.

        ``timestamp`` is epoch seconds: the true UTC instant of an intraday bar's
        IST start, and for a daily bar the IST date at 00:00 UTC. Both dates are
        inclusive. NFO contracts come from /api/data/v1/historical with open
        interest, everything else (and an NFO contract that endpoint does not
        answer) from one minute chart candles.

        Raises:
            PocketfulAPIError: Unknown interval, symbol or exchange, or a chunk
                Pocketful refused; never a partial series.
            BrokerBusyError: Pacing refused a request, or Pocketful's rate limit held.
        """
        if timeframe not in self.timeframe_map:
            raise PocketfulAPIError(
                f"Pocketful history does not offer the {timeframe} interval. Choose one of "
                f"{', '.join(self.timeframe_map)}."
            )
        start, end = _history_dates(from_date, to_date)
        pf_exchange, _segment = _route(exchange)
        token = get_token(symbol, exchange)
        if not token:
            raise _not_found(symbol, exchange)
        if end < start:
            return _empty_history()

        contract = _fno_contract(symbol) if exchange == "NFO" else None
        if contract is not None:
            try:
                bars = self._historical_bars(contract, self.timeframe_map[timeframe], start, end)
                if timeframe == "D":
                    bars = self._with_todays_bar(bars, symbol, exchange, token, start, end)
                return _finish(bars, timeframe, exchange, build_bars=False)
            except _HistoricalUnavailable as exc:
                logger.warning(
                    f"Pocketful historical data gave nothing for {exchange}:{symbol} ({exc}); "
                    "using chart candles, without open interest"
                )

        minutes = self._chart_minutes(symbol, exchange, pf_exchange, token, start, end)
        return _finish(minutes, timeframe, exchange, build_bars=True)

    def _chart_minutes(self, symbol, exchange, pf_exchange, token, start, end):
        """One minute candles from /api/v1/charts for start..end, chunked."""
        rows = []
        for first, last in _chunks(start, end, _CHART_CHUNK_DAYS):
            response = _data_request(
                "GET",
                "/api/v1/charts",
                self.auth_token,
                params={
                    "exchange": pf_exchange,
                    "token": str(token),
                    "candletype": _CHART_ONE_MINUTE,
                    "from_date": f"{first.isoformat()}T00:00:00",
                    "to_date": f"{last.isoformat()}T23:59:59",
                },
                timeout=_HISTORY_TIMEOUT,
                # chart-data.md lists a clientid header beside the session's own.
                headers={"clientid": client_id(self.auth_token) or ""},
            )
            payload = response.payload
            candles = payload.get("candles") if isinstance(payload, dict) else None
            if not response.ok or not isinstance(candles, (list, type(None))):
                raise _refusal(
                    response, f"history for {symbol} on {exchange} from {first} to {last}"
                )
            rows.extend(candles or [])
        return _within(_candle_frame(rows), start, end)

    def _historical_bars(self, contract, interval, start, end):
        """NFO bars from /api/data/v1/historical for start..end, chunked.

        Raises:
            _HistoricalUnavailable: An error answer, or no candles at all.
            PocketfulUnavailableError: The session ended or Pocketful is unreachable.
        """
        days = (
            _HISTORICAL_DAILY_CHUNK_DAYS if interval == "1day" else _HISTORICAL_INTRADAY_CHUNK_DAYS
        )
        rows = []
        for first, last in _chunks(start, end, days):
            body = dict(contract)
            body.update(
                {
                    "interval": interval,
                    "from_date": f"{first.isoformat()}T00:00:00",
                    "to_date": f"{last.isoformat()}T23:59:59",
                }
            )
            response = _data_request(
                "POST",
                "/api/data/v1/historical",
                self.auth_token,
                payload=body,
                timeout=_HISTORY_TIMEOUT,
            )
            if response.status_code in (401, 403):
                raise _refusal(response, "historical data")
            payload = response.payload
            candles = payload.get("candles") if isinstance(payload, dict) else None
            if not response.ok or not isinstance(candles, (list, type(None))):
                raise _HistoricalUnavailable(
                    f"HTTP {response.status_code}, message {response.message!r}"
                )
            rows.extend(candles or [])
        bars = _within(_candle_frame(rows), start, end)
        if bars.empty:
            raise _HistoricalUnavailable("no candles in the range")
        return bars

    def _with_todays_bar(self, bars, symbol, exchange, token, start, end):
        """Add today's daily bar from a quote when the daily series stops before today.

        Only when today is in the range, and only from an answer whose last
        trade (``last_trade_time``, epoch seconds) is today: on a holiday the
        quote still shows the last session, which is already a bar.
        """
        today = _ist_today()
        if not start <= today <= end:
            return bars
        if not bars.empty and bars["timestamp"].max().date() >= today:
            return bars
        try:
            raw = self._market_data(symbol, exchange, token=token)
        except PocketfulUnavailableError:
            raise
        except PocketfulAPIError:
            logger.warning(
                f"No quote for today's {exchange}:{symbol} daily bar; series ends earlier"
            )
            return bars
        traded = _num(raw.get("last_trade_time"))
        quote = _quote_from(raw)
        if not traded or quote["open"] <= 0:
            return bars
        if datetime.fromtimestamp(traded, _IST).date() != today:
            return bars
        today_bar = pd.DataFrame(
            [
                {
                    "timestamp": pd.Timestamp(
                        datetime(today.year, today.month, today.day, tzinfo=_IST)
                    ),
                    "open": quote["open"],
                    "high": quote["high"],
                    "low": quote["low"],
                    "close": quote["ltp"],
                    "volume": quote["volume"],
                    "oi": quote["oi"],
                }
            ]
        )
        return pd.concat([bars, today_bar], ignore_index=True) if not bars.empty else today_bar
