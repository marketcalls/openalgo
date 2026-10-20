"""Historify writes must remain correct when gthread runs them in parallel."""

import threading

import pandas as pd
import pytest

from database import historify_db
from services import historify_service


@pytest.fixture
def historify_database(monkeypatch, tmp_path):
    """Use an isolated initialized DuckDB database for each concurrency test."""
    original_path = historify_db.HISTORIFY_DB_PATH
    monkeypatch.setattr(historify_db, "HISTORIFY_DB_PATH", str(tmp_path / "historify.duckdb"))
    historify_db.init_database()
    yield
    monkeypatch.setattr(historify_db, "HISTORIFY_DB_PATH", original_path)


def _concurrently(count, work):
    barrier = threading.Barrier(count)
    errors = []
    errors_lock = threading.Lock()

    def run(index):
        try:
            barrier.wait()
            work(index)
        except Exception as error:  # assertions below report all worker failures
            with errors_lock:
                errors.append(error)

    workers = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert not worker.is_alive(), "a Historify write worker did not finish"
    assert not errors, errors


def _candle(close=100.0):
    return pd.DataFrame(
        [{"timestamp": 1_700_000_000, "open": 99.0, "high": 101.0, "low": 98.0,
          "close": close, "volume": 10, "oi": 0}]
    )


def test_parallel_new_symbol_upserts_create_every_catalog_row(historify_database):
    """The catalog check/insert gap cannot lose simultaneous new symbols."""
    _concurrently(
        8,
        lambda index: historify_db.upsert_market_data(
            _candle(), f"SYM{index}", "NSE", "D"
        ),
    )

    with historify_db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_data").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM data_catalog").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(DISTINCT id) FROM data_catalog").fetchone()[0] == 8


def test_parallel_same_symbol_upserts_leave_one_consistent_catalog_row(historify_database):
    """Concurrent ON CONFLICT upserts neither raise nor duplicate the catalog."""
    _concurrently(
        8,
        lambda index: historify_db.upsert_market_data(_candle(100.0 + index), "SBIN", "NSE", "D"),
    )

    with historify_db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM market_data").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM data_catalog").fetchone()[0] == 1


def test_parallel_job_creation_allocates_unique_item_ids(historify_database):
    """Sequence allocation replaces the unsafe MAX(id) + ROW_NUMBER() pattern."""
    _concurrently(
        8,
        lambda index: _assert_job_created(index),
    )

    with historify_db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM download_jobs").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM job_items").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(DISTINCT id) FROM job_items").fetchone()[0] == 8


def _assert_job_created(index):
    ok, message = historify_db.create_download_job(
        f"job-{index}", "custom", [{"symbol": f"SYM{index}", "exchange": "NSE"}], "D",
        "2026-01-01", "2026-01-02"
    )
    assert ok, message


def test_historify_download_can_wait_without_bypassing_rate_limiting(monkeypatch):
    """Jobs opt out of request-thread refusal but retain the shared limiter."""
    captured = {}
    monkeypatch.setattr(
        historify_service,
        "get_history",
        lambda **kwargs: (captured.update(kwargs) or (True, {"data": []}, 200)),
    )

    ok, _, status = historify_service.download_data(
        "SBIN", "NSE", "D", "2026-01-01", "2026-01-02", "api-key"
    )

    assert ok and status == 200
    assert captured["background"] is True
