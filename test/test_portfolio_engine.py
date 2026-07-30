"""
Portfolio backtester: data loading, rebalancing policy and the engine.

The engine cases are chosen so a plausible-but-wrong implementation fails:
weights that drift, turnover that is one-way, costs that apply to traded value
rather than to the whole portfolio, and a cost drag that is zero when nothing
trades.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfolio.data import (
    DataError,
    MissingHistory,
    PriceMatrix,
    UnsupportedExchange,
    _frame_from_payload,
    _normalise_exchange,
    split_artifacts,
)
from portfolio.engine import Costs, normalise_weights, run_backtest
from portfolio.rebalance import RebalancePolicy, calendar_dates, drifted


def matrix(data: dict[str, list[float]], start: str = "2024-01-01") -> PriceMatrix:
    index = pd.bdate_range(start, periods=len(next(iter(data.values()))))
    closes = pd.DataFrame(data, index=index)
    return PriceMatrix(
        closes=closes, source="db", start=index[0].date(), end=index[-1].date()
    )


class TestExchangeGate:
    def test_accepts_the_supported_cash_exchanges(self):
        assert _normalise_exchange("nse") == "NSE"
        assert _normalise_exchange(" BSE ") == "BSE"

    @pytest.mark.parametrize("ex", ["NFO", "MCX", "CDS", "", "NASDAQ"])
    def test_rejects_everything_else(self, ex):
        with pytest.raises(UnsupportedExchange):
            _normalise_exchange(ex)


class TestPayloadParsing:
    def test_reads_epoch_seconds(self):
        payload = [
            {"timestamp": 1704067200, "close": 100.0},
            {"timestamp": 1704153600, "close": 101.0},
        ]
        frame = _frame_from_payload(payload, "X")
        assert list(frame["close"]) == [100.0, 101.0]
        # Epoch must not be read as nanoseconds and land in 1970.
        assert frame.index[0].year == 2024

    def test_reads_iso_strings_and_string_numerics(self):
        payload = {"data": [{"date": "2024-01-01", "close": "100.5"}]}
        frame = _frame_from_payload(payload, "X")
        assert frame["close"].iloc[0] == pytest.approx(100.5)

    def test_last_write_wins_for_a_duplicated_session(self):
        payload = [
            {"date": "2024-01-01", "close": 100.0},
            {"date": "2024-01-01", "close": 111.0},
        ]
        frame = _frame_from_payload(payload, "X")
        assert len(frame) == 1
        assert frame["close"].iloc[0] == 111.0

    def test_empty_and_malformed_payloads_raise(self):
        with pytest.raises(MissingHistory):
            _frame_from_payload([], "X")
        with pytest.raises(MissingHistory):
            _frame_from_payload([{"open": 1}], "X")


class TestWeights:
    def test_percentages_are_normalised(self):
        w = normalise_weights({"A": 40.0, "B": 60.0}, ["A", "B"])
        assert w.sum() == pytest.approx(1.0)
        assert w[0] == pytest.approx(0.4)

    def test_order_follows_symbols_not_the_dict(self):
        w = normalise_weights({"B": 60.0, "A": 40.0}, ["A", "B"])
        assert w[0] == pytest.approx(0.4)

    def test_missing_extra_and_negative_weights_raise(self):
        with pytest.raises(ValueError, match="no weight given"):
            normalise_weights({"A": 1.0}, ["A", "B"])
        with pytest.raises(ValueError, match="unheld"):
            normalise_weights({"A": 1.0, "Z": 1.0}, ["A"])
        with pytest.raises(ValueError, match="long-only"):
            normalise_weights({"A": -1.0, "B": 2.0}, ["A", "B"])


class TestRebalancePolicy:
    def test_rejects_unknown_rules_and_out_of_range_bands(self):
        with pytest.raises(ValueError, match="unknown rebalance rule"):
            RebalancePolicy(rule="fortnightly")
        with pytest.raises(ValueError, match="fraction"):
            RebalancePolicy(drift_band=5.0)

    def test_buy_and_hold_only_when_nothing_can_trigger(self):
        assert RebalancePolicy().is_buy_and_hold
        assert not RebalancePolicy(rule="monthly").is_buy_and_hold
        assert not RebalancePolicy(drift_band=0.05).is_buy_and_hold

    def test_calendar_lands_on_real_sessions(self):
        index = pd.bdate_range("2024-01-01", "2024-03-29")
        dates = calendar_dates(index, "monthly")
        assert all(d in index for d in dates)
        # Jan and Feb ends; the final period end is included, the first
        # session is not (that is the purchase, not a rebalance).
        assert index[0] not in dates

    def test_never_yields_no_dates(self):
        index = pd.bdate_range("2024-01-01", periods=100)
        assert len(calendar_dates(index, "never")) == 0

    def test_drift_is_absolute_points_not_relative(self):
        target = np.array([0.5, 0.5])
        # 2 points of drift: under a relative test 0.52/0.5 = 4% would trip a
        # 5% band differently. Absolute is what we promise.
        assert not drifted(np.array([0.52, 0.48]), target, 0.05)
        assert drifted(np.array([0.56, 0.44]), target, 0.05)
        assert not drifted(np.array([0.9, 0.1]), target, 0.0)


class TestEngine:
    def test_buy_and_hold_compounds_the_weighted_assets(self):
        # A doubles, B flat. 50/50 buy and hold -> 1.5x.
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(prices, {"A": 50, "B": 50}, initial_capital=1000.0)
        assert r.equity.iloc[-1] == pytest.approx(1500.0)
        assert r.total_return == pytest.approx(0.5)

    def test_weights_drift_when_never_rebalancing(self):
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(prices, {"A": 50, "B": 50})
        # A doubled, so it is now two thirds of the portfolio.
        assert r.weights.iloc[-1]["A"] == pytest.approx(2 / 3)
        assert len(r.rebalance_dates) == 0

    def test_buy_and_hold_never_trades_so_costs_cannot_bite(self):
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(
            prices, {"A": 50, "B": 50}, costs=Costs(bps=100, slippage=0.01)
        )
        assert r.cost_drag == pytest.approx(0.0)
        assert r.turnover.empty

    def test_rebalancing_resets_weights_to_target(self):
        prices = matrix(
            {"A": [100.0] * 21 + [200.0], "B": [100.0] * 22}, start="2024-01-01"
        )
        r = run_backtest(prices, {"A": 50, "B": 50}, policy=RebalancePolicy("monthly"))
        assert len(r.rebalance_dates) >= 1
        assert r.weights.iloc[-1]["A"] == pytest.approx(0.5)

    def test_turnover_is_one_way_and_costs_scale_with_it(self):
        # A doubles on the last session, which is a month end, so the
        # rebalance sells a quarter of the book and buys the other side:
        # |2/3 - 1/2| + |1/3 - 1/2| = 1/3, one-way = 1/6.
        prices = matrix({"A": [100.0] * 21 + [200.0], "B": [100.0] * 22})
        free = run_backtest(prices, {"A": 50, "B": 50}, policy=RebalancePolicy("monthly"))
        assert free.turnover.iloc[-1] == pytest.approx(1 / 6, rel=1e-3)

        # 100 bps + 1% slippage = 2% of traded value.
        paid = run_backtest(
            prices,
            {"A": 50, "B": 50},
            policy=RebalancePolicy("monthly"),
            costs=Costs(bps=100, slippage=0.01),
        )
        assert paid.equity.iloc[-1] < free.equity.iloc[-1]
        # Charged on the traded sixth, not on the whole portfolio.
        assert paid.equity.iloc[-1] == pytest.approx(
            free.equity.iloc[-1] * (1 - (1 / 6) * 0.02), rel=1e-6
        )

    def test_cost_drag_reports_the_return_costs_consumed(self):
        prices = matrix({"A": [100.0] * 21 + [200.0], "B": [100.0] * 22})
        r = run_backtest(
            prices,
            {"A": 50, "B": 50},
            policy=RebalancePolicy("monthly"),
            costs=Costs(bps=100, slippage=0.01),
        )
        assert r.cost_drag > 0
        free = run_backtest(prices, {"A": 50, "B": 50}, policy=RebalancePolicy("monthly"))
        assert r.cost_drag == pytest.approx(free.total_return - r.total_return, rel=1e-6)

    def test_drift_band_can_trigger_without_a_calendar(self):
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(
            prices, {"A": 50, "B": 50}, policy=RebalancePolicy("never", drift_band=0.05)
        )
        assert len(r.rebalance_dates) == 1
        assert r.weights.iloc[-1]["A"] == pytest.approx(0.5)

    def test_a_flat_market_returns_capital_untouched(self):
        prices = matrix({"A": [100.0] * 30, "B": [50.0] * 30})
        r = run_backtest(
            prices,
            {"A": 30, "B": 70},
            policy=RebalancePolicy("monthly"),
            costs=Costs(bps=50),
            initial_capital=1234.0,
        )
        assert r.equity.iloc[-1] == pytest.approx(1234.0)
        # Nothing drifted, so nothing traded, so nothing was charged.
        assert r.cost_drag == pytest.approx(0.0)

    def test_returns_drop_the_first_row_rather_than_zero_filling(self):
        prices = matrix({"A": [100.0, 110.0, 121.0]})
        r = run_backtest(prices, {"A": 100})
        assert len(r.returns) == 2
        assert r.returns.iloc[0] == pytest.approx(0.1)

    def test_result_records_which_source_produced_it(self):
        prices = matrix({"A": [100.0, 101.0]})
        r = run_backtest(prices, {"A": 100})
        assert r.source == "db"
        assert r.meta["rule"] == "never"


class TestPriceMatrix:
    def test_returns_have_no_leading_zero(self):
        prices = matrix({"A": [100.0, 110.0]})
        assert len(prices.returns()) == 1

    def test_reports_its_shape(self):
        prices = matrix({"A": [1.0, 2.0], "B": [3.0, 4.0]})
        assert prices.symbols == ["A", "B"]
        assert prices.sessions == 2


class TestCorporateActionGuard:
    """
    Broker feeds arrive already adjusted, so the engine does not adjust.
    What it must not do is stay silent when a series clearly was not — a
    stored history that missed a split has a step in it that is
    indistinguishable downstream from a real -50% session.
    """

    def test_clean_data_raises_no_warning(self):
        closes = pd.DataFrame(
            {"A": [100.0, 102.0, 99.0, 105.0], "B": [50.0, 51.0, 49.0, 52.0]},
            index=pd.bdate_range("2024-01-01", periods=4),
        )
        assert split_artifacts(closes) == {}

    def test_an_unadjusted_1_for_2_split_is_flagged(self):
        closes = pd.DataFrame(
            {"A": [100.0, 101.0, 50.5, 51.0]},
            index=pd.bdate_range("2024-01-01", periods=4),
        )
        found = split_artifacts(closes)
        assert "A" in found
        assert found["A"][0][1] < -0.4

    def test_a_hard_but_real_session_is_not_flagged(self):
        # A 20% circuit is the practical single-session ceiling; it must pass.
        closes = pd.DataFrame(
            {"A": [100.0, 80.0, 96.0]},
            index=pd.bdate_range("2024-01-01", periods=3),
        )
        assert split_artifacts(closes) == {}

    def test_a_bonus_issue_upward_step_is_flagged_too(self):
        closes = pd.DataFrame(
            {"A": [50.0, 51.0, 153.0]},
            index=pd.bdate_range("2024-01-01", periods=3),
        )
        assert "A" in split_artifacts(closes)

    def test_the_matrix_carries_warnings_so_a_run_can_surface_them(self):
        clean = matrix({"A": [100.0, 101.0]})
        assert clean.warnings == {}
