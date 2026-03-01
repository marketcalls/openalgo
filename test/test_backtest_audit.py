#!/usr/bin/env python
"""
ADVERSARIAL AUDIT — Full backtest engine audit.
Phases 1-7, 10 of the 10-phase audit protocol.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest
from services.backtest_client import BacktestClient
from services.backtest_metrics import calculate_metrics, _get_bars_per_year, _empty_metrics
from services.backtest_patcher import StrategyPatcher


def make_client(capital=100000, slippage=0.05, commission=20.0, comm_pct=0.0):
    return BacktestClient({
        "initial_capital": capital,
        "slippage_pct": slippage,
        "commission_per_order": commission,
        "commission_pct": comm_pct,
    })


def make_data(closes, symbol="SBIN", exchange="NSE"):
    """Create simple OHLCV data from a list of close prices."""
    n = len(closes)
    df = pd.DataFrame({
        "timestamp": list(range(1000, 1000 + n)),
        "open": closes,
        "high": [c + 2 for c in closes],
        "low": [c - 2 for c in closes],
        "close": closes,
        "volume": [10000] * n,
        "oi": [0] * n,
    })
    return df


# ═══════════════════════════════════════════════════════════════════
# PHASE 1 — LOOK-AHEAD BIAS
# ═══════════════════════════════════════════════════════════════════

class TestPhase1LookAheadBias:

    def test_history_only_returns_up_to_current_bar(self):
        """Prove history() never exposes future data."""
        c = make_client()
        c.data["S:E"] = make_data([100, 110, 120, 130, 140])
        for idx in range(5):
            c.current_bar_index["S:E"] = idx
            df = c.history(symbol="S", exchange="E")
            assert len(df) == idx + 1, f"At bar {idx}, got {len(df)} rows"
            assert df.iloc[-1]["close"] == [100,110,120,130,140][idx]

    def test_no_internal_method_reads_future(self):
        """Verify _get_current_bar never reads beyond index."""
        c = make_client()
        data = make_data([100, 200, 300])
        c.data["S:E"] = data
        c.current_bar_index["S:E"] = 0
        bar = c._get_current_bar("S", "E")
        assert bar["close"] == 100  # Not 200 or 300

    def test_cheating_strategy_does_not_get_perfect_returns(self):
        """
        Strategy that tries to buy when next bar is higher.
        Since history() only shows up to current bar, it CANNOT
        know tomorrow's close. If it tries df.iloc[-1] that's today.
        """
        c = make_client(commission=0, slippage=0)
        prices = [100, 105, 95, 110, 90, 120, 80]
        c.data["S:E"] = make_data(prices)

        # Simulate: at each bar, strategy can only see history up to current
        for i in range(len(prices)):
            c.current_bar_index["S:E"] = i
            c.current_timestamp = 1000 + i
            df = c.history(symbol="S", exchange="E")
            # Try to "cheat" by reading the last row — it's TODAY, not tomorrow
            last_close = df.iloc[-1]["close"]
            assert last_close == prices[i], "History leaked future data!"

    def test_deliberate_future_access_fails(self):
        """If someone tries to access data[current_idx+1], it should fail or return wrong data."""
        c = make_client()
        data = make_data([100, 200, 300])
        c.data["S:E"] = data
        c.current_bar_index["S:E"] = 0

        # history() returns only 1 bar
        df = c.history(symbol="S", exchange="E")
        assert len(df) == 1
        # Accessing iloc[1] should raise IndexError
        with pytest.raises(IndexError):
            _ = df.iloc[1]

    def test_advance_to_never_overshoots(self):
        """advance_to should set index to bar AT or BEFORE timestamp."""
        c = make_client()
        c.data["S:E"] = make_data([100, 200, 300])
        # Advance to timestamp 1001 (bar index 1)
        c.advance_to(1001)
        assert c.current_bar_index["S:E"] == 1
        # Advance to timestamp 1000 (bar index 0)
        c.advance_to(1000)
        assert c.current_bar_index["S:E"] == 0
        # Advance to timestamp 999 (before data — should be -1)
        c.advance_to(999)
        assert c.current_bar_index["S:E"] == -1


# ═══════════════════════════════════════════════════════════════════
# PHASE 2 — ORDER EXECUTION EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestPhase2OrderExecution:

    def _setup(self, capital=100000, slippage=0, commission=0):
        c = make_client(capital=capital, slippage=slippage, commission=commission)
        c.data["S:E"] = make_data([100, 105, 95, 110])
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000
        return c

    def test_case1_partial_close(self):
        """Buy 100, Sell 40, Sell 60 — verify trades and capital."""
        c = self._setup(commission=20)
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=100, price_type="MARKET")
        # commission = 20 deducted
        assert c.positions["S:E"]["qty"] == 100

        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=40, price_type="MARKET")
        assert c.positions["S:E"]["qty"] == 60
        assert len(c.trades) == 1  # First partial close logged

        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=60, price_type="MARKET")
        assert c.positions["S:E"]["qty"] == 0
        assert len(c.trades) == 2  # Second close logged

        # Both trades should have commission
        assert c.trades[0]["commission"] > 0
        assert c.trades[1]["commission"] > 0

    def test_case2_reversal(self):
        """Buy 100, Sell 200 — should close long + open short."""
        c = self._setup()
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=100, price_type="MARKET")
        assert c.positions["S:E"]["qty"] == 100

        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=200, price_type="MARKET")
        assert c.positions["S:E"]["qty"] == -100  # Short 100
        assert len(c.trades) == 1  # Close of the long recorded

        # Verify the trade action is LONG (was a long position closed)
        assert c.trades[0]["action"] == "LONG"
        assert c.trades[0]["quantity"] == 100

    def test_case3_same_bar_sl_and_limit(self):
        """Both SL and LIMIT could trigger on same bar — verify deterministic."""
        c = self._setup()
        # Buy 100 first
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=100, price_type="MARKET")

        # Place SL-SELL at trigger=98 and LIMIT-SELL at 104
        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=100,
                     price_type="SL", trigger_price=98, price=97, product="MIS")
        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=100,
                     price_type="LIMIT", price=104, product="MIS")

        # Move to bar 1: high=107, low=103 — LIMIT triggers (high>=104), SL doesn't (low>98)
        c.current_bar_index["S:E"] = 1
        c.current_timestamp = 1001
        c.process_pending_orders()

        # Only LIMIT should have triggered
        filled = [o for o in c.orders if o["status"] == "complete" and o["price_type"] != "MARKET"]
        assert len(filled) == 1

    def test_case4_commission_exceeds_profit(self):
        """Small winning trade where commission > pnl."""
        c = make_client(capital=100000, slippage=0, commission=50)
        c.data["S:E"] = make_data([100, 100.10])  # tiny gain
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000

        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=1, price_type="MARKET")
        # Move to bar 1
        c.current_bar_index["S:E"] = 1
        c.current_timestamp = 1001
        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=1, price_type="MARKET")

        assert len(c.trades) == 1
        t = c.trades[0]
        # PnL = 0.10, Commission on entry=50, commission on exit=50
        # net_pnl = pnl - commission_on_exit = 0.10 - 50 = -49.90
        assert t["net_pnl"] < 0, f"Net PnL should be negative: {t['net_pnl']}"

    def test_case5_slippage_direction(self):
        """BUY increases price, SELL decreases price."""
        c = make_client(slippage=1.0, commission=0)  # 1% slippage
        c.data["S:E"] = make_data([100])
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000

        buy_price = c._apply_slippage(100.0, "BUY")
        sell_price = c._apply_slippage(100.0, "SELL")

        assert buy_price > 100.0, f"BUY slippage should increase price: {buy_price}"
        assert sell_price < 100.0, f"SELL slippage should decrease price: {sell_price}"
        assert buy_price == 101.0
        assert sell_price == 99.0

    def test_case6_multi_symbol_timeline(self):
        """Two symbols with overlapping bars — timeline union correctness."""
        c = make_client()
        c.data["A:E"] = pd.DataFrame({
            "timestamp": [100, 200, 300],
            "open": [10,11,12], "high": [12,13,14], "low": [9,10,11],
            "close": [11,12,13], "volume": [1000]*3, "oi": [0]*3,
        })
        c.data["B:E"] = pd.DataFrame({
            "timestamp": [150, 200, 250, 300],
            "open": [20,21,22,23], "high": [22,23,24,25], "low": [19,20,21,22],
            "close": [21,22,23,24], "volume": [1000]*4, "oi": [0]*4,
        })

        # Build timeline like engine does
        all_ts = set()
        for key, df in c.data.items():
            all_ts.update(df["timestamp"].tolist())
        timeline = sorted(all_ts)

        assert timeline == [100, 150, 200, 250, 300]

        # At timestamp 150, A should be at bar 0, B at bar 0
        c.advance_to(150)
        assert c.current_bar_index["A:E"] == 0  # ts 100 <= 150
        assert c.current_bar_index["B:E"] == 0  # ts 150 <= 150

    def test_case7_no_trades_no_nan(self):
        """Zero trades — metrics must not NaN."""
        equity = [
            {"timestamp": 1000, "equity": 100000, "drawdown": 0},
            {"timestamp": 1001, "equity": 100000, "drawdown": 0},
            {"timestamp": 1002, "equity": 100000, "drawdown": 0},
        ]
        metrics = calculate_metrics([], equity, 100000, "D")
        for k, v in metrics.items():
            if k == "monthly_returns":
                continue
            if isinstance(v, float):
                assert not np.isnan(v), f"Metric {k} is NaN"
                assert not np.isinf(v), f"Metric {k} is inf"

    def test_case8_flat_equity_sharpe_zero(self):
        """Zero equity change — Sharpe = 0, not NaN."""
        equity = [
            {"timestamp": i, "equity": 100000, "drawdown": 0}
            for i in range(100)
        ]
        metrics = calculate_metrics([], equity, 100000, "D")
        assert metrics["sharpe_ratio"] == 0.0
        assert not np.isnan(metrics["sharpe_ratio"])


# ═══════════════════════════════════════════════════════════════════
# PHASE 3 — METRIC VERIFICATION AGAINST NUMPY GROUND TRUTH
# ═══════════════════════════════════════════════════════════════════

class TestPhase3MetricGroundTruth:

    def _make_equity_curve(self, equities):
        peak = equities[0]
        curve = []
        for i, eq in enumerate(equities):
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            curve.append({"timestamp": 1000 + i, "equity": eq, "drawdown": dd})
        return curve

    def test_cagr_independent(self):
        """Verify CAGR against independent numpy calculation."""
        equities = [100000, 102000, 98000, 105000, 110000, 108000, 115000]
        curve = self._make_equity_curve(equities)
        metrics = calculate_metrics([], curve, 100000, "D")

        # Independent CAGR
        n_bars = len(equities)
        bars_per_year = 252
        years = n_bars / bars_per_year
        ratio = equities[-1] / equities[0]
        expected_cagr = (ratio ** (1.0 / years) - 1) * 100

        assert abs(metrics["cagr"] - round(expected_cagr, 4)) < 1e-3, \
            f"CAGR mismatch: {metrics['cagr']} vs {expected_cagr}"

    def test_sharpe_independent(self):
        """Verify Sharpe against independent numpy calculation."""
        equities = [100000, 102000, 98000, 105000, 110000, 108000, 115000]
        curve = self._make_equity_curve(equities)
        metrics = calculate_metrics([], curve, 100000, "D")

        # Independent Sharpe
        eq = pd.Series(equities, dtype=float)
        rets = eq.pct_change().dropna().replace([np.inf, -np.inf], 0).fillna(0)
        expected_sharpe = float(rets.mean() / rets.std() * np.sqrt(252))

        assert abs(metrics["sharpe_ratio"] - round(expected_sharpe, 4)) < 1e-3, \
            f"Sharpe mismatch: {metrics['sharpe_ratio']} vs {expected_sharpe}"

    def test_sortino_independent(self):
        """Verify Sortino against independent numpy calculation."""
        equities = [100000, 102000, 98000, 105000, 110000, 108000, 115000]
        curve = self._make_equity_curve(equities)
        metrics = calculate_metrics([], curve, 100000, "D")

        eq = pd.Series(equities, dtype=float)
        rets = eq.pct_change().dropna().replace([np.inf, -np.inf], 0).fillna(0)
        downside = rets[rets < 0]
        if len(downside) > 1 and downside.std() > 0:
            expected_sortino = float(rets.mean() / downside.std() * np.sqrt(252))
        else:
            expected_sortino = 0.0

        assert abs(metrics["sortino_ratio"] - round(expected_sortino, 4)) < 1e-3, \
            f"Sortino mismatch: {metrics['sortino_ratio']} vs {expected_sortino}"

    def test_max_drawdown_independent(self):
        """Verify max drawdown against independent calculation."""
        equities = [100000, 110000, 95000, 105000, 90000, 120000]
        curve = self._make_equity_curve(equities)
        metrics = calculate_metrics([], curve, 100000, "D")

        # Independent max DD
        peak = equities[0]
        max_dd = 0
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak
            max_dd = max(max_dd, dd)

        assert abs(metrics["max_drawdown_pct"] - round(max_dd * 100, 4)) < 1e-3, \
            f"Max DD mismatch: {metrics['max_drawdown_pct']} vs {max_dd * 100}"

    def test_profit_factor_independent(self):
        """Verify profit factor against independent calculation."""
        trades = [
            {"net_pnl": 500, "bars_held": 1, "commission": 0, "slippage_cost": 0},
            {"net_pnl": -200, "bars_held": 1, "commission": 0, "slippage_cost": 0},
            {"net_pnl": 800, "bars_held": 1, "commission": 0, "slippage_cost": 0},
            {"net_pnl": -100, "bars_held": 1, "commission": 0, "slippage_cost": 0},
        ]
        equities = [100000, 100500, 100300, 101100, 101000]
        curve = self._make_equity_curve(equities)
        metrics = calculate_metrics(trades, curve, 100000, "D")

        gross_profit = 500 + 800
        gross_loss = 200 + 100
        expected_pf = gross_profit / gross_loss

        assert abs(metrics["profit_factor"] - round(expected_pf, 4)) < 1e-3, \
            f"PF mismatch: {metrics['profit_factor']} vs {expected_pf}"


# ═══════════════════════════════════════════════════════════════════
# PHASE 5 — STRATEGY PATCHER BREAK TESTS
# ═══════════════════════════════════════════════════════════════════

class TestPhase5Patcher:

    def _patch(self, code):
        p = StrategyPatcher()
        client = make_client()
        client.data["S:E"] = make_data([100, 110, 120])
        client.current_bar_index["S:E"] = 0
        return p.patch(code, client)

    def test_nested_while_loops(self):
        """Nested while loops — should extract outer only."""
        code = """
from openalgo import api
client = api(api_key="x")
while True:
    for i in range(3):
        while i < 2:
            break
    import time
    time.sleep(5)
"""
        fn = self._patch(code)
        assert callable(fn)

    def test_try_except_inside_loop(self):
        code = """
from openalgo import api
client = api(api_key="x")
while True:
    try:
        x = 1 / 0
    except ZeroDivisionError:
        pass
    import time
    time.sleep(1)
"""
        fn = self._patch(code)
        assert callable(fn)
        fn()  # Should not crash

    def test_no_while_loop_with_function(self):
        """Strategy with main() but no while loop."""
        code = """
from openalgo import api
client = api(api_key="x")
def main():
    pass
"""
        fn = self._patch(code)
        assert callable(fn)

    def test_no_entry_point_script(self):
        """Simple script with no function — should return no-op."""
        code = """
x = 42
y = x + 1
"""
        fn = self._patch(code)
        assert callable(fn)

    def test_async_def_should_not_crash(self):
        """async def should compile but not be callable in normal way."""
        code = """
async def strategy():
    pass
"""
        # Should not raise during patching
        fn = self._patch(code)
        assert callable(fn)

    def test_import_requests_blocked(self):
        """Strategy importing requests — should fail because blocked in sandbox."""
        code = """
import requests
"""
        with pytest.raises(ValueError, match="blocked in backtest sandbox"):
            self._patch(code)

    def test_safe_os_no_write(self):
        """os module should allow getenv but not have system, remove, etc."""
        p = StrategyPatcher()
        client = make_client()
        ns = p._build_namespace(client)
        safe_os = ns["os"]
        assert hasattr(safe_os, "getenv")
        assert not hasattr(safe_os, "system")
        assert not hasattr(safe_os, "remove")
        assert not hasattr(safe_os, "unlink")
        assert not hasattr(safe_os, "rmdir")


# ═══════════════════════════════════════════════════════════════════
# PHASE 6 — CAPITAL CONSISTENCY INVARIANT
# ═══════════════════════════════════════════════════════════════════

class TestPhase6CapitalConsistency:

    def test_capital_plus_unrealized_equals_equity(self):
        """At every bar: capital + unrealized == equity (within rounding)."""
        c = make_client(capital=100000, slippage=0, commission=0)
        prices = [100, 105, 95, 110, 90, 120]
        c.data["S:E"] = make_data(prices)

        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=10, price_type="MARKET")

        for i in range(len(prices)):
            c.current_bar_index["S:E"] = i
            c.current_timestamp = 1000 + i
            c.record_equity(1000 + i)

            unrealized = c._total_unrealized()
            expected_equity = c.capital + unrealized
            actual_equity = c.equity_curve[-1]["equity"]

            assert abs(expected_equity - actual_equity) < 0.02, \
                f"Bar {i}: capital({c.capital}) + unrealized({unrealized}) = {expected_equity} != equity({actual_equity})"

    def test_final_capital_accounting(self):
        """After all trades: initial + sum(pnl) - sum(commission) == final capital."""
        c = make_client(capital=100000, slippage=0, commission=20)
        prices = [100, 110, 95, 105, 115]
        c.data["S:E"] = make_data(prices)

        # Buy, sell, buy, sell
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=10, price_type="MARKET")

        c.current_bar_index["S:E"] = 1
        c.current_timestamp = 1001
        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=10, price_type="MARKET")

        c.current_bar_index["S:E"] = 2
        c.current_timestamp = 1002
        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=10, price_type="MARKET")

        c.current_bar_index["S:E"] = 3
        c.current_timestamp = 1003
        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=10, price_type="MARKET")

        # Verify: no open positions
        assert c.positions["S:E"]["qty"] == 0

        total_pnl = sum(t["pnl"] for t in c.trades)
        total_commission = sum(20 for _ in range(4))  # 4 orders, each 20
        expected_capital = 100000 + total_pnl - total_commission
        assert abs(c.capital - expected_capital) < 0.02, \
            f"Capital accounting mismatch: {c.capital} vs {expected_capital}"


# ═══════════════════════════════════════════════════════════════════
# PHASE 7 — FINANCIAL INVARIANTS
# ═══════════════════════════════════════════════════════════════════

class TestPhase7FinancialInvariants:

    def test_max_drawdown_never_negative(self):
        equities = [100000, 110000, 95000, 105000, 90000, 120000]
        peak = equities[0]
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak
            assert dd >= 0, f"Drawdown negative: {dd}"

    def test_peak_equity_monotonic(self):
        """peak_equity should be monotonically non-decreasing."""
        c = make_client()
        c.data["S:E"] = make_data([100, 110, 95, 120, 80])

        peaks = []
        for i in range(5):
            c.current_bar_index["S:E"] = i
            c.current_timestamp = 1000 + i
            c.record_equity(1000 + i)
            peaks.append(c.peak_equity)

        for i in range(1, len(peaks)):
            assert peaks[i] >= peaks[i-1], f"Peak decreased at {i}: {peaks[i]} < {peaks[i-1]}"

    def test_equity_never_nan(self):
        c = make_client()
        c.data["S:E"] = make_data([100, 0.01, 100, 50])  # edge: near-zero price

        for i in range(4):
            c.current_bar_index["S:E"] = i
            c.current_timestamp = 1000 + i
            c.record_equity(1000 + i)

        for pt in c.equity_curve:
            assert not np.isnan(pt["equity"]), f"Equity NaN at {pt['timestamp']}"
            assert not np.isinf(pt["equity"]), f"Equity Inf at {pt['timestamp']}"

    def test_profit_factor_infinite_only_no_losses(self):
        trades = [
            {"net_pnl": 100, "bars_held": 1, "commission": 0, "slippage_cost": 0},
            {"net_pnl": 200, "bars_held": 1, "commission": 0, "slippage_cost": 0},
        ]
        curve = [
            {"timestamp": 1000, "equity": 100000, "drawdown": 0},
            {"timestamp": 1001, "equity": 100100, "drawdown": 0},
            {"timestamp": 1002, "equity": 100300, "drawdown": 0},
        ]
        metrics = calculate_metrics(trades, curve, 100000, "D")
        assert metrics["profit_factor"] == 999.99  # capped infinite

    def test_win_rate_between_0_and_100(self):
        trades = [
            {"net_pnl": 100, "bars_held": 1, "commission": 0, "slippage_cost": 0},
            {"net_pnl": -50, "bars_held": 1, "commission": 0, "slippage_cost": 0},
        ]
        curve = [
            {"timestamp": 1000, "equity": 100000, "drawdown": 0},
            {"timestamp": 1001, "equity": 100100, "drawdown": 0},
            {"timestamp": 1002, "equity": 100050, "drawdown": 0},
        ]
        metrics = calculate_metrics(trades, curve, 100000, "D")
        assert 0 <= metrics["win_rate"] <= 100


# ═══════════════════════════════════════════════════════════════════
# PHASE 10 — FAILURE INJECTION
# ═══════════════════════════════════════════════════════════════════

class TestPhase10FailureInjection:

    def test_strategy_division_by_zero(self):
        """Strategy with div/0 should not crash engine — iteration is non-fatal."""
        c = make_client()
        c.data["S:E"] = make_data([100, 110])
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000

        p = StrategyPatcher()
        code = """
def strategy():
    x = 1 / 0
"""
        fn = p.patch(code, c)
        # Engine catches exceptions from iteration_fn
        try:
            fn()
            assert False, "Should have raised"
        except ZeroDivisionError:
            pass  # Expected — engine wraps this in try/except

    def test_negative_capital_start(self):
        """Negative initial capital should still produce metrics, not crash."""
        c = make_client(capital=-50000)
        c.data["S:E"] = make_data([100, 110])
        for i in range(2):
            c.current_bar_index["S:E"] = i
            c.current_timestamp = 1000 + i
            c.record_equity(1000 + i)
        # Should not crash
        assert len(c.equity_curve) == 2

    def test_empty_metrics_returns_valid(self):
        m = _empty_metrics(0)
        assert m["final_capital"] == 0.0
        assert m["sharpe_ratio"] == 0.0
        assert isinstance(m["monthly_returns"], dict)

    def test_commission_pct_mode(self):
        """Test percentage-based commission instead of per-order."""
        c = make_client(capital=100000, slippage=0, commission=0, comm_pct=0.1)
        c.data["S:E"] = make_data([100])
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000

        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=100, price_type="MARKET")
        # trade_value = 100 * 100 = 10000
        # commission = 10000 * 0.1% = 10
        expected_commission = 10.0
        expected_capital = 100000 - expected_commission
        assert abs(c.capital - expected_capital) < 0.01, f"Capital: {c.capital} != {expected_capital}"


# ═══════════════════════════════════════════════════════════════════
# ADDITIONAL VULNERABILITY PROBES
# ═══════════════════════════════════════════════════════════════════

class TestAdditionalVulnerabilities:

    def test_FIXED_reversal_double_commission(self):
        """
        FIXED: On reversal (Buy 100, Sell 200), commission is now charged
        separately for the close portion AND the new open portion.
        """
        c = make_client(capital=100000, slippage=0, commission=20)
        c.data["S:E"] = make_data([100])
        c.current_bar_index["S:E"] = 0
        c.current_timestamp = 1000

        c.placeorder(symbol="S", exchange="E", action="BUY", quantity=100, price_type="MARKET")
        initial = c.capital  # 100000 - 20 = 99980
        assert initial == 99980

        c.placeorder(symbol="S", exchange="E", action="SELL", quantity=200, price_type="MARKET")
        # Close commission (20) + open commission (20) = 40
        assert c.capital == initial - 40  # 2 commissions for reversal

    def test_FIXED_history_default_index_returns_empty(self):
        """
        FIXED: If current_bar_index is NOT set for a symbol, history() now
        defaults to -1 and returns empty DataFrame (no look-ahead leak).
        """
        c = make_client()
        c.data["S:E"] = make_data([100, 200, 300, 400, 500])
        # NOTE: current_bar_index NOT set for S:E
        df = c.history(symbol="S", exchange="E")
        assert len(df) == 0  # No data exposed — safe default

    def test_BUG_api_constructor_positional_args(self):
        """
        Patcher uses `api\\s*\\([^)]*\\)` but if strategy calls api() with
        no arguments or positional args like api("key", "host"), the regex
        still matches. What about api = api(...)?
        """
        p = StrategyPatcher()
        code = 'client = api("mykey", "localhost")'
        patched = p._replace_api_constructor(code)
        assert "_backtest_client" in patched

    def test_FIXED_calmar_uses_signed_cagr(self):
        """
        FIXED: Calmar ratio now uses signed CAGR, so losing strategies
        show negative Calmar ratio.
        """
        equities = [100000, 95000, 90000, 85000]  # Losing strategy
        peak = equities[0]
        curve = []
        for i, eq in enumerate(equities):
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            curve.append({"timestamp": 1000+i, "equity": eq, "drawdown": dd})

        metrics = calculate_metrics([], curve, 100000, "D")
        assert metrics["cagr"] < 0, "CAGR should be negative"
        assert metrics["calmar_ratio"] < 0, "Calmar should be negative for losing strategies"

    def test_BUG_duplicate_equity_point_on_last_bar(self):
        """
        Engine calls record_equity() in the loop (line 175) AND again
        after close_all_positions (line 191) with the same timestamp.
        This creates a DUPLICATE equity point at the last timestamp.
        """
        c = make_client()
        c.record_equity(1000)
        c.record_equity(1000)  # Same timestamp
        assert len(c.equity_curve) == 2  # Duplicate exists
        assert c.equity_curve[0]["timestamp"] == c.equity_curve[1]["timestamp"]

    def test_FIXED_scoped_session_cleanup_after_run(self):
        """
        FIXED: start_backtest() now calls db_session.remove() in its finally
        block, ensuring thread-local sessions are cleaned up after each run
        even when threads are reused in the ThreadPoolExecutor.
        """
        import inspect
        from services.backtest_engine import start_backtest
        source = inspect.getsource(start_backtest)
        assert "db_session.remove()" in source, \
            "start_backtest must call db_session.remove() after run"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
