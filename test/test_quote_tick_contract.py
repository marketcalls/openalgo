"""Tests for websocket_proxy.tick_contract (Quote-mode field contract).

Adapters forward broker payloads verbatim, and several mappers only add
OHLC when the broker snapshot carries it. The contract guarantees the
documented Quote Data fields on every Quote-mode tick, using null (never
a fabricated 0) for values the broker did not supply. Imports the
lightweight tick_contract module directly so the tests don't depend on
broker adapters or the database layer.
"""

import importlib.util
import pathlib

import pytest

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "websocket_proxy" / "tick_contract.py"
)


def _load_tick_contract():
    spec = importlib.util.spec_from_file_location("_tick_contract_under_test", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_tick_contract()
normalize_quote_tick = _mod.normalize_quote_tick
QUOTE_MODE = _mod.QUOTE_MODE
QUOTE_REQUIRED_FIELDS = _mod.QUOTE_REQUIRED_FIELDS


class TestQuoteModeContract:
    def test_missing_ohlc_becomes_null_not_zero(self):
        # Zerodha-style mapper that omits OHLC when the snapshot lacks it.
        tick = {"symbol": "SBIN", "exchange": "NSE", "ltp": 625.5, "volume": 100}
        normalized = normalize_quote_tick(tick)
        for field in ("open", "high", "low", "close"):
            assert normalized[field] is None  # null, never a fabricated 0

    def test_all_required_fields_present_after_normalisation(self):
        tick = {"ltp": 100.0}
        normalized = normalize_quote_tick(tick)
        for field in QUOTE_REQUIRED_FIELDS:
            assert field in normalized

    def test_broker_supplied_values_preserved(self):
        tick = {
            "ltp": 625.5,
            "open": 620.0,
            "high": 628.0,
            "low": 618.5,
            "close": 622.0,
            "volume": 1500000,
            "timestamp": "2024-01-15T10:30:00+05:30",
        }
        before = dict(tick)
        assert normalize_quote_tick(tick) == before

    def test_zero_values_are_never_overwritten(self):
        # A broker-supplied 0 is real data as far as this module is
        # concerned — normalisation fills absences, it never edits values.
        tick = {"ltp": 625.5, "open": 0, "volume": 0}
        normalized = normalize_quote_tick(tick)
        assert normalized["open"] == 0
        assert normalized["volume"] == 0

    def test_ltp_aliased_from_last_price(self):
        tick = {"last_price": 625.5}
        normalized = normalize_quote_tick(tick)
        assert normalized["ltp"] == 625.5
        # The adapter's own key is untouched.
        assert normalized["last_price"] == 625.5

    def test_missing_volume_and_timestamp_become_null(self):
        tick = {"ltp": 625.5}
        normalized = normalize_quote_tick(tick)
        assert normalized["volume"] is None  # indices carry no volume
        assert normalized["timestamp"] is None

    def test_idempotent(self):
        tick = {"last_price": 42.0, "open": 41.0}
        once = normalize_quote_tick(dict(tick))
        twice = normalize_quote_tick(dict(once))
        assert once == twice

    def test_non_dict_payload_passes_through(self):
        for payload in (None, 42, "oops", [1, 2]):
            assert normalize_quote_tick(payload) is payload

    def test_empty_dict_gets_full_contract(self):
        normalized = normalize_quote_tick({})
        for field in QUOTE_REQUIRED_FIELDS:
            assert field in normalized
            assert normalized[field] is None

    def test_quote_mode_constant_matches_mode_utils(self):
        # Guard against the mirror drifting from websocket_proxy.mode_utils.
        spec = importlib.util.spec_from_file_location(
            "_mode_utils_guard",
            pathlib.Path(__file__).resolve().parent.parent / "websocket_proxy" / "mode_utils.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert QUOTE_MODE == mod.MODE_BY_UPPER_LABEL["QUOTE"]

    def test_mutates_in_place_and_returns_same_object(self):
        tick = {"ltp": 1.0}
        result = normalize_quote_tick(tick)
        assert result is tick
