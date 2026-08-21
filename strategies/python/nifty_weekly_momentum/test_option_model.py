"""Tests for W+1 option valuation and execution planning."""
from __future__ import annotations

import math
import unittest

from strategies.python.nifty_weekly_momentum.option_model import (
    OptionQuote,
    black76_price,
    build_entry_plan,
    evaluate_long_option,
    implied_volatility,
    realized_volatility,
)


class OptionModelTests(unittest.TestCase):
    def test_implied_volatility_round_trip(self):
        expected = 0.22
        price = black76_price(25_000, 25_000, 7 / 365, 0.06, expected, "call")

        actual = implied_volatility(price, 25_000, 25_000, 7 / 365, 0.06, "call")

        self.assertIsNotNone(actual)
        self.assertAlmostEqual(expected, actual, places=8)

    def test_realized_volatility_requires_enough_observations(self):
        self.assertIsNone(realized_volatility([(float(i), 100.0) for i in range(59)]))
        prices = [(float(i), 100.0 * math.exp(((-1) ** i) * 0.0001)) for i in range(120)]
        self.assertGreater(realized_volatility(prices), 0)

    def test_valuation_accepts_consistent_parity_and_reasonable_iv(self):
        seconds = 7 * 24 * 60 * 60
        years = seconds / (365 * 24 * 60 * 60)
        call_mid = black76_price(25_000, 25_000, years, 0.06, 0.20, "call")
        put_mid = black76_price(25_000, 25_000, years, 0.06, 0.20, "put")
        call = OptionQuote(call_mid - 0.05, call_mid + 0.05, 100, 100)
        put = OptionQuote(put_mid - 0.05, put_mid + 0.05, 100, 100)

        result = evaluate_long_option(
            call,
            put,
            "call",
            strike=25_000,
            seconds_to_expiry=seconds,
            realized_vol=0.20,
            lot_size=1,
            planned_risk=10_000,
            estimated_fees=1,
        )

        self.assertTrue(result.allowed, result.reason)
        self.assertAlmostEqual(25_000, result.forward, places=6)
        self.assertAlmostEqual(0.20, result.midpoint_iv, places=6)

    def test_valuation_rejects_expensive_iv(self):
        seconds = 7 * 24 * 60 * 60
        years = seconds / (365 * 24 * 60 * 60)
        call_mid = black76_price(25_000, 25_000, years, 0.06, 0.30, "call")
        put_mid = black76_price(25_000, 25_000, years, 0.06, 0.30, "put")

        result = evaluate_long_option(
            OptionQuote(call_mid - 0.05, call_mid + 0.05, 100, 100),
            OptionQuote(put_mid - 0.05, put_mid + 0.05, 100, 100),
            "call",
            25_000,
            seconds,
            realized_vol=0.15,
            lot_size=1,
            planned_risk=10_000,
            estimated_fees=1,
        )

        self.assertFalse(result.allowed)
        self.assertIn("IV/RV", result.reason)

    def test_entry_plan_sizes_in_lot_multiples(self):
        plan = build_entry_plan(
            OptionQuote(9.95, 10.0, 100, 100),
            lot_size=25,
            tick_size=0.05,
            per_trade_risk=500,
            remaining_risk=900,
            capital=100_000,
            estimated_fees_per_lot=20,
        )

        self.assertTrue(plan.allowed, plan.reason)
        self.assertEqual(5, plan.lots)
        self.assertEqual(125, plan.quantity)
        self.assertEqual(10.0, plan.limit_price)

    def test_entry_plan_skips_when_one_lot_does_not_fit(self):
        plan = build_entry_plan(
            OptionQuote(199.0, 200.0, 65, 65),
            lot_size=65,
            tick_size=0.05,
            per_trade_risk=500,
            remaining_risk=2_000,
            capital=100_000,
            estimated_fees_per_lot=100,
        )

        self.assertFalse(plan.allowed)
        self.assertIn("one-lot risk", plan.reason)

    def test_entry_plan_rejects_wide_or_shallow_quotes(self):
        wide = build_entry_plan(
            OptionQuote(95.0, 100.0, 100, 100), 25, 0.05, 500, 2_000, 100_000, 20
        )
        shallow = build_entry_plan(
            OptionQuote(99.9, 100.0, 100, 10), 25, 0.05, 500, 2_000, 100_000, 20
        )

        self.assertFalse(wide.allowed)
        self.assertIn("spread", wide.reason)
        self.assertFalse(shallow.allowed)
        self.assertIn("visible ask", shallow.reason)


if __name__ == "__main__":
    unittest.main()