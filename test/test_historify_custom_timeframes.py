"""Stored-data aggregation keeps continuous buckets across calendar years."""

from contextlib import contextmanager
from datetime import datetime, timezone

import duckdb
import pytest

from database import historify_db


def epoch(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture
def stored(monkeypatch, tmp_path):
    path = str(tmp_path / "candles.duckdb")
    with duckdb.connect(path) as connection:
        connection.execute(
            "CREATE TABLE market_data(symbol VARCHAR, exchange VARCHAR, interval VARCHAR, timestamp BIGINT, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT, oi BIGINT)"
        )

    @contextmanager
    def connection():
        with duckdb.connect(path) as conn:
            yield conn

    monkeypatch.setattr(historify_db, "get_connection", connection)
    monkeypatch.setattr(historify_db, "_get_market_open_seconds", lambda _: 33300)

    def insert(interval, times):
        with connection() as conn:
            for i, time in enumerate(times):
                conn.execute(
                    "INSERT INTO market_data VALUES ('TEST','NSE',?,?,?,?,?,?,?,?)",
                    [interval, time, i + 1, i + 3, i, i + 2, 10, i],
                )

    return insert


def test_multiday_reads_daily_storage(stored):
    times = [epoch("2026-10-01T03:45:00"), epoch("2026-10-02T03:45:00")]
    stored("D", times)
    frame = historify_db.get_ohlcv("TEST", "NSE", "2D")
    assert len(frame) > 0
    assert frame.volume.sum() == 20


def test_two_week_anchor_does_not_restart_at_new_year(stored):
    stored("D", [epoch("2020-12-28T03:45:00"), epoch("2021-01-04T03:45:00")])
    frame = historify_db.get_ohlcv("TEST", "NSE", "2W")
    # Monday 1970-01-05 is the continuous multi-week anchor.
    assert frame.timestamp.tolist() == [epoch("2020-12-28T00:00:00")]


def test_seven_month_bucket_crosses_the_year(stored):
    stored("D", [epoch("2025-12-15T03:45:00"), epoch("2026-01-15T03:45:00")])
    frame = historify_db.get_ohlcv("TEST", "NSE", "7M")
    # Absolute month 24311 starts December 2025 and includes January 2026.
    assert frame.timestamp.tolist() == [epoch("2025-12-01T00:00:00")]
    assert frame.iloc[0].open == 1 and frame.iloc[0].close == 3
    assert frame.iloc[0].volume == 20


@pytest.mark.parametrize("interval,seconds", [("7m", 420), ("2h", 7200)])
def test_intraday_aggregation_resets_at_each_session(stored, interval, seconds):
    opening = epoch("2026-10-01T03:45:00")
    stored("1m", [opening, opening + 60, opening + seconds, opening + 86400])
    frame = historify_db.get_ohlcv("TEST", "NSE", interval)
    assert frame.timestamp.tolist() == [opening, opening + seconds, opening + 86400]
    assert frame.iloc[0].volume == 20
