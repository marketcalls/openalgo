"""Tests for one-second futures sampling."""
from __future__ import annotations

import unittest

from strategies.python.nifty_weekly_momentum.frame_sampler import FuturesFrameSampler


class FuturesFrameSamplerTests(unittest.TestCase):
    def test_uses_microprice_from_fresh_depth(self):
        sampler = FuturesFrameSampler(["A"])
        sampler.ingest_quote("A", 100.8, bid=99.0, ask=101.0, bid_size=30, ask_size=10)

        frame = sampler.build_frame(100)["A"]

        self.assertEqual("microprice", frame.source)
        self.assertAlmostEqual(100.5, frame.price)

    def test_uses_vwap_only_with_positive_trade_quantities(self):
        sampler = FuturesFrameSampler(["A"])
        sampler.ingest_quote("A", 100.2, bid=99.0, ask=101.0, bid_size=10, ask_size=10)
        sampler.ingest_trade("A", 100.3, price=100.0, quantity=2)
        sampler.ingest_trade("A", 100.7, price=103.0, quantity=1)

        frame = sampler.build_frame(100)["A"]

        self.assertEqual("vwap", frame.source)
        self.assertAlmostEqual(101.0, frame.price)

    def test_zero_quantity_ltp_does_not_pretend_to_be_vwap(self):
        sampler = FuturesFrameSampler(["A"])
        sampler.ingest_quote("A", 100.2, bid=99.0, ask=101.0, bid_size=0, ask_size=0)
        sampler.ingest_trade("A", 100.7, price=110.0, quantity=0)

        frame = sampler.build_frame(100)["A"]

        self.assertEqual("midpoint", frame.source)
        self.assertEqual(100.0, frame.price)

    def test_rejects_crossed_and_stale_depth(self):
        crossed = FuturesFrameSampler(["A"])
        crossed.ingest_quote("A", 100.5, bid=102.0, ask=101.0, bid_size=10, ask_size=10)
        self.assertEqual("stale", crossed.build_frame(100)["A"].source)

        stale = FuturesFrameSampler(["A"])
        stale.ingest_quote("A", 97.0, bid=99.0, ask=101.0, bid_size=10, ask_size=10)
        self.assertEqual("stale", stale.build_frame(100)["A"].source)

    def test_emits_one_frame_for_every_configured_symbol(self):
        sampler = FuturesFrameSampler(["A", "B"])
        sampler.ingest_quote("A", 100.5, bid=99.0, ask=101.0, bid_size=10, ask_size=10)

        frames = sampler.build_frame(100)

        self.assertEqual({"A", "B"}, set(frames))
        self.assertEqual("stale", frames["B"].source)


if __name__ == "__main__":
    unittest.main()