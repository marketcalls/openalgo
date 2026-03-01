# test/test_backtest_client.py
"""Tests for BacktestClient — the SDK-compatible mock client."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest

from services.backtest_client import BacktestClient


@pytest.fixture
def config():
    return {
        "initial_capital": 100000,
        "slippage_pct": 0.05,
        "commission_per_order": 20.0,
        "commission_pct": 0.0,
    }


@pytest.fixture
def client(config):
    return BacktestClient(config)


@pytest.fixture
def sample_data():
    """Create sample OHLCV DataFrame."""
    return pd.DataFrame({
        "timestamp": [1704067200, 1704153600, 1704240000, 1704326400, 1704412800],
        "open": [100.0, 102.0, 101.0, 105.0, 103.0],
        "high": [103.0, 104.0, 106.0, 107.0, 108.0],
        "low": [99.0, 100.0, 100.0, 103.0, 101.0],
        "close": [102.0, 101.0, 105.0, 103.0, 107.0],
        "volume": [10000, 12000, 11000, 13000, 9000],
        "oi": [0, 0, 0, 0, 0],
    })


@pytest.fixture
def loaded_client(client, sample_data):
    """Client with data loaded and positioned at bar 2."""
    client.data["SBIN:NSE"] = sample_data
    client.current_bar_index["SBIN:NSE"] = 2
    client.current_timestamp = 1704240000
    return client


class TestClientInit:
    def test_initial_capital(self, client, config):
        assert client.capital == 100000
        assert client.initial_capital == 100000

    def test_empty_state(self, client):
        assert len(client.positions) == 0
        assert len(client.trades) == 0
        assert len(client.orders) == 0
        assert len(client.equity_curve) == 0


class TestHistory:
    def test_history_returns_data_up_to_current_bar(self, loaded_client):
        df = loaded_client.history(symbol="SBIN", exchange="NSE")
        # At bar index 2, should get bars 0, 1, 2 (3 bars)
        assert len(df) == 3

    def test_history_prevents_lookahead(self, loaded_client):
        df = loaded_client.history(symbol="SBIN", exchange="NSE")
        # Should not include future bars
        assert df.iloc[-1]["close"] == 105.0  # bar 2 close

    def test_history_missing_symbol(self, loaded_client):
        df = loaded_client.history(symbol="UNKNOWN", exchange="NSE")
        assert df.empty


class TestQuotes:
    def test_quotes_returns_current_bar(self, loaded_client):
        q = loaded_client.quotes(symbol="SBIN", exchange="NSE")
        assert q["status"] == "success"
        assert q["data"]["ltp"] == 105.0  # bar 2 close

    def test_quotes_missing_symbol(self, loaded_client):
        q = loaded_client.quotes(symbol="UNKNOWN", exchange="NSE")
        assert q["status"] == "error"


class TestPlaceOrder:
    def test_market_buy(self, loaded_client):
        result = loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        assert result["status"] == "success"
        assert "orderid" in result
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 10

    def test_market_sell(self, loaded_client):
        # First buy
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        # Then sell
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="SELL",
            price_type="MARKET", quantity=10, product="MIS",
        )
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 0
        assert len(loaded_client.trades) == 1

    def test_limit_order_queued(self, loaded_client):
        result = loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="LIMIT", quantity=10, price=100.0, product="MIS",
        )
        assert result["status"] == "success"
        assert len(loaded_client.pending_orders) == 1

    def test_zero_quantity_rejected(self, loaded_client):
        result = loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=0, product="MIS",
        )
        assert result["status"] == "error"


class TestPositionManagement:
    def test_add_to_position(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=5, product="MIS",
        )
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 15

    def test_partial_close(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="SELL",
            price_type="MARKET", quantity=5, product="MIS",
        )
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 5
        assert len(loaded_client.trades) == 1

    def test_reversal(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="SELL",
            price_type="MARKET", quantity=15, product="MIS",
        )
        # Should be short 5
        assert loaded_client.positions["SBIN:NSE"]["qty"] == -5


class TestPendingOrders:
    def test_limit_buy_triggers(self, loaded_client, sample_data):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="LIMIT", quantity=10, price=100.0, product="MIS",
        )
        # Advance to bar 3 where low=103, so limit at 100 won't trigger
        loaded_client.current_bar_index["SBIN:NSE"] = 3
        loaded_client.process_pending_orders()
        assert len(loaded_client.pending_orders) == 1  # still pending

    def test_cancel_order(self, loaded_client):
        result = loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="LIMIT", quantity=10, price=100.0, product="MIS",
        )
        loaded_client.cancelorder(order_id=result["orderid"])
        assert len(loaded_client.pending_orders) == 0


class TestEquity:
    def test_record_equity(self, loaded_client):
        loaded_client.record_equity(1704240000)
        assert len(loaded_client.equity_curve) == 1
        assert loaded_client.equity_curve[0]["equity"] == 100000  # no positions

    def test_equity_with_position(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        loaded_client.record_equity(1704240000)
        assert len(loaded_client.equity_curve) == 1
        # Capital reduced by commission, but position adds unrealized P&L


class TestSmartOrder:
    def test_smart_buy_from_flat(self, loaded_client):
        loaded_client.placesmartorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", product="MIS",
            quantity=1, position_size=10,
        )
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 10

    def test_smart_no_action_needed(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        result = loaded_client.placesmartorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", product="MIS",
            quantity=1, position_size=10,
        )
        assert result["message"] == "No action needed"


class TestCloseAll:
    def test_close_all_positions(self, loaded_client):
        loaded_client.placeorder(
            symbol="SBIN", exchange="NSE", action="BUY",
            price_type="MARKET", quantity=10, product="MIS",
        )
        loaded_client.close_all_positions_at_end()
        assert loaded_client.positions["SBIN:NSE"]["qty"] == 0
        assert len(loaded_client.trades) == 1


class TestFunds:
    def test_funds_initial(self, loaded_client):
        f = loaded_client.funds()
        assert f["status"] == "success"
        assert float(f["data"]["availablecash"]) == 100000

    def test_positionbook_empty(self, loaded_client):
        pb = loaded_client.positionbook()
        assert pb["status"] == "success"
        assert len(pb["data"]) == 0
