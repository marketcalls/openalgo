"""Tests for the daily NIFTY futures contract map boundary."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from strategies.python.nifty_weekly_momentum.contract_map import ContractMapError, load_contract_map


def _payload() -> dict:
    weights = [20.0, 15.0, 12.0, 10.0, 9.0, 8.0, 6.0, 5.0, 4.0, 3.0]
    total = sum(weights)
    contracts = {}
    for rank, weight in enumerate(weights, start=1):
        symbol = f"NAME{rank}"
        contracts[symbol] = {
            "openalgo_symbol": f"{symbol}27AUG26FUT",
            "broker_symbol": f"{symbol}-FUT",
            "broker_exchange": "NFO",
            "token": str(1000 + rank),
            "expiry": "27-AUG-26",
            "lotsize": "25",
            "tick_size": "0.05",
            "weight_percent": weight,
            "normalized_weight": weight / total,
            "rank": rank,
        }
    return {
        "resolved_date": "2026-08-21",
        "common_expiry": "27-AUG-26",
        "resolved_count": len(contracts),
        "excluded_symbols": ["MISSING"],
        "raw_weight_covered": total,
        "source_weight_total": 97.97,
        "contracts": contracts,
    }


class ContractMapTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._temp_dir.cleanup()

    def _write(self, payload: dict) -> Path:
        path = Path(self._temp_dir.name) / "nifty-futures-map-2026-08-21.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_and_orders_valid_contract_map(self):
        loaded = load_contract_map(self._write(_payload()), date(2026, 8, 21))

        self.assertEqual(date(2026, 8, 27), loaded.common_expiry)
        self.assertEqual(92.0, loaded.raw_weight_covered)
        self.assertEqual(10, len(loaded.contracts))
        self.assertEqual(1, loaded.contracts[0].rank)
        self.assertTrue(loaded.contracts[0].is_top10)
        self.assertAlmostEqual(1.0, sum(contract.normalized_weight for contract in loaded.contracts))

    def test_rejects_stale_session_map(self):
        with self.assertRaisesRegex(ContractMapError, "expected 2026-08-22"):
            load_contract_map(self._write(_payload()), date(2026, 8, 22))

    def test_rejects_missing_top10_rank(self):
        payload = _payload()
        payload["contracts"]["NAME10"]["rank"] = 11

        with self.assertRaisesRegex(ContractMapError, "top-10"):
            load_contract_map(self._write(payload), date(2026, 8, 21))

    def test_rejects_non_normalized_weights(self):
        payload = _payload()
        payload["contracts"]["NAME1"]["normalized_weight"] = 0.5

        with self.assertRaisesRegex(ContractMapError, "normalized weights"):
            load_contract_map(self._write(payload), date(2026, 8, 21))


if __name__ == "__main__":
    unittest.main()