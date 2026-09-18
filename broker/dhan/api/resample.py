"""Timeframes Dhan does not serve, built from the ones it does.

Dhan's history API returns 1, 5, 15, 25 and 60 minute candles and daily
candles. 30m and 4h are aggregated here from 15m, and W and M from D.

Intraday buckets are anchored to the exchange's session open, not to
midnight, so a 4h NSE bar covers 09:15-13:15 and 13:15-15:30, and a 30m bar
opens at 09:15, 09:45 and so on. 15m is the base for both because every
15 minute bar sits inside exactly one bucket for either session open.

Timestamps follow data.py's convention rather than a timezone of their own:
`datetime.fromtimestamp()` on a stamp gives the IST wall-clock time of the
bar (intraday) or 05:30 on its IST date (daily). Buckets are computed on that
wall clock and stamped back through the same conversion, so derived bars line
up with native ones whatever the server's timezone is.
"""

from datetime import date, datetime, timedelta

import pandas as pd

# interval -> (native interval to fetch, bucket size in minutes or "W"/"M")
DERIVED_INTERVALS = {
    "30m": ("15m", 30),
    "4h": ("15m", 240),
    "W": ("D", "W"),
    "M": ("D", "M"),
}

# Advertised in BrokerData.timeframe_map so the intervals API offers them.
DERIVED_TIMEFRAMES = {interval: base for interval, (base, _) in DERIVED_INTERVALS.items()}

# Session open (hour, minute) in IST. Commodity and currency segments open at
# 09:00; everything else Dhan serves opens at 09:15.
_SESSION_OPEN = {"MCX": (9, 0), "NCO": (9, 0), "CDS": (9, 0), "BCD": (9, 0)}
_DEFAULT_SESSION_OPEN = (9, 15)

# data.py stamps a daily candle at 05:30 wall-clock on its IST date.
_DAILY_STAMP_OFFSET = pd.Timedelta(hours=5, minutes=30)

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


def _to_date(value) -> date:
    return pd.Timestamp(value).date()


def _widen_range(start: date, end: date, rule: str) -> tuple[date, date]:
    """Extend a window to whole weeks or months so no edge bucket is partial.

    A chart pages history backwards; a window ending mid-week would otherwise
    return a short bar for that week, stamped the same as the full one the
    newer page already holds.
    """
    if rule == "W":
        start = start - timedelta(days=start.weekday())
        end = end + timedelta(days=6 - end.weekday())
    else:
        start = start.replace(day=1)
        next_month = (end.replace(day=1) + timedelta(days=32)).replace(day=1)
        end = next_month - timedelta(days=1)
    return start, min(end, date.today())


def aggregate(df: pd.DataFrame, interval: str, exchange: str) -> pd.DataFrame:
    """Aggregate native candles into the derived interval.

    Args:
        df: Native candles in data.py's format, any order.
        interval: One of DERIVED_INTERVALS.
        exchange: OpenAlgo exchange code; decides the intraday session anchor.

    Returns:
        Candles with columns COLUMNS, sorted by timestamp.
    """
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)

    _, rule = DERIVED_INTERVALS[interval]
    df = df.sort_values("timestamp").reset_index(drop=True)
    wall = pd.DatetimeIndex([datetime.fromtimestamp(int(t)) for t in df["timestamp"]])
    day = wall.normalize()

    if rule == "W":
        bucket = day - pd.to_timedelta(wall.dayofweek, unit="D") + _DAILY_STAMP_OFFSET
    elif rule == "M":
        bucket = day - pd.to_timedelta(wall.day - 1, unit="D") + _DAILY_STAMP_OFFSET
    else:
        hour, minute = _SESSION_OPEN.get(exchange, _DEFAULT_SESSION_OPEN)
        session_open = day + pd.Timedelta(hours=hour, minutes=minute)
        minutes = (wall - session_open) // pd.Timedelta(minutes=1)
        bucket = session_open + pd.to_timedelta((minutes // rule) * rule, unit="min")

    out = (
        df.assign(_bucket=bucket)
        .groupby("_bucket", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            oi=("oi", "last"),
        )
    )
    out.insert(0, "timestamp", [int(ts.to_pydatetime().timestamp()) for ts in out.index])
    out["volume"] = out["volume"].astype("int64")
    out["oi"] = out["oi"].fillna(0).astype("int64")
    return out.reset_index(drop=True)[COLUMNS]


def get_derived_history(get_history, symbol, exchange, interval, start_date, end_date):
    """Fetch the native interval through `get_history` and aggregate it.

    Args:
        get_history: BrokerData.get_history, called with the native interval.
        symbol, exchange, start_date, end_date: As for BrokerData.get_history.
        interval: One of DERIVED_INTERVALS.
    """
    base, rule = DERIVED_INTERVALS[interval]
    start, end = _to_date(start_date), _to_date(end_date)
    if rule in ("W", "M"):
        start, end = _widen_range(start, end, rule)
    df = get_history(symbol, exchange, base, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    return aggregate(df, interval, exchange)
