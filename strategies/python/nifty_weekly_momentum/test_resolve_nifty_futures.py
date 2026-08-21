"""Focused tests for the NIFTY futures resolver."""
from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "resolve-nifty-futures.py"
SPEC = importlib.util.spec_from_file_location("resolve_nifty_futures", SCRIPT_PATH)
resolver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(resolver)


class ResolveNiftyFuturesTests(unittest.TestCase):
    def setUp(self):
        self.original_min_weight = resolver.MIN_RAW_WEIGHT_PTS
        self.original_top_n = resolver.TOP_N_REQUIRED
        resolver.MIN_RAW_WEIGHT_PTS = 90.0
        resolver.TOP_N_REQUIRED = 2

    def tearDown(self):
        resolver.MIN_RAW_WEIGHT_PTS = self.original_min_weight
        resolver.TOP_N_REQUIRED = self.original_top_n

    def test_selects_exact_common_expiry_and_preserves_rank(self):
        rows = [
            {"NSE_Symbol": "ALPHA", "Weight_Percent": "55", "Rank": "1"},
            {"NSE_Symbol": "BETA", "Weight_Percent": "40", "Rank": "2"},
            {"NSE_Symbol": "GAMMA", "Weight_Percent": "5", "Rank": "3"},
        ]
        instruments = [
            self._future("ALPHA", "ALPHA30JAN30FUT", "30-JAN-30"),
            self._future("BETA", "BETA30JAN30FUT", "30-JAN-30"),
            self._future("GAMMA", "GAMMA30JAN30FUT", "30-JAN-30"),
            self._future("ALPHA", "ALPHA27FEB30FUT", "27-FEB-30"),
            self._future("BETA", "BETA27FEB30FUT", "27-FEB-30"),
        ]

        expiry, resolved, excluded = resolver.select_common_expiry(
            rows,
            resolver.group_futures_by_underlying(instruments),
            date(2030, 1, 1),
        )

        self.assertEqual("30-JAN-30", expiry)
        self.assertEqual("ALPHA30JAN30FUT", resolved["ALPHA"]["openalgo_symbol"])
        self.assertEqual(1, resolved["ALPHA"]["rank"])
        self.assertEqual(2, resolved["BETA"]["rank"])
        self.assertEqual([], excluded)

    def test_rejects_expiry_missing_a_required_top_rank(self):
        rows = [
            {"NSE_Symbol": "ALPHA", "Weight_Percent": "91", "Rank": "1"},
            {"NSE_Symbol": "BETA", "Weight_Percent": "9", "Rank": "2"},
        ]
        instruments = [self._future("ALPHA", "ALPHA30JAN30FUT", "30-JAN-30")]

        expiry, resolved, excluded = resolver.select_common_expiry(
            rows,
            resolver.group_futures_by_underlying(instruments),
            date(2030, 1, 1),
        )

        self.assertIsNone(expiry)
        self.assertEqual({}, resolved)
        self.assertEqual(["ALPHA", "BETA"], excluded)

    @staticmethod
    def _future(name: str, symbol: str, expiry: str) -> dict:
        return {
            "name": name,
            "symbol": symbol,
            "exchange": "NFO",
            "instrumenttype": "FUT",
            "expiry": expiry,
            "lotsize": "250",
            "tick_size": "0.05",
        }


if __name__ == "__main__":
    unittest.main()