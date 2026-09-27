"""
Price-matrix loader for the portfolio backtester.

Turns a list of symbols into one calendar-aligned close-price DataFrame, which
is the only input the engine needs. Everything downstream (returns, weights,
rebalancing, metrics) is a transformation of that matrix, so the correctness of
a backtest is mostly decided here.

Two sources, chosen by the caller rather than guessed:

- ``db``  -- the local DuckDB/Historify store, read in **one query for all
  symbols**. Deterministic, rate-limit free, and what a long multi-symbol
  backtest should use.
- ``api`` -- the broker's history API, through
  ``services.history_service.get_history``. Always current, but rate limited
  and broker dependent; a 20-symbol 5-year run is 20 sequential calls.

The ``db`` path deliberately bypasses the history service. That service is
per-symbol and materialises every bar as a dict before pandas rebuilds a frame
from it -- for ten symbols over ten years that is 25,000 dicts and 265ms,
against 17ms for the single query here. A backtest reads far more history at
once than a chart does, so the shape that suits a chart is the wrong one here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from threading import Lock

import numpy as np
import pandas as pd

from services.history_service import get_history
from utils.logging import get_logger

logger = get_logger(__name__)

# Equity and ETF cash markets only. Derivatives have expiries and rolls, which
# a weight-based buy-and-hold portfolio has no meaning for; currency and
# commodity carry their own settlement conventions. Widening this set means
# answering those questions first, so it is an explicit allow-list.
SUPPORTED_EXCHANGES = ("NSE", "BSE")

# A small cache of loaded matrices.
#
# Every interesting question asks the same history repeatedly: comparing four
# rebalancing schedules is four runs over identical prices, walk-forward is
# dozens, and a strategy comparison more still. Re-reading the store each time
# is pure waste -- the bars cannot have changed within one request.
#
# Bounded and LRU because a matrix is real memory (10 symbols x 10 years is
# roughly 200KB, but 50 x 20 years is not), and keyed on everything that
# changes the answer, so no query can collide with a different one.
_CACHE_MAX = 16
_cache: OrderedDict[tuple, PriceMatrix] = OrderedDict()
_cache_lock = Lock()


def clear_price_cache() -> None:
    """Drop every cached matrix. Call after ingesting new history."""
    with _cache_lock:
        _cache.clear()

# Benchmarks are indices, which live on their own exchanges and cannot be
# held. They are allowed as the comparison series only -- never as a holding,
# since you cannot buy an index, only a fund tracking it. GLOBAL_INDEX is
# quote-only and Zerodha-only, but still fair game as a comparison series.
BENCHMARK_EXCHANGES = ("NSE_INDEX", "BSE_INDEX", "GLOBAL_INDEX")


class DataError(Exception):
    """Base for anything that makes a backtest unsafe to run."""


class UnsupportedExchange(DataError):
    """A symbol was requested on an exchange the backtester does not model."""


class MissingHistory(DataError):
    """
    A symbol has no usable history for the requested window.

    Raised rather than silently dropping the symbol or forward-filling from
    nothing: a portfolio quietly backtested on 4 of its 5 holdings reports a
    return that was never achievable, and nothing in the output would show it.
    """


@dataclass(frozen=True)
class PriceMatrix:
    """
    Calendar-aligned closes for a set of symbols.

    ``closes`` is indexed by date, one column per symbol, sorted ascending with
    no duplicate dates. ``source`` records where the bars came from so a result
    can say which data produced it.
    """

    closes: pd.DataFrame
    source: str
    start: date
    end: date
    #: symbol -> [(date, return)] for moves large enough to look like an
    #: unadjusted corporate action. Empty for well-adjusted data, which is the
    #: normal case; non-empty means treat the run's numbers with suspicion.
    warnings: dict = field(default_factory=dict)

    @property
    def symbols(self) -> list[str]:
        return list(self.closes.columns)

    @property
    def sessions(self) -> int:
        return len(self.closes.index)

    def returns(self) -> pd.DataFrame:
        """
        Simple daily returns.

        The first row is dropped rather than zero-filled: there is no return on
        the first observation, and a leading 0 would understate volatility and
        flatter every risk metric computed from it.
        """
        return self.closes.pct_change().iloc[1:]


def split_artifacts(
    closes: pd.DataFrame, threshold: float = 0.35
) -> dict[str, list[tuple[str, float]]]:
    """
    Sessions where a price moved so far it is more likely a data artifact than
    a market move — an unadjusted split, bonus or consolidation.

    Broker feeds are normally already adjusted, so this does not adjust
    anything; it reports. The case it catches is a series stored *before* a
    corporate action and not re-ingested after, which leaves a step in the
    history that no amount of downstream maths can distinguish from a real
    -50% day. Silently backtesting through one produces a confident, wrong
    answer, so the run should say so.

    ``threshold`` is an absolute daily return. It has to sit *below* the
    smallest common split ratio, not at it: a 1:2 split is exactly -50%, so a
    0.5 threshold misses the very case it exists for. 0.35 clears the 20%
    circuit that caps a real NSE/BSE session with room to spare, while still
    catching 1:2.
    """
    out: dict[str, list[tuple[str, float]]] = {}
    moves = closes.pct_change()
    for symbol in closes.columns:
        hits = moves[symbol][moves[symbol].abs() > threshold]
        if not hits.empty:
            out[symbol] = [
                (stamp.date().isoformat(), float(value))
                for stamp, value in hits.items()
            ]
    return out


def _closes_from_duckdb(
    symbols: list[str],
    exchanges: list[str],
    start_date: str,
    end_date: str,
    interval: str,
) -> dict[str, pd.Series]:
    """
    Read every symbol's closes in one query.

    Timestamps are stored as epoch seconds, so the conversion happens in SQL
    and the result arrives as a frame pandas can pivot directly -- no
    per-bar Python objects in between, which is where the service path spends
    its time.
    """
    from database.historify_db import get_connection

    pairs = list(dict.fromkeys(zip(symbols, exchanges, strict=True)))
    where = " or ".join("(symbol = ? and exchange = ?)" for _ in pairs)
    params: list[object] = [interval, start_date, end_date]
    for symbol, exchange in pairs:
        params.extend([symbol, exchange])

    sql = f"""
        select symbol,
               to_timestamp(timestamp)::date as session,
               close
        from market_data
        where interval = ?
          and to_timestamp(timestamp)::date >= ?::date
          and to_timestamp(timestamp)::date <= ?::date
          and ({where})
        order by symbol, timestamp
    """

    with get_connection() as conn:
        frame = conn.execute(sql, params).df()

    if frame.empty:
        raise MissingHistory(
            f"Historify holds no {interval} bars for "
            f"{', '.join(sorted({s for s, _ in pairs}))} between "
            f"{start_date} and {end_date}"
        )

    out: dict[str, pd.Series] = {}
    for symbol in symbols:
        rows = frame[frame["symbol"] == symbol]
        if rows.empty:
            raise MissingHistory(
                f"{symbol}: no {interval} history in Historify for "
                f"{start_date}..{end_date}. Ingest it, or run with the broker "
                f"API as the source."
            )
        series = pd.Series(
            pd.to_numeric(rows["close"], errors="coerce").to_numpy(),
            index=pd.DatetimeIndex(pd.to_datetime(rows["session"])).normalize(),
            name=symbol,
        ).dropna()
        # A re-ingested session would otherwise duplicate; last write wins,
        # matching the API path.
        out[symbol] = series[~series.index.duplicated(keep="last")].sort_index()
    return out


def _normalise_exchange(exchange: str, allowed: tuple[str, ...] = SUPPORTED_EXCHANGES) -> str:
    ex = (exchange or "").strip().upper()
    if ex not in allowed:
        raise UnsupportedExchange(
            f"{ex or '(blank)'} is not supported here; expected "
            f"{' or '.join(allowed)}"
        )
    return ex


def _frame_from_payload(payload: object, symbol: str) -> pd.DataFrame:
    """
    Coerce one history response into a [timestamp, close] frame.

    The service returns either a list of bar dicts or a dict wrapping one under
    ``data``; brokers also disagree on whether numerics arrive as numbers or
    strings, so values are coerced rather than trusted.
    """
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("bars", []))
    if not isinstance(rows, list) or not rows:
        raise MissingHistory(f"{symbol}: history response contained no bars")

    frame = pd.DataFrame(rows)
    time_col = next(
        (c for c in ("timestamp", "time", "date", "datetime") if c in frame.columns),
        None,
    )
    if time_col is None or "close" not in frame.columns:
        raise MissingHistory(
            f"{symbol}: history rows lack a timestamp or close column "
            f"(got {sorted(frame.columns)})"
        )

    stamps = frame[time_col]
    # Epoch seconds vs an ISO string: decide on dtype, not on a guess, because
    # a misread epoch silently lands every bar in 1970.
    if pd.api.types.is_numeric_dtype(stamps):
        index = pd.to_datetime(stamps, unit="s", utc=True).dt.tz_localize(None)
    else:
        index = pd.to_datetime(stamps, errors="coerce")

    # `.to_numpy()`, not the Series: a Series carries its own 0..n index, and
    # pandas would align it against the DatetimeIndex and produce all-NaN.
    out = pd.DataFrame(
        {"close": pd.to_numeric(frame["close"], errors="coerce").to_numpy()},
        index=pd.DatetimeIndex(index).normalize(),
    )
    out = out[out["close"].notna() & out.index.notna()]
    if out.empty:
        raise MissingHistory(f"{symbol}: no rows survived timestamp/close parsing")
    # A duplicated session (a re-ingested day) would otherwise make the join
    # explode combinatorially; the last write wins.
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_prices(
    symbols: list[str],
    exchanges: list[str] | str,
    start_date: str,
    end_date: str,
    *,
    source: str = "db",
    interval: str = "D",
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
    min_sessions: int = 2,
    allowed_exchanges: tuple[str, ...] = SUPPORTED_EXCHANGES,
) -> PriceMatrix:
    """
    Load closes for ``symbols`` into one aligned matrix.

    ``exchanges`` is either one exchange for all symbols or one per symbol.
    ``source`` is ``'db'`` (Historify/DuckDB) or ``'api'`` (broker) and is the
    caller's choice, never inferred -- the two answer differently and a result
    has to be able to say which it used.

    Raises ``MissingHistory`` if any symbol is empty for the window, and
    ``UnsupportedExchange`` for anything outside NSE/BSE.
    """
    if not symbols:
        raise DataError("no symbols requested")
    if source not in ("db", "api"):
        raise DataError(f"source must be 'db' or 'api', got {source!r}")

    if isinstance(exchanges, str):
        exchanges = [exchanges] * len(symbols)
    if len(exchanges) != len(symbols):
        raise DataError(
            f"{len(symbols)} symbols but {len(exchanges)} exchanges; pass one "
            "exchange or one per symbol"
        )

    checked = [_normalise_exchange(ex, allowed_exchanges) for ex in exchanges]

    key = (
        tuple(symbols), tuple(checked), start_date, end_date, source, interval,
        min_sessions,
    )
    if source == "db":
        with _cache_lock:
            hit = _cache.get(key)
            if hit is not None:
                _cache.move_to_end(key)
                logger.debug("portfolio.data: cache hit for %s", ",".join(symbols))
                return hit

        # One query, all symbols. See the module docstring for why this does
        # not go through the history service.
        series = _closes_from_duckdb(symbols, checked, start_date, end_date, interval)
        for symbol in symbols:
            logger.debug(
                "portfolio.data: %s bars for %s from duckdb", len(series[symbol]), symbol
            )
        return _remember(key, _assemble(series, symbols, start_date, end_date, source, min_sessions))

    series = {}
    for symbol, ex in zip(symbols, checked, strict=True):
        ok, payload, status = get_history(
            symbol=symbol,
            exchange=ex,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            auth_token=auth_token,
            feed_token=feed_token,
            broker=broker,
            source=source,
        )
        if not ok:
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message", ""))
            raise MissingHistory(
                f"{symbol} ({ex}): history request failed [{status}] {message}".strip()
            )
        frame = _frame_from_payload(payload, symbol)
        if symbol in series:
            raise DataError(f"{symbol} requested more than once")
        series[symbol] = frame["close"]
        logger.info(
            "portfolio.data: loaded %s bars for %s (%s) from %s",
            len(frame), symbol, ex, source,
        )

    return _assemble(series, symbols, start_date, end_date, source, min_sessions)


def _remember(key: tuple, matrix: PriceMatrix) -> PriceMatrix:
    """Store under the LRU cap, evicting the least recently used."""
    with _cache_lock:
        _cache[key] = matrix
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return matrix


def _assemble(
    series: dict[str, pd.Series],
    symbols: list[str],
    start_date: str,
    end_date: str,
    source: str,
    min_sessions: int,
) -> PriceMatrix:
    """Align the per-symbol closes into one matrix, whichever source built them."""
    # Inner join: a portfolio return needs every holding priced on the same
    # session. An outer join plus forward-fill would invent prices on days a
    # symbol did not trade and understate the portfolio's true volatility.
    closes = pd.concat(series, axis=1, join="inner").sort_index()
    closes.columns = list(series.keys())

    values = closes.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise DataError("price matrix must contain only positive finite closes")

    if len(closes.index) < min_sessions:
        overlap = closes.index
        raise MissingHistory(
            f"only {len(overlap)} session(s) are common to all "
            f"{len(symbols)} symbols between {start_date} and {end_date}; "
            "a shorter window or a symbol with a later listing date is likely"
        )

    artifacts = split_artifacts(closes)
    if artifacts:
        logger.warning(
            "portfolio.data: %d symbol(s) show moves consistent with an "
            "unadjusted corporate action: %s",
            len(artifacts), ", ".join(artifacts),
        )

    return PriceMatrix(
        closes=closes,
        source=source,
        start=closes.index[0].date(),
        end=closes.index[-1].date(),
        warnings=artifacts,
    )
