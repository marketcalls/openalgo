"""
Bar delivery for the indicator screener.

Two things here can be wrong in a way nothing else catches.

**Candle alignment.** The 5m/15m/1h candles the screener reads are aggregated
from stored 1m bars by an expression written in SQL, and the live-bar stitcher
has to land on the same boundaries from Python. Nothing at runtime compares
them: if they drift, the aggregation quietly produces candles offset by minutes
and every indicator reading is wrong by one bar's worth of data. So the SQL
expression is executed here, against real DuckDB, and asserted equal to
``bucket_start`` over the same timestamps.

**Live stitching.** Appending a bar is the one place the screener writes into a
series, and a ragged column -- one array a different length from the others --
is exactly what an indicator's ``calc`` cannot survive. Every case asserts the
columns stayed rectangular.

Run: uv run pytest test/test_screener_bars.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import duckdb
import pytest

from database.historify_db import IST_OFFSET_SECONDS, bucket_start
from services import screener_service
from services.screener_service import _apply_quote, _stitch_live

IST = timezone(timedelta(seconds=IST_OFFSET_SECONDS))
NSE_OPEN = 33300  # 09:15 IST


def ist(year, month, day, hour, minute, second=0) -> int:
    """IST wall clock to UTC epoch seconds, the way stored bars are keyed."""
    return int(datetime(year, month, day, hour, minute, second, tzinfo=IST).timestamp())


def sql_bucket(ts: int, interval_seconds: int, market_open: int) -> int:
    """
    The bucket expression exactly as ``_get_aggregated_ohlcv`` embeds it.

    Kept as a literal copy rather than imported, because the point is to detect
    the two definitions diverging -- sharing one would test nothing.
    """
    off, secs = IST_OFFSET_SECONDS, interval_seconds
    expression = (
        f"SELECT (FLOOR(({ts} + {off}) / 86400) * 86400 - {off}) + {market_open} + "
        f"FLOOR(((({ts} + {off}) % 86400) - {market_open}) / {secs}) * {secs}"
    )
    with duckdb.connect() as conn:
        return int(conn.execute(expression).fetchone()[0])


# ---------------------------------------------------------------------------
# Candle alignment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interval_seconds", [300, 900, 3600])
@pytest.mark.parametrize(
    "moment",
    [
        ist(2026, 9, 3, 9, 15, 0),  # the open itself
        ist(2026, 9, 3, 9, 17, 30),  # mid-candle
        ist(2026, 9, 3, 11, 42, 11),  # arbitrary mid-session
        ist(2026, 9, 3, 15, 29, 59),  # last second of the session
        ist(2026, 9, 3, 8, 5, 0),  # pre-open, negative bucket offset
        ist(2026, 9, 3, 18, 0, 0),  # after hours
    ],
)
def test_python_bucket_matches_sql(moment, interval_seconds):
    """
    The Python twin agrees with the SQL for every candle width and time of day.

    Pre-open is included on purpose: it is the case where floor division and
    truncation disagree, so a ``//`` swapped for ``int()`` shows up here and
    nowhere else.
    """
    assert bucket_start(moment, interval_seconds, NSE_OPEN) == sql_bucket(
        moment, interval_seconds, NSE_OPEN
    )


def test_bucket_boundaries_are_market_open_aligned():
    """NSE 5m candles run 09:15-09:20, not 09:10-09:15."""
    assert bucket_start(ist(2026, 9, 3, 9, 15, 0), 300, NSE_OPEN) == ist(2026, 9, 3, 9, 15)
    assert bucket_start(ist(2026, 9, 3, 9, 19, 59), 300, NSE_OPEN) == ist(2026, 9, 3, 9, 15)
    assert bucket_start(ist(2026, 9, 3, 9, 20, 0), 300, NSE_OPEN) == ist(2026, 9, 3, 9, 20)


def test_hourly_candles_start_at_the_open_not_the_hour():
    """An NSE hourly candle is 09:15-10:15. This is the case a naive bucket gets wrong."""
    assert bucket_start(ist(2026, 9, 3, 10, 14, 0), 3600, NSE_OPEN) == ist(2026, 9, 3, 9, 15)
    assert bucket_start(ist(2026, 9, 3, 10, 15, 0), 3600, NSE_OPEN) == ist(2026, 9, 3, 10, 15)


# ---------------------------------------------------------------------------
# Live stitching
# ---------------------------------------------------------------------------


def series(*times: int) -> dict[str, list]:
    """A columnar series with a distinct, checkable price per bar."""
    return {
        "t": list(times),
        "o": [100.0 + i for i, _ in enumerate(times)],
        "h": [101.0 + i for i, _ in enumerate(times)],
        "l": [99.0 + i for i, _ in enumerate(times)],
        "c": [100.5 + i for i, _ in enumerate(times)],
        "v": [1000 for _ in times],
    }


def assert_rectangular(columns: dict[str, list]) -> None:
    lengths = {key: len(values) for key, values in columns.items()}
    assert len(set(lengths.values())) == 1, f"ragged columns: {lengths}"


def test_quote_inside_the_last_candle_amends_it():
    columns = series(ist(2026, 9, 3, 9, 15), ist(2026, 9, 3, 9, 20))
    before = len(columns["t"])

    assert _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 9, 23))

    assert len(columns["t"]) == before, "amending must not append"
    assert columns["c"][-1] == 250.0
    assert columns["h"][-1] == 250.0, "a high trade extends the high"
    assert columns["l"][-1] == 100.0, "and leaves the low alone"
    assert_rectangular(columns)


def test_quote_below_the_low_extends_the_low():
    columns = series(ist(2026, 9, 3, 9, 15))
    _apply_quote(columns, "NSE", "5m", ltp=1.0, now=ist(2026, 9, 3, 9, 17))
    assert columns["l"][-1] == 1.0
    assert columns["h"][-1] == 101.0


def test_quote_in_the_next_candle_appends_exactly_one_bar():
    columns = series(ist(2026, 9, 3, 9, 15), ist(2026, 9, 3, 9, 20))

    assert _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 9, 26))

    assert len(columns["t"]) == 3
    assert columns["t"][-1] == ist(2026, 9, 3, 9, 25)
    assert columns["o"][-1] == columns["h"][-1] == columns["l"][-1] == columns["c"][-1] == 250.0
    assert columns["v"][-1] == 0, "a forming bar's volume is not known from an LTP"
    assert_rectangular(columns)


def test_stale_quote_changes_nothing():
    """A quote older than the last stored bar must not rewrite history."""
    columns = series(ist(2026, 9, 3, 9, 15), ist(2026, 9, 3, 14, 30))
    snapshot = {key: list(values) for key, values in columns.items()}

    assert not _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 10, 0))

    assert columns == snapshot


def test_quote_more_than_one_candle_ahead_changes_nothing():
    """
    After hours the LTP is the day's close and 'now' is many candles past the
    last bar. Appending would invent a flat candle at a time the market was
    shut, so the series is left alone and its last timestamp stays honest.
    """
    columns = series(ist(2026, 9, 3, 15, 25))
    snapshot = {key: list(values) for key, values in columns.items()}

    assert not _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 19, 0))

    assert columns == snapshot


def test_stale_store_is_not_papered_over():
    """A store days behind has a hole no single price can fill."""
    columns = series(ist(2026, 8, 21, 15, 25))
    snapshot = {key: list(values) for key, values in columns.items()}

    assert not _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 11, 0))

    assert columns == snapshot


def test_daily_bar_for_today_is_amended_not_appended():
    columns = series(ist(2026, 9, 2, 0, 0), ist(2026, 9, 3, 0, 0))

    assert _apply_quote(columns, "NSE", "D", ltp=250.0, now=ist(2026, 9, 3, 11, 0))

    assert len(columns["t"]) == 2
    assert columns["c"][-1] == 250.0


def test_daily_bar_for_the_next_session_preserves_the_time_convention():
    """
    Daily timestamps carry whatever time of day the ingest wrote them at, so a
    new bar is derived by shifting the last one rather than built from scratch.
    """
    columns = series(ist(2026, 9, 2, 9, 15))

    assert _apply_quote(columns, "NSE", "D", ltp=250.0, now=ist(2026, 9, 3, 11, 0))

    assert columns["t"][-1] == ist(2026, 9, 3, 9, 15)
    assert_rectangular(columns)


def test_series_without_volume_stays_rectangular():
    """Indices carry no volume column; appending must not create one."""
    columns = series(ist(2026, 9, 3, 9, 15))
    del columns["v"]

    _apply_quote(columns, "NSE", "5m", ltp=250.0, now=ist(2026, 9, 3, 9, 21))

    assert "v" not in columns
    assert_rectangular(columns)


# ---------------------------------------------------------------------------
# The batch quote fan-out
# ---------------------------------------------------------------------------


def test_stitch_live_skips_symbols_the_broker_did_not_return(monkeypatch):
    now_bucket = ist(2026, 9, 3, 9, 15)
    data = {"NSE:AAA": series(now_bucket), "NSE:BBB": series(now_bucket)}
    untouched = {key: list(values) for key, values in data["NSE:BBB"].items()}

    monkeypatch.setattr(
        screener_service,
        "get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [{"symbol": "AAA", "exchange": "NSE", "data": {"ltp": 250.0}}],
            },
            200,
        ),
    )
    monkeypatch.setattr(screener_service, "datetime", _FrozenClock(ist(2026, 9, 3, 9, 17)))

    assert _stitch_live(data, "5m", api_key="key")

    assert data["NSE:AAA"]["c"][-1] == 250.0
    assert data["NSE:BBB"] == untouched


def test_stitch_live_survives_a_failing_quote_chunk(monkeypatch):
    """A broker that refuses must cost the live bar, not the whole scan."""
    data = {"NSE:AAA": series(ist(2026, 9, 3, 9, 15))}
    snapshot = {key: list(values) for key, values in data["NSE:AAA"].items()}

    def boom(symbols, api_key=None):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(screener_service, "get_multiquotes", boom)

    assert _stitch_live(data, "5m", api_key="key") is False
    assert data["NSE:AAA"] == snapshot


class _FrozenClock:
    """Stands in for ``datetime`` so 'now' is a fixture, not the wall clock."""

    def __init__(self, epoch: int):
        self._epoch = epoch

    def now(self, tz=None):
        return datetime.fromtimestamp(self._epoch, tz or UTC)

    @staticmethod
    def fromtimestamp(ts, tz=None):
        return datetime.fromtimestamp(ts, tz)
