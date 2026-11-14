"""A Zerodha position closed today reports a P&L % on what was bought (issue #2261).

Kite sends quantity 0 and average_price 0 once a position is squared off, so the
Positions page had no base and showed +0.00% whatever the P&L.
"""

import pytest

from broker.zerodha.mapping.order_data import transform_positions_data


def kite_position(**fields):
    base = {
        "tradingsymbol": "NIFTY27NOV2626000CE",
        "exchange": "NFO",
        "product": "MIS",
        "quantity": 0,
        "average_price": 0,
        "last_price": 7.1,
        "pnl": -862.5,
        "buy_value": 34500.0,
        "sell_value": 33637.5,
    }
    base.update(fields)
    return base


def test_closed_position_carries_pnl_percent_on_buy_value():
    [row] = transform_positions_data([kite_position()])
    assert row["pnlpercent"] == pytest.approx(-2.5)


def test_closed_profit_is_positive():
    [row] = transform_positions_data([kite_position(pnl=1957.5, buy_value=39150.0)])
    assert row["pnlpercent"] == pytest.approx(5.0)


@pytest.mark.parametrize("buy_value", [0, None])
def test_closed_position_without_a_buy_value_has_no_percent(buy_value):
    [row] = transform_positions_data([kite_position(buy_value=buy_value)])
    assert "pnlpercent" not in row


def test_open_position_is_unchanged():
    [row] = transform_positions_data(
        [kite_position(quantity=350, average_price=48.15, last_price=49.5, pnl=472.5)]
    )
    assert "pnlpercent" not in row
    assert row["quantity"] == 350
