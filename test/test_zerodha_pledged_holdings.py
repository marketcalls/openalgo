"""Zerodha holdings count pledged and T1 shares.

Kite reports a pledged holding with ``quantity: 0`` and the shares in
``collateral_quantity``, while its ``pnl`` covers every share. Rows below are
shaped on a live account: RELIANCE 200 and WAAREEENER 45, both fully pledged,
showed quantity 0 and holding value 0 against a P&L of -25,396.
"""

from broker.zerodha.mapping.order_data import (
    calculate_portfolio_statistics,
    transform_holdings_data,
)

PLEDGED = [
    {
        "tradingsymbol": "RELIANCE",
        "exchange": "BSE",
        "product": "CNC",
        "quantity": 0,
        "t1_quantity": 0,
        "collateral_quantity": 200,
        "collateral_type": "margin",
        "average_price": 1297.0,
        "last_price": 1380.35,
        "pnl": 16670.0,
    },
    {
        "tradingsymbol": "WAAREEENER",
        "exchange": "BSE",
        "product": "CNC",
        "quantity": 0,
        "t1_quantity": 0,
        "collateral_quantity": 45,
        "collateral_type": "margin",
        "average_price": 3336.0,
        "last_price": 2401.2,
        "pnl": -42066.0,
    },
]


def test_fully_pledged_holding_keeps_its_quantity():
    rows = transform_holdings_data(PLEDGED)
    assert [r["quantity"] for r in rows] == [200, 45]


def test_pledged_holding_value_matches_kite_pnl():
    stats = calculate_portfolio_statistics(PLEDGED)
    assert round(stats["totalholdingvalue"], 2) == round(1380.35 * 200 + 2401.2 * 45, 2)
    assert round(stats["totalinvvalue"], 2) == round(1297.0 * 200 + 3336.0 * 45, 2)
    assert round(stats["totalholdingvalue"] - stats["totalinvvalue"], 2) == -25396.0
    assert stats["totalpnlpercentage"] != 0


def test_partly_pledged_and_t1_shares_add_up():
    row = {
        "tradingsymbol": "INFY",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 60,
        "t1_quantity": 5,
        "collateral_quantity": 40,
        "average_price": 1500.0,
        "last_price": 1600.0,
        "pnl": 10500.0,
    }
    [out] = transform_holdings_data([row])
    assert out["quantity"] == 105


def test_rows_without_collateral_fields_are_unchanged():
    row = {
        "tradingsymbol": "SBIN",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": 10,
        "average_price": 500.0,
        "last_price": 550.0,
        "pnl": 500.0,
    }
    [out] = transform_holdings_data([row])
    assert out["quantity"] == 10
    assert calculate_portfolio_statistics([row])["totalholdingvalue"] == 5500.0
