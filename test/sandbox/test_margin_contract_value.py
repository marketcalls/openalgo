# test/sandbox/test_margin_contract_value.py
"""
Regression tests for contract_value scaling in sandbox margin calculation.

Sandbox P&L (realized + unrealized) is scaled by a per-symbol ``contract_value``
multiplier for instruments where one contract is not one unit of the underlying
(e.g. crypto derivatives: 0.001 BTC or 0.01 ETH per contract). The margin
calculation must apply the same multiplier, otherwise margin/used-margin is
over-blocked by 1/contract_value (e.g. ~1000x for BTC) while P&L stays correct,
leaving the funds ledger inconsistent with the position ledger.

Both paths share ``utils.symbol_utils.normalize_contract_value`` so they cannot
diverge, and the normalizer rejects non-finite / non-positive multipliers so a
bad value can never turn margin negative.

These tests isolate ``FundManager.calculate_margin_required`` by mocking the
symbol lookup and leverage so no database is required.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import patch

# Add repo root to the front of the path so the project's own packages
# (sandbox/, database/, utils/) take precedence over any similarly named modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sandbox.fund_manager import FundManager
from utils.symbol_utils import normalize_contract_value


class _Sym:
    """Minimal stand-in for a symtoken row."""

    def __init__(self, contract_value):
        self.contract_value = contract_value


def _fund_manager():
    # Avoid DB access in FundManager.__init__ (reads starting_capital from config)
    with patch("sandbox.fund_manager.get_config", return_value="10000000.00"):
        return FundManager("TEST_CV_USER")


# --- normalize_contract_value: shared validation ---------------------------------


def test_normalize_valid_multipliers():
    assert normalize_contract_value(0.001) == Decimal("0.001")
    assert normalize_contract_value(0.01) == Decimal("0.01")
    assert normalize_contract_value(1.0) == Decimal("1.0")
    assert normalize_contract_value("0.001") == Decimal("0.001")


def test_normalize_rejects_missing_or_bad_values():
    # Missing / non-positive / non-finite all fall back to 1.0 (never corrupt margin).
    assert normalize_contract_value(None) == Decimal("1.0")
    assert normalize_contract_value(0) == Decimal("1.0")
    assert normalize_contract_value(-0.001) == Decimal("1.0")
    assert normalize_contract_value("nan") == Decimal("1.0")
    assert normalize_contract_value("inf") == Decimal("1.0")
    assert normalize_contract_value("not-a-number") == Decimal("1.0")


# --- calculate_margin_required: contract_value applied ---------------------------


@patch.object(FundManager, "_get_leverage", return_value=Decimal("1"))
@patch("sandbox.fund_manager.get_symbol_info")
def test_equity_margin_unaffected_by_contract_value(mock_sym, _lev):
    """contract_value = 1.0 (equity/standard F&O) => margin = qty * price / leverage."""
    mock_sym.return_value = _Sym(1.0)
    fm = _fund_manager()

    margin, msg = fm.calculate_margin_required("RELIANCE", "NSE", "MIS", 100, 1500, action="BUY")

    assert margin == Decimal("150000"), f"expected 150000, got {margin} ({msg})"


@patch.object(FundManager, "_get_leverage", return_value=Decimal("1"))
@patch("sandbox.fund_manager.get_symbol_info")
def test_btc_option_margin_scaled_by_contract_value(mock_sym, _lev):
    """BTC contract_value = 0.001 => margin scaled down 1000x vs raw premium * qty."""
    mock_sym.return_value = _Sym(0.001)
    fm = _fund_manager()

    margin, msg = fm.calculate_margin_required(
        "BTC12JUL2663800PE", "CRYPTO", "NRML", 4, 123.4, action="BUY"
    )

    expected = Decimal("4") * Decimal("123.4") * Decimal("0.001")  # 0.4936
    assert margin == expected, f"expected {expected}, got {margin} ({msg})"
    # Guard against the pre-fix behaviour (raw, unscaled premium * qty).
    assert margin != Decimal("4") * Decimal("123.4"), "margin was not scaled by contract_value"


@patch.object(FundManager, "_get_leverage", return_value=Decimal("1"))
@patch("sandbox.fund_manager.get_symbol_info")
def test_eth_option_margin_scaled_by_contract_value(mock_sym, _lev):
    """ETH contract_value = 0.01 => margin scaled down 100x vs raw premium * qty."""
    mock_sym.return_value = _Sym(0.01)
    fm = _fund_manager()

    margin, msg = fm.calculate_margin_required(
        "ETH12JUL261810PE", "CRYPTO", "NRML", 2, 7.7, action="BUY"
    )

    expected = Decimal("2") * Decimal("7.7") * Decimal("0.01")  # 0.154
    assert margin == expected, f"expected {expected}, got {margin} ({msg})"


@patch.object(FundManager, "_get_leverage", return_value=Decimal("10"))
@patch("sandbox.fund_manager.get_symbol_info")
def test_leverage_still_applied_on_top_of_contract_value(mock_sym, _lev):
    """Leverage divides the contract_value-scaled notional (e.g. crypto futures)."""
    mock_sym.return_value = _Sym(0.001)
    fm = _fund_manager()

    margin, msg = fm.calculate_margin_required("BTCUSDFUT", "CRYPTO", "NRML", 4, 78000, action="BUY")

    expected = (Decimal("4") * Decimal("78000") * Decimal("0.001")) / Decimal("10")  # 31.2
    assert margin == expected, f"expected {expected}, got {margin} ({msg})"


@patch.object(FundManager, "_get_leverage", return_value=Decimal("1"))
@patch("sandbox.fund_manager.get_symbol_info")
def test_bad_contract_value_never_yields_negative_margin(mock_sym, _lev):
    """A negative/invalid multiplier must fall back to 1.0, never produce negative margin
    (which would credit available_balance when block_margin subtracts it)."""
    mock_sym.return_value = _Sym(-0.001)
    fm = _fund_manager()

    margin, msg = fm.calculate_margin_required(
        "BTC12JUL2663800PE", "CRYPTO", "NRML", 4, 123.4, action="BUY"
    )

    assert margin is not None and margin > 0, f"margin should be positive, got {margin} ({msg})"
    assert margin == Decimal("4") * Decimal("123.4"), "should fall back to unscaled (cv=1.0)"


if __name__ == "__main__":
    test_normalize_valid_multipliers()
    test_normalize_rejects_missing_or_bad_values()
    test_equity_margin_unaffected_by_contract_value()
    test_btc_option_margin_scaled_by_contract_value()
    test_eth_option_margin_scaled_by_contract_value()
    test_leverage_still_applied_on_top_of_contract_value()
    test_bad_contract_value_never_yields_negative_margin()
    print("ALL contract_value margin tests passed")
