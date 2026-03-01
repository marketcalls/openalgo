# test/test_backtest_engine.py
"""Tests for the backtest engine orchestrator."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from threading import Event

from services.backtest_engine import (
    BacktestEngine,
    generate_backtest_id,
    validate_data_availability,
    _storage_interval_for,
)


class TestGenerateBacktestId:
    def test_format(self):
        bt_id = generate_backtest_id()
        assert bt_id.startswith("BT-")
        parts = bt_id.split("-")
        # BT-YYYYMMDD-HHMMSS-uuid8
        assert len(parts) == 4

    def test_unique(self):
        ids = {generate_backtest_id() for _ in range(100)}
        assert len(ids) == 100


class TestStorageInterval:
    def test_intraday_maps_to_1m(self):
        for iv in ["1m", "5m", "15m", "30m", "1h"]:
            assert _storage_interval_for(iv) == "1m"

    def test_daily_maps_to_d(self):
        assert _storage_interval_for("D") == "D"

    def test_unknown_maps_to_d(self):
        assert _storage_interval_for("W") == "D"


class TestValidateDataAvailability:
    @patch("services.backtest_engine.get_data_range")
    def test_all_available(self, mock_range):
        mock_range.return_value = {
            "first_timestamp": 1704067200,
            "last_timestamp": 1735689600,
            "record_count": 100000,
        }
        result = validate_data_availability(
            ["SBIN", "TCS"], "NSE", "5m", "2024-01-01", "2024-12-31"
        )
        assert result["available"] is True
        assert result["details"]["SBIN"]["has_data"] is True
        assert result["details"]["TCS"]["has_data"] is True

    @patch("services.backtest_engine.get_data_range")
    def test_some_missing(self, mock_range):
        def side_effect(sym, exc, iv):
            if sym == "SBIN":
                return {"first_timestamp": 1, "last_timestamp": 2, "record_count": 100}
            return None

        mock_range.side_effect = side_effect
        result = validate_data_availability(
            ["SBIN", "UNKNOWN"], "NSE", "D", "2024-01-01", "2024-12-31"
        )
        assert result["available"] is False
        assert result["details"]["SBIN"]["has_data"] is True
        assert result["details"]["UNKNOWN"]["has_data"] is False


class TestBacktestEngine:
    @pytest.fixture
    def base_config(self):
        return {
            "backtest_id": "BT-TEST-001",
            "user_id": "test_user",
            "name": "Test Backtest",
            "strategy_id": None,
            "strategy_code": "# empty strategy\npass",
            "symbols": ["SBIN"],
            "exchange": "NSE",
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "interval": "D",
            "initial_capital": 100000,
            "slippage_pct": 0.05,
            "commission_per_order": 20.0,
            "commission_pct": 0.0,
            "data_source": "db",
        }

    def test_cancellation_works(self, base_config):
        cancel = Event()
        cancel.set()  # Pre-cancel
        engine = BacktestEngine(base_config, cancel_event=cancel)

        with patch.object(engine, "_update_status"):
            with patch.object(engine, "_emit_progress"):
                with patch.object(engine, "_load_data", return_value={"SBIN:NSE": MagicMock()}):
                    result = engine.run()
                    assert result["status"] == "cancelled"

    def test_empty_data_fails(self, base_config):
        engine = BacktestEngine(base_config)

        with patch.object(engine, "_update_status"):
            with patch.object(engine, "_emit_progress"):
                with patch.object(engine, "_load_data", return_value={}):
                    result = engine.run()
                    assert result["status"] == "failed"
                    assert "No data" in result["error"]

    def test_date_to_timestamp(self, base_config):
        engine = BacktestEngine(base_config)
        ts = engine._date_to_timestamp("2024-01-01")
        assert ts == 1704067200  # 2024-01-01 00:00:00 UTC

        ts_eod = engine._date_to_timestamp("2024-01-01", end_of_day=True)
        assert ts_eod > ts
