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
from portfolio.analytics import (
    average_pairwise_correlation,
    capture_ratios,
    concentration,
    correlation_matrix,
    diversification_ratio,
    summary,
)
from portfolio.compare import rebalancing_sweep
from portfolio.costs import EquityCosts, schedule_for
from portfolio.engine import Costs, normalise_weights, run_backtest
from portfolio.health import portfolio_health
from portfolio.holdings import holdings_summary, parse_holdings
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


class TestItemisedPnl:
    """
    Per-symbol P&L has to be an attribution, not a list of performances: the
    contributions must sum to the portfolio's own return, which is exactly what
    a naive weight x symbol-return table fails to do once weights drift.
    """

    def test_contributions_sum_to_the_portfolio_return(self):
        prices = matrix({"A": [100.0, 130.0], "B": [100.0, 90.0]})
        r = run_backtest(prices, {"A": 50, "B": 50}, initial_capital=1000.0)
        assert r.items["contribution_pct"].sum() == pytest.approx(r.total_return)

    def test_it_reports_currency_made_per_holding(self):
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(prices, {"A": 50, "B": 50}, initial_capital=1000.0)
        # 500 into A which doubled -> +500; B flat -> 0.
        assert r.items.loc["A", "net_pnl"] == pytest.approx(500.0)
        assert r.items.loc["B", "net_pnl"] == pytest.approx(0.0)

    def test_symbol_return_is_distinct_from_contribution(self):
        prices = matrix({"A": [100.0, 200.0], "B": [100.0, 100.0]})
        r = run_backtest(prices, {"A": 50, "B": 50})
        # A doubled on its own, but contributed half of that to the portfolio.
        assert r.items.loc["A", "symbol_return"] == pytest.approx(1.0)
        assert r.items.loc["A", "contribution_pct"] == pytest.approx(0.5)

    def test_contributions_still_reconcile_under_rebalancing_and_costs(self):
        prices = matrix({"A": [100.0] * 21 + [200.0], "B": [100.0] * 22})
        r = run_backtest(
            prices,
            {"A": 50, "B": 50},
            policy=RebalancePolicy("monthly"),
            costs=Costs(bps=100, slippage=0.01),
            initial_capital=5000.0,
        )
        assert r.items["contribution_pct"].sum() == pytest.approx(r.total_return)
        # Costs were charged, and to the holdings that actually traded.
        assert r.items["costs"].sum() > 0

    def test_a_loser_carries_a_negative_contribution(self):
        prices = matrix({"A": [100.0, 50.0], "B": [100.0, 100.0]})
        r = run_backtest(prices, {"A": 50, "B": 50}, initial_capital=1000.0)
        assert r.items.loc["A", "net_pnl"] == pytest.approx(-250.0)
        assert r.items.loc["A", "contribution_pct"] < 0


class TestAnalytics:
    def _returns(self, n: int = 260, seed: int = 7) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        index = pd.bdate_range("2023-01-02", periods=n)
        base = rng.normal(0.0004, 0.01, n)
        return pd.DataFrame(
            {
                "A": base + rng.normal(0, 0.002, n),   # nearly identical to B
                "B": base + rng.normal(0, 0.002, n),
                "C": rng.normal(0.0004, 0.01, n),      # independent
            },
            index=index,
        )

    def test_correlation_matrix_is_square_and_unit_diagonal(self):
        corr = correlation_matrix(self._returns())
        assert corr.shape == (3, 3)
        assert np.allclose(np.diag(corr), 1.0)

    def test_thin_overlap_is_nan_rather_than_a_confident_number(self):
        r = self._returns(n=5)
        corr = correlation_matrix(r, min_overlap=20)
        assert corr.isna().to_numpy().any()

    def test_average_pairwise_correlation_sees_through_names(self):
        avg = average_pairwise_correlation(self._returns())
        # A and B share a driver, C does not: the mean must land between.
        assert 0.0 < avg < 1.0

    def test_average_correlation_undefined_for_a_single_holding(self):
        one = self._returns()[["A"]]
        assert np.isnan(average_pairwise_correlation(one))

    def test_concentration_reports_effective_holdings(self):
        even = concentration({"A": 25, "B": 25, "C": 25, "D": 25})
        assert even["effective_holdings"] == pytest.approx(4.0)
        # Twenty names but one dominates: nowhere near twenty real bets.
        lopsided = concentration({"A": 80, **{f"S{i}": 20 / 19 for i in range(19)}})
        assert lopsided["holdings"] == 20
        assert lopsided["effective_holdings"] < 2.0

    def test_concentration_rejects_empty_weights(self):
        with pytest.raises(ValueError):
            concentration({"A": 0.0})

    def test_diversification_ratio_is_higher_for_uncorrelated_holdings(self):
        r = self._returns()
        w = pd.Series({"A": 0.5, "B": 0.5, "C": 0.5})
        twins = diversification_ratio(w[["A", "B"]], r[["A", "B"]])
        mixed = diversification_ratio(w[["A", "C"]], r[["A", "C"]])
        assert mixed > twins

    def test_capture_ratios_split_up_and_down_markets(self):
        index = pd.bdate_range("2024-01-01", periods=6)
        bench = pd.Series([0.02, -0.02, 0.02, -0.02, 0.01, -0.01], index=index)
        # Takes all the upside, half the downside.
        port = pd.Series([0.02, -0.01, 0.02, -0.01, 0.01, -0.005], index=index)
        caps = capture_ratios(port, bench)
        assert caps["up_capture"] == pytest.approx(1.0, rel=0.02)
        assert caps["down_capture"] < 0.6

    def test_capture_is_nan_when_a_regime_never_occurred(self):
        index = pd.bdate_range("2024-01-01", periods=3)
        bench = pd.Series([0.01, 0.02, 0.01], index=index)  # never fell
        caps = capture_ratios(pd.Series([0.01, 0.01, 0.01], index=index), bench)
        assert np.isnan(caps["down_capture"])

    def test_summary_covers_the_headline_metrics(self):
        r = self._returns()["A"]
        out = summary(r)
        for key in ("cagr", "volatility", "sharpe", "sortino", "max_drawdown", "cvar"):
            assert key in out and np.isfinite(out[key])
        # No benchmark supplied, so relative figures are absent, not faked.
        assert "beta" not in out

    def test_summary_adds_relative_metrics_with_a_benchmark(self):
        r = self._returns()
        out = summary(r["A"], r["C"])
        for key in ("alpha", "beta", "information_ratio", "up_capture", "excess_cagr"):
            assert key in out


class TestCostDragExactness:
    def test_buy_and_hold_drag_is_exactly_zero(self):
        # Reconstructing the gross path from weights left rounding error, so
        # a run that never traded reported a tiny non-zero drag.
        prices = matrix({"A": [100.0, 137.0, 92.0, 118.0], "B": [55.0, 51.0, 63.0, 60.0]})
        r = run_backtest(
            prices, {"A": 35, "B": 65}, costs=Costs(bps=250, slippage=0.02)
        )
        assert r.cost_drag == 0.0

    def test_drag_equals_the_gap_to_an_uncharged_run(self):
        prices = matrix({"A": [100.0] * 21 + [180.0], "B": [100.0] * 22})
        kw = dict(policy=RebalancePolicy("monthly"), initial_capital=10_000.0)
        free = run_backtest(prices, {"A": 50, "B": 50}, **kw)
        paid = run_backtest(prices, {"A": 50, "B": 50}, costs=Costs(bps=75), **kw)
        assert paid.cost_drag == pytest.approx(free.total_return - paid.total_return, abs=1e-12)


class TestCaptureRatioStability:
    """
    Capture must not depend on how long the window is. Compounding only the
    sessions that went one way diverges with length: over five years of real
    data the benchmark's up-days-only product reached five figures and every
    ratio against it collapsed to zero.
    """

    def _pair(self, n: int, seed: int = 3):
        rng = np.random.default_rng(seed)
        index = pd.bdate_range("2015-01-01", periods=n)
        bench = pd.Series(rng.normal(0.0005, 0.011, n), index=index)
        port = pd.Series(bench.to_numpy() * 0.8 + rng.normal(0, 0.002, n), index=index)
        return port, bench

    def test_capture_is_stable_as_the_window_grows(self):
        short = capture_ratios(*self._pair(120))
        long = capture_ratios(*self._pair(2500))
        assert short["up_capture"] == pytest.approx(long["up_capture"], abs=0.25)
        # A beta-0.8 portfolio should land near 0.8, not near 0.
        assert 0.5 < long["up_capture"] < 1.1
        assert long["up_capture"] > 0.01

    def test_a_full_capture_portfolio_reports_one(self):
        _, bench = self._pair(400)
        caps = capture_ratios(bench.copy(), bench)
        assert caps["up_capture"] == pytest.approx(1.0)
        assert caps["down_capture"] == pytest.approx(1.0)


class TestPortfolioHealth:
    """
    The grade must be arguable, not merely believable: every pillar publishes
    its inputs, its formula and the weight it actually carried.
    """

    def _kit(self, n=300, seed=11):
        rng = np.random.default_rng(seed)
        index = pd.bdate_range("2023-01-02", periods=n)
        closes = pd.DataFrame(
            {
                "A": 100 * np.cumprod(1 + rng.normal(0.0006, 0.01, n)),
                "B": 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, n)),
            },
            index=index,
        )
        return closes, closes.pct_change().iloc[1:], pd.Series({"A": 0.5, "B": 0.5})

    def _health(self, **over):
        closes, rets, w = self._kit()
        kw = dict(
            weights=w, returns=rets, closes=closes, sharpe=1.0, sortino=1.2,
            max_drawdown=-0.15, cost_drag=0.001, turnover=0.4,
        )
        kw.update(over)
        return portfolio_health(**kw)

    def test_every_pillar_shows_its_working(self):
        h = self._health()
        assert len(h["pillars"]) == 6
        for p in h["pillars"]:
            assert p["formula"] and isinstance(p["formula"], str)
            assert "inputs" in p and "effective_weight" in p
            assert p["comment"]

    def test_grade_tracks_the_score(self):
        good = self._health(sharpe=2.5, max_drawdown=-0.05, cost_drag=0.0)
        bad = self._health(sharpe=-0.5, max_drawdown=-0.55, cost_drag=0.08)
        assert good["score"] > bad["score"]
        assert good["grade"] < bad["grade"]  # 'A' sorts before 'F'

    def test_concentration_pillar_sees_through_holding_count(self):
        closes, rets, _ = self._kit()
        lopsided = pd.Series({"A": 0.97, "B": 0.03})
        even = pd.Series({"A": 0.5, "B": 0.5})
        base = dict(returns=rets, closes=closes, sharpe=1.0, sortino=1.2,
                    max_drawdown=-0.15, cost_drag=0.0, turnover=0.0)
        lo = portfolio_health(weights=lopsided, **base)
        ev = portfolio_health(weights=even, **base)
        pick = lambda h: next(p for p in h["pillars"] if p["key"] == "concentration")
        assert pick(lo)["score"] < pick(ev)["score"]

    def test_an_unmeasurable_pillar_is_dropped_not_scored_zero(self):
        # 300 sessions is short of the 200-day filter for a *dropna* series?
        # No -- force it: 50 sessions cannot have a 200-session average.
        closes, rets, w = self._kit(n=50)
        h = portfolio_health(
            weights=w, returns=rets, closes=closes, sharpe=1.0, sortino=1.2,
            max_drawdown=-0.15, cost_drag=0.0, turnover=0.0,
        )
        assert "trend" in h["unmeasured"]
        trend = next(p for p in h["pillars"] if p["key"] == "trend")
        assert trend["score"] is None
        assert trend["effective_weight"] == 0.0
        # The rest renormalise to a full weighting rather than being diluted.
        # Tolerance, not exactness: effective_weight is rounded for display, so
        # five pillars sum to 0.9999. Renormalisation is the property here.
        assert sum(p["effective_weight"] for p in h["pillars"]) == pytest.approx(1.0, abs=1e-3)

    def test_effective_weights_sum_to_one_when_all_measured(self):
        h = self._health()
        assert sum(p["effective_weight"] for p in h["pillars"]) == pytest.approx(1.0, abs=1e-3)

    def test_cost_drag_penalises_the_score(self):
        cheap = self._health(cost_drag=0.0)
        pricey = self._health(cost_drag=0.05)
        assert cheap["score"] > pricey["score"]

    def test_grade_boundaries(self):
        from portfolio.health import grade_for
        assert grade_for(95) == "A"
        assert grade_for(90) == "A"
        assert grade_for(89.9) == "B"
        assert grade_for(0) == "F"


class TestIndianEquityCosts:
    """
    Pinned against a public brokerage calculator: delivery equity, NSE, buy and
    sell 5,000 shares at 1,000 each -- turnover 1,00,00,000 -- costs 11,124.06.
    """

    def test_matches_the_published_calculator_line_by_line(self):
        c = EquityCosts(exchange="NSE")
        b = c.breakdown(buy_value=50_00_000, sell_value=50_00_000)
        assert b["brokerage"] == pytest.approx(0.0)
        assert b["stt"] == pytest.approx(10_000.0)
        assert b["exchange_txn"] == pytest.approx(307.0, abs=0.5)
        assert b["sebi"] == pytest.approx(10.0, abs=0.01)
        # Named `tax` in the generic schedule: a market may levy VAT or none.
        assert b["tax"] == pytest.approx(57.06, abs=0.1)
        assert b["stamp_duty"] == pytest.approx(750.0)
        assert b["total"] == pytest.approx(11_124.06, abs=0.5)

    def test_stamp_duty_is_charged_on_the_buy_leg_only(self):
        c = EquityCosts()
        buy_only = c.breakdown(1_00_000, 0)["stamp_duty"]
        sell_only = c.breakdown(0, 1_00_000)["stamp_duty"]
        assert buy_only > 0
        assert sell_only == 0
        # The asymmetry a flat bps rate cannot express.
        assert c.charge(1_00_000, 0) > c.charge(0, 1_00_000)

    def test_gst_applies_to_fees_not_to_taxes(self):
        c = EquityCosts()
        b = c.breakdown(50_00_000, 50_00_000)
        assert b["tax"] == pytest.approx((b["brokerage"] + b["exchange_txn"] + b["sebi"]) * 0.18)
        # If GST were charged on STT it would dwarf every other line.
        assert b["tax"] < b["stt"] / 100

    def test_bse_costs_more_to_transact_than_nse(self):
        nse = EquityCosts("NSE").charge(50_00_000, 50_00_000)
        bse = EquityCosts("BSE").charge(50_00_000, 50_00_000)
        assert bse > nse

    def test_stt_dominates_so_turnover_is_what_hurts(self):
        b = EquityCosts().breakdown(50_00_000, 50_00_000)
        assert b["stt"] / b["total"] > 0.85

    def test_effective_rate_is_about_11_bps_each_way(self):
        rate = EquityCosts().effective_rate(50_00_000, 50_00_000)
        assert rate == pytest.approx(0.001112, abs=1e-5)

    def test_no_trade_costs_nothing(self):
        assert EquityCosts().charge(0, 0) == pytest.approx(0.0)
        assert EquityCosts().effective_rate(0, 0) == 0.0


class TestGenericCostSchedule:
    """
    Charges are data, not code. The India preset must reproduce the published
    calculator exactly, and a different market must work through the same
    machinery -- otherwise "configurable" is just relocated hardcoding.
    """

    def test_india_preset_reproduces_the_calculator(self):
        b = schedule_for("india_delivery_nse").breakdown(50_00_000, 50_00_000, orders=0)
        assert b["stt"] == pytest.approx(10_000.0)
        assert b["exchange_txn"] == pytest.approx(307.0, abs=0.5)
        assert b["sebi"] == pytest.approx(10.0, abs=0.01)
        assert b["tax"] == pytest.approx(57.06, abs=0.1)
        assert b["stamp_duty"] == pytest.approx(750.0)
        assert b["total"] == pytest.approx(11_124.06, abs=0.5)

    def test_every_rate_is_overridable(self):
        # A budget changes STT: no release should be needed.
        s = schedule_for("india_delivery_nse", {"stt": {"rate": 0.00125}})
        assert s.breakdown(50_00_000, 50_00_000)["stt"] == pytest.approx(12_500.0)

    def test_flat_brokerage_scales_with_orders_not_value(self):
        s = schedule_for("india_delivery_nse", {"brokerage": {"flat": 20.0}})
        assert s.breakdown(1_00_000, 1_00_000, orders=4)["brokerage"] == pytest.approx(80.0)
        # Ten times the value, same order count, same brokerage.
        assert s.breakdown(10_00_000, 10_00_000, orders=4)["brokerage"] == pytest.approx(80.0)

    def test_percent_brokerage_is_capped_per_order(self):
        s = schedule_for(
            "india_delivery_nse", {"brokerage": {"flat": 0.0, "rate": 0.0003, "cap": 20.0}}
        )
        # 2 orders of 5,00,000 each -> 150 uncapped, so the cap binds at 20.
        assert s.breakdown(5_00_000, 5_00_000, orders=2)["brokerage"] == pytest.approx(40.0)

    def test_bse_carries_its_own_transaction_rate(self):
        nse = schedule_for("india_delivery_nse").breakdown(50_00_000, 50_00_000)
        bse = schedule_for("india_delivery_bse").breakdown(50_00_000, 50_00_000)
        assert bse["exchange_txn"] > nse["exchange_txn"]

    def test_a_different_market_needs_no_new_code(self):
        us = schedule_for("us_equity").breakdown(50_000, 50_000, orders=2)
        # Sell-side only, which an India-shaped model could not express.
        assert us["sec_fee"] == pytest.approx(50_000 * 0.0000278)
        assert us["tax"] == pytest.approx(0.0)
        buy_only = schedule_for("us_equity").breakdown(50_000, 0, orders=1)
        assert buy_only["sec_fee"] == pytest.approx(0.0)

    def test_unknown_override_keys_are_ignored_not_fatal(self):
        # A saved portfolio must not break when a schedule gains or loses a line.
        s = schedule_for("india_delivery_nse", {"nonexistent": {"rate": 1.0}})
        assert s.breakdown(1_000, 1_000)["total"] > 0

    def test_unknown_preset_is_refused(self):
        with pytest.raises(ValueError, match="unknown cost schedule"):
            schedule_for("mars_equity")


class TestRebalancingSweep:
    """
    The comparison has to be on identical prices and identical costs, or it is
    measuring two strategies rather than one decision.
    """

    def _prices(self):
        rng = np.random.default_rng(5)
        index = pd.bdate_range("2020-01-01", periods=800)
        closes = pd.DataFrame(
            {
                "A": 100 * np.cumprod(1 + rng.normal(0.0006, 0.012, 800)),
                "B": 100 * np.cumprod(1 + rng.normal(0.0003, 0.008, 800)),
            },
            index=index,
        )
        return PriceMatrix(closes=closes, source="db",
                           start=index[0].date(), end=index[-1].date())

    def test_covers_every_rule_plus_drift(self):
        out = rebalancing_sweep(self._prices(), {"A": 50, "B": 50})
        labels = [v["label"] for v in out["variants"]]
        assert labels[:4] == ["Never", "Yearly", "Quarterly", "Monthly"]
        assert any(l.startswith("Drift") for l in labels)

    def test_never_is_the_only_one_that_cannot_incur_cost(self):
        out = rebalancing_sweep(
            self._prices(), {"A": 50, "B": 50}, costs=schedule_for("india_delivery_nse")
        )
        never = next(v for v in out["variants"] if v["label"] == "Never")
        monthly = next(v for v in out["variants"] if v["label"] == "Monthly")
        assert never["cost_drag"] == 0.0
        assert never["rebalances"] == 0
        assert monthly["cost_drag"] > 0
        assert monthly["rebalances"] > monthly_expected_min()

    def test_more_trading_costs_more(self):
        out = rebalancing_sweep(
            self._prices(), {"A": 50, "B": 50}, costs=schedule_for("india_delivery_nse")
        )
        by = {v["label"]: v for v in out["variants"]}
        assert by["Monthly"]["turnover"] > by["Quarterly"]["turnover"]
        assert by["Monthly"]["cost_drag"] > by["Quarterly"]["cost_drag"]

    def test_ranks_on_sharpe_not_on_raw_return(self):
        out = rebalancing_sweep(self._prices(), {"A": 50, "B": 50})
        best = next(v for v in out["variants"] if v["label"] == out["best_by_sharpe"])
        assert best["sharpe"] == max(v["sharpe"] for v in out["variants"])

    def test_every_variant_shares_one_window(self):
        out = rebalancing_sweep(self._prices(), {"A": 50, "B": 50})
        # Two results computed over different periods are not a comparison.
        assert len({len(c) for c in out["curves"].values()}) == 1


def monthly_expected_min() -> int:
    """800 business days is about 38 months, so monthly must rebalance often."""
    return 30


class TestLiveHoldings:
    """
    Parsing a broker payload: brokers disagree on types, some omit last_price,
    and a fabricated number here would flow into every downstream metric.
    """

    def test_coerces_string_numerics(self):
        h = parse_holdings([
            {"symbol": "itc", "exchange": "nse", "quantity": "4",
             "average_price": "296.14", "pnl": "-39.55"}
        ])
        assert len(h) == 1
        assert h[0].symbol == "ITC" and h[0].exchange == "NSE"
        assert h[0].quantity == 4.0

    def test_recovers_last_price_from_pnl_when_absent(self):
        # 4 shares bought at 100, P&L -40 -> the market is at 90.
        h = parse_holdings([
            {"symbol": "X", "quantity": 4, "average_price": 100, "pnl": -40}
        ])
        assert h[0].last_price == pytest.approx(90.0)

    def test_drops_rows_it_cannot_weight(self):
        rows = [
            {"symbol": "A", "quantity": 0, "average_price": 10},
            {"symbol": "B", "quantity": 5, "average_price": 0},
            {"symbol": "C", "quantity": "junk", "average_price": 10},
            {"symbol": "D", "quantity": 5, "average_price": 10, "pnl": 0},
        ]
        assert [h.symbol for h in parse_holdings(rows)] == ["D"]

    def test_weights_by_current_value_not_cost(self):
        # Equal cost, but A doubled: exposure is what it is worth now.
        h = parse_holdings([
            {"symbol": "A", "quantity": 10, "average_price": 100, "pnl": 1000},
            {"symbol": "B", "quantity": 10, "average_price": 100, "pnl": 0},
        ])
        s = holdings_summary(h)
        by = {r["symbol"]: r for r in s["holdings"]}
        # Weights are rounded to 5dp for transport, so approx's default 1e-6
        # relative tolerance is tighter than the value can be.
        assert by["A"]["weight"] == pytest.approx(2 / 3, abs=1e-4)
        assert by["B"]["weight"] == pytest.approx(1 / 3, abs=1e-4)

    def test_summary_totals_reconcile(self):
        h = parse_holdings([
            {"symbol": "A", "quantity": 7, "average_price": 282.96, "pnl": -50.01},
            {"symbol": "B", "quantity": 4, "average_price": 296.14, "pnl": -39.55},
        ])
        s = holdings_summary(h)
        assert s["current"] == pytest.approx(s["invested"] + s["pnl"], abs=0.02)
        assert sum(r["weight"] for r in s["holdings"]) == pytest.approx(1.0, abs=1e-4)

    def test_empty_holdings_do_not_divide_by_zero(self):
        s = holdings_summary([])
        assert s["count"] == 0 and s["pnl_pct"] == 0.0
