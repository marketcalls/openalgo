"""Sector rotation (relative rotation map) service.

Places every NSE sector index on a four-quadrant map against a benchmark:
RS-Ratio on the horizontal axis (is the sector stronger than the benchmark?)
and RS-Momentum on the vertical axis (is that strength still building?). Both
are centred on 100.

Follows the standard service contract in ``docs/prompt/services_documentation.md``:
every entry point returns ``(success, response, status_code)``.

The calculation is the one in the standalone sector-rotation-map project, run
unchanged on daily bars or on weekly bars resampled from them:

    RS           = 100 * close_sector / close_benchmark
    RS smoothed  = EMA(RS, 10)
    RS-Ratio     = 100 + 2 * zscore(RS smoothed, 52 bars)
    RS-Momentum  = 100 + 2 * zscore(EMA(change in RS-Ratio, 5), 52 bars)

Prices come from ``portfolio.data.load_prices``, which already serves both
sources (Historify with ``source='db'``, the broker history API with
``source='api'``). It is called once per symbol rather than once for the whole
set, for two reasons that are specific to a sector map:

* ``load_prices`` refuses the whole request when one symbol is missing. Not
  every broker publishes every sector index, and one absent index must cost
  that dot, not the map.
* It inner-joins every column. A newer index (Nifty India Defence) would then
  shorten every other sector's history to its own.

So the benchmark is loaded once, and each sector is aligned with it on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from portfolio.data import DataError, load_prices
from utils.logging import get_logger
from utils.thread_safe_cache import LockedTTLCache

logger = get_logger(__name__)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    exchange: str
    label: str


# NSE sector indices in OpenAlgo symbol format (docs/prompt/symbol-format.md).
# Financial Services is the Nifty Financial Services index, which OpenAlgo
# names FINNIFTY.
SECTORS: tuple[Instrument, ...] = (
    Instrument("NIFTYAUTO", "NSE_INDEX", "Auto"),
    Instrument("NIFTYCOMMODITIES", "NSE_INDEX", "Commodities"),
    Instrument("NIFTYCONSRDURBL", "NSE_INDEX", "Consumer Durables"),
    Instrument("NIFTYENERGY", "NSE_INDEX", "Energy"),
    Instrument("FINNIFTY", "NSE_INDEX", "Financial Services"),
    Instrument("NIFTYFMCG", "NSE_INDEX", "FMCG"),
    Instrument("NIFTYHEALTHCARE", "NSE_INDEX", "Healthcare"),
    Instrument("NIFTYINDDEFENCE", "NSE_INDEX", "India Defence"),
    Instrument("NIFTYINFRA", "NSE_INDEX", "Infra"),
    Instrument("NIFTYIT", "NSE_INDEX", "IT"),
    Instrument("NIFTYMEDIA", "NSE_INDEX", "Media"),
    Instrument("NIFTYMETAL", "NSE_INDEX", "Metal"),
    Instrument("NIFTYOILANDGAS", "NSE_INDEX", "Oil & Gas"),
    Instrument("NIFTYPHARMA", "NSE_INDEX", "Pharma"),
    Instrument("NIFTYPVTBANK", "NSE_INDEX", "Private Bank"),
    Instrument("NIFTYPSE", "NSE_INDEX", "PSE"),
    Instrument("NIFTYPSUBANK", "NSE_INDEX", "PSU Bank"),
    Instrument("NIFTYREALTY", "NSE_INDEX", "Realty"),
)

BENCHMARKS: tuple[Instrument, ...] = (
    Instrument("NIFTY", "NSE_INDEX", "Nifty 50"),
    Instrument("NIFTY500", "NSE_INDEX", "Nifty 500"),
    Instrument("BANKNIFTY", "NSE_INDEX", "Bank Nifty"),
    Instrument("SENSEX", "BSE_INDEX", "Sensex"),
    Instrument("NIFTYNXT50", "NSE_INDEX", "Nifty Next 50"),
    Instrument("MIDCPNIFTY", "NSE_INDEX", "Midcap Nifty"),
    Instrument("FINNIFTY", "NSE_INDEX", "Fin Nifty"),
)

TIMEFRAMES = ("daily", "weekly")
SOURCES = ("db", "api")

# Cash and index exchanges (docs/prompt/order-constants.md). Derivatives are
# left out: a contract expires and rolls, so its closes are not one series a
# relative-strength trend can be read from.
EXCHANGES = ("NSE", "BSE", "NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX")

# Each symbol is one history request on the broker source, so a map is
# bounded rather than open-ended.
MAX_INSTRUMENTS = 40

# Calculation parameters, in bars of the selected timeframe.
RS_EMA_SPAN = 10
MOMENTUM_EMA_SPAN = 5
ZSCORE_WINDOW = 52
ZSCORE_MIN_BARS = 20
ZSCORE_SCALE = 2.0

# The longest trail the map can draw. The response carries this many points per
# sector and the page trims to the slider, so moving the slider is not a
# round trip.
MAX_TAIL = 30

# Calendar days of history to read. The z-score needs 52 bars plus the warm-up
# of both EMAs before its first value is meaningful, and the trail then needs
# MAX_TAIL more on top.
LOOKBACK_DAYS = {"daily": 548, "weekly": 1095}

# Broker history is rate limited and a default map is nineteen requests, so
# each symbol's closes are reused for a few minutes.
_CLOSES_CACHE = LockedTTLCache(maxsize=256, ttl=300)

_BENCHMARKS_BY_SYMBOL = {b.symbol: b for b in BENCHMARKS}
_SECTORS_BY_KEY = {(s.symbol, s.exchange): s for s in SECTORS}


def _error(message: str, status: int = 400) -> tuple[bool, dict[str, Any], int]:
    return False, {"status": "error", "message": message}, status


def list_options() -> tuple[bool, dict[str, Any], int]:
    """Benchmarks, timeframes and sectors, for populating the page controls."""
    return (
        True,
        {
            "status": "success",
            "data": {
                "benchmarks": [
                    {"symbol": b.symbol, "exchange": b.exchange, "label": b.label}
                    for b in BENCHMARKS
                ],
                "timeframes": list(TIMEFRAMES),
                "exchanges": list(EXCHANGES),
                "max_instruments": MAX_INSTRUMENTS,
                "sectors": [
                    {"symbol": s.symbol, "exchange": s.exchange, "label": s.label} for s in SECTORS
                ],
                "max_tail": MAX_TAIL,
            },
        },
        200,
    )


def to_weekly(closes: pd.Series) -> pd.Series:
    """Resample daily closes to one close per week, ending Friday.

    Each week is stamped with the last session that actually traded rather than
    with the Friday itself, so a week still in progress is not dated in the
    future and a week that ended on a Thursday holiday shows the Thursday.
    """
    if closes.empty:
        return closes
    weekly_close = closes.resample("W-FRI").last()
    weekly_date = closes.index.to_series().resample("W-FRI").last()
    keep = weekly_close.notna() & weekly_date.notna()
    return pd.Series(
        weekly_close[keep].to_numpy(),
        index=pd.DatetimeIndex(weekly_date[keep].to_numpy()),
        name=closes.name,
    )


def paired_bars(
    closes: pd.Series, benchmark: pd.Series, timeframe: str
) -> tuple[pd.Series, pd.Series]:
    """The symbol's and the benchmark's bars on a shared calendar.

    Daily sessions are aligned before any weekly resampling. Resampling each
    side on its own would stamp a week with that side's own last session, so a
    week that ended on a holiday for only one of them (a BSE-only holiday, a
    global index, a day missing from Historify) would match nothing and drop
    out of both the smoothing and the z-score.
    """
    pair = pd.concat({"symbol": closes, "benchmark": benchmark}, axis=1, join="inner").dropna()
    symbol, bench = pair["symbol"], pair["benchmark"]
    if timeframe == "weekly":
        return to_weekly(symbol), to_weekly(bench)
    return symbol, bench


def _zscore(series: pd.Series) -> pd.Series:
    mean = series.rolling(window=ZSCORE_WINDOW, min_periods=ZSCORE_MIN_BARS).mean()
    std = series.rolling(window=ZSCORE_WINDOW, min_periods=ZSCORE_MIN_BARS).std()
    # A flat stretch has no spread to scale by; NaN drops the bar rather than
    # dividing by zero into an infinite reading.
    std = std.replace(0, np.nan)
    return 100 + ((series - mean) / std) * ZSCORE_SCALE


def rrg_series(sector: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """RS-Ratio and RS-Momentum for every bar where both are defined.

    Both inputs are closes indexed by date. Only sessions both traded are used:
    a ratio against a forward-filled close would invent relative strength on a
    day one side did not trade.
    """
    pair = pd.concat({"sector": sector, "benchmark": benchmark}, axis=1, join="inner")
    pair = pair.dropna().sort_index()
    if pair.empty:
        return pd.DataFrame(columns=["rs_ratio", "rs_momentum"])

    raw_rs = (pair["sector"] / pair["benchmark"]) * 100
    rs_smoothed = raw_rs.ewm(span=RS_EMA_SPAN, adjust=False).mean()
    rs_ratio = _zscore(rs_smoothed)

    momentum = (rs_ratio - rs_ratio.shift(1)).ewm(span=MOMENTUM_EMA_SPAN, adjust=False).mean()
    rs_momentum = _zscore(momentum)

    out = pd.DataFrame({"rs_ratio": rs_ratio, "rs_momentum": rs_momentum})
    return out[out["rs_ratio"].notna() & out["rs_momentum"].notna()]


def quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Which quadrant a point sits in. A value of exactly 100 counts as strong."""
    if rs_ratio >= 100:
        return "leading" if rs_momentum >= 100 else "weakening"
    return "improving" if rs_momentum >= 100 else "lagging"


def bars_in_quadrant(points: pd.DataFrame) -> int:
    """How many consecutive bars, ending with the latest, share its quadrant."""
    if points.empty:
        return 0
    quadrants = [
        quadrant(r, m) for r, m in zip(points["rs_ratio"], points["rs_momentum"], strict=True)
    ]
    current = quadrants[-1]
    count = 0
    for q in reversed(quadrants):
        if q != current:
            break
        count += 1
    return count


def summarise(points: pd.DataFrame, tail: int = MAX_TAIL) -> dict[str, Any] | None:
    """The latest position, its quadrant, its run length and its trail."""
    if points.empty:
        return None
    trail = points.iloc[-tail:]
    last = points.iloc[-1]
    rs_ratio = float(last["rs_ratio"])
    rs_momentum = float(last["rs_momentum"])
    return {
        "quadrant": quadrant(rs_ratio, rs_momentum),
        "rs_ratio": round(rs_ratio, 2),
        "rs_momentum": round(rs_momentum, 2),
        "bars_in_quadrant": bars_in_quadrant(points),
        "tail": [
            {
                "date": stamp.strftime("%Y-%m-%d"),
                "rs_ratio": round(float(row["rs_ratio"]), 2),
                "rs_momentum": round(float(row["rs_momentum"]), 2),
            }
            for stamp, row in trail.iterrows()
        ],
    }


def _load_closes(
    instrument: Instrument,
    start_date: str,
    end_date: str,
    source: str,
    creds: dict[str, Any],
) -> pd.Series:
    """Daily closes for one instrument, reused across maps for a few minutes.

    Cached per symbol rather than per map, so adding one stock to a map of
    eighteen sectors costs one history request, not nineteen.
    """
    key = (
        instrument.symbol,
        instrument.exchange,
        source,
        creds.get("broker"),
        start_date,
        end_date,
    )
    cached = _CLOSES_CACHE.get(key)
    if cached is not None:
        return cached
    matrix = load_prices(
        [instrument.symbol],
        [instrument.exchange],
        start_date,
        end_date,
        source=source,
        allowed_exchanges=EXCHANGES,
        # This module's own cache expires; the loader's does not, and would
        # keep a map from before a Historify download for the rest of the day.
        cache=False,
        **creds,
    )
    closes = matrix.closes[matrix.closes.columns[0]]
    _CLOSES_CACHE[key] = closes
    return closes


def _missing_reason(source: str) -> str:
    if source == "db":
        return (
            "Historify has no daily history for this symbol. Download it in "
            "Historify, or switch the data source to Broker API."
        )
    return (
        "Your broker returned no history for this symbol. Some brokers do not "
        "publish every sector index; Historify may have it."
    )


def resolve_instruments(
    requested: list[dict[str, Any]] | None,
) -> tuple[list[Instrument], str | None]:
    """Turn a requested list into instruments, or explain what is wrong with it.

    An empty or missing list means the default sector set. Duplicates are
    dropped, keeping the first. A symbol without a label takes the sector name
    when it is one of the default sectors, and its own symbol otherwise.
    """
    if not requested:
        return list(SECTORS), None
    if len(requested) > MAX_INSTRUMENTS:
        return [], f"The map holds at most {MAX_INSTRUMENTS} symbols."

    out: list[Instrument] = []
    seen: set[tuple[str, str]] = set()
    for item in requested:
        symbol = str(item.get("symbol") or "").strip().upper()
        exchange = str(item.get("exchange") or "").strip().upper()
        if not symbol:
            return [], "Every symbol on the map needs a name."
        if exchange not in EXCHANGES:
            return [], (
                f"{symbol} is on {exchange or 'no exchange'}. The map takes "
                f"symbols from {', '.join(EXCHANGES)}."
            )
        if (symbol, exchange) in seen:
            continue
        seen.add((symbol, exchange))
        known = _SECTORS_BY_KEY.get((symbol, exchange))
        label = str(item.get("label") or "").strip() or (known.label if known else symbol)
        out.append(Instrument(symbol, exchange, label))
    return out, None


def compute_sector_rotation(
    benchmark: str = "NIFTY",
    timeframe: str = "daily",
    source: str = "db",
    *,
    instruments: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
    end_date: date | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """Place every requested instrument on the rotation map against ``benchmark``.

    Args:
        benchmark: one of ``BENCHMARKS``. An instrument that is the benchmark
            itself is left off the map, since it would sit on 100/100 forever.
        timeframe: ``daily`` or ``weekly``. Weekly bars are resampled from
            daily ones, so both read the same history.
        source: ``'db'`` for Historify, ``'api'`` for the broker history API.
        instruments: ``[{symbol, exchange, label?}]`` on one of ``EXCHANGES``;
            the default sector set when empty.
        end_date: the last session to include; today when omitted.

    Returns:
        ``(success, response, status_code)``. Instruments that could not be
        placed are listed under ``unavailable`` with the reason, rather than
        failing the whole map.
    """
    bench = _BENCHMARKS_BY_SYMBOL.get((benchmark or "").upper())
    if bench is None:
        return _error(f"benchmark must be one of {', '.join(_BENCHMARKS_BY_SYMBOL)}")
    if timeframe not in TIMEFRAMES:
        return _error(f"timeframe must be one of {', '.join(TIMEFRAMES)}")
    if source not in SOURCES:
        return _error("source must be 'db' (Historify) or 'api' (broker)")

    members, problem = resolve_instruments(instruments)
    if problem:
        return _error(problem)

    end = end_date or date.today()
    start = end - timedelta(days=LOOKBACK_DAYS[timeframe])
    start_date, end_date_str = start.isoformat(), end.isoformat()

    creds = {
        "api_key": api_key,
        "auth_token": auth_token,
        "feed_token": feed_token,
        "broker": broker,
    }

    try:
        bench_closes = _load_closes(bench, start_date, end_date_str, source, creds)
    except DataError:
        logger.exception(f"Sector rotation: benchmark {bench.symbol} history unavailable")
        if source == "db":
            message = (
                f"Historify has no daily history for {bench.label}. Download it "
                "in Historify, or switch the data source to Broker API."
            )
        else:
            message = (
                f"Your broker returned no history for {bench.label}. Pick another "
                "benchmark, or switch the data source to Historify."
            )
        return _error(message, 422)

    placed: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    as_of: str | None = None

    for member in members:
        if (member.symbol, member.exchange) == (bench.symbol, bench.exchange):
            unavailable.append(
                {
                    "symbol": member.symbol,
                    "exchange": member.exchange,
                    "label": member.label,
                    "reason": (
                        "This is the benchmark itself, so it would always sit at "
                        "100. Pick another benchmark to see it on the map."
                    ),
                }
            )
            continue
        try:
            closes = _load_closes(member, start_date, end_date_str, source, creds)
        except Exception as exc:  # noqa: BLE001 - one symbol must not cost the map
            if isinstance(exc, DataError):
                logger.info(f"Sector rotation: {member.symbol} skipped: {exc}")
            else:
                logger.exception(f"Sector rotation: {member.symbol} history load failed")
            unavailable.append(
                {
                    "symbol": member.symbol,
                    "exchange": member.exchange,
                    "label": member.label,
                    "reason": _missing_reason(source),
                }
            )
            continue

        summary = summarise(rrg_series(*paired_bars(closes, bench_closes, timeframe)))
        if summary is None:
            unavailable.append(
                {
                    "symbol": member.symbol,
                    "exchange": member.exchange,
                    "label": member.label,
                    "reason": (
                        f"Not enough {timeframe} history yet. The map needs at "
                        f"least {ZSCORE_MIN_BARS + 1} bars that this symbol and "
                        "the benchmark both traded."
                    ),
                }
            )
            continue

        last_date = summary["tail"][-1]["date"]
        if as_of is None or last_date > as_of:
            as_of = last_date
        placed.append(
            {
                "symbol": member.symbol,
                "exchange": member.exchange,
                "label": member.label,
                **summary,
            }
        )

    if not placed and unavailable:
        return _error("Nothing could be placed on the map. " + unavailable[0]["reason"], 422)

    return (
        True,
        {
            "status": "success",
            "data": {
                "benchmark": bench.symbol,
                "benchmark_exchange": bench.exchange,
                "benchmark_label": bench.label,
                "timeframe": timeframe,
                "source": source,
                "as_of": as_of,
                "max_tail": MAX_TAIL,
                "instruments": placed,
                "unavailable": unavailable,
            },
        },
        200,
    )
