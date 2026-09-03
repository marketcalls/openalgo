"""Kotak position P&L.

Kotak's /quick/user/positions payload carries no pnl field, so
transform_positions_data computes one from Kotak's documented "Profit N Loss"
formula (issue #1970). The realized half is covered for closed legs; these pin
the open half, where the mark-to-market term applies and where a missing key
used to leave Flow's pnl_above/pnl_below guards evaluating 0.
"""

import pytest

from broker.kotak.mapping.order_data import transform_positions_data


def row(**kw):
    """One raw Kotak position row, flat by default."""
    base = {
        "trdSym": "YESBANK",
        "exSeg": "NSE",
        "prod": "MIS",
        "flBuyQty": "0",
        "flSellQty": "0",
        "cfBuyQty": "0",
        "cfSellQty": "0",
        "buyAmt": "0.00",
        "sellAmt": "0.00",
        "cfBuyAmt": "0.00",
        "cfSellAmt": "0.00",
        "avgnetprice": 0.0,
    }
    base.update(kw)
    return base


def one(**kw):
    return transform_positions_data([row(**kw)])[0]


# --- the realized half, which must not regress -------------------------------

# The four real SENSEX legs from issue #1970, all fully squared off.
CLOSED_LEGS = [
    ("SENSEX2690376900CE", "1641.00", "1810.00", 169.00),
    ("SENSEX2690376300CE", "6466.00", "5683.00", -783.00),
    ("SENSEX2690375700PE", "1455.00", "595.00", -860.00),
    ("SENSEX2690376300PE", "2735.00", "5197.00", 2462.00),
]


@pytest.mark.parametrize(("symbol", "buy_amt", "sell_amt", "expected"), CLOSED_LEGS)
def test_a_closed_leg_reports_its_realized_pnl(symbol, buy_amt, sell_amt, expected):
    position = one(trdSym=symbol, flBuyQty="20", flSellQty="20", buyAmt=buy_amt, sellAmt=sell_amt)

    assert position["quantity"] == 0
    assert position["pnl"] == expected


def test_the_closed_book_totals_what_the_account_made():
    positions = transform_positions_data(
        [
            row(trdSym=s, flBuyQty="20", flSellQty="20", buyAmt=b, sellAmt=sl)
            for s, b, sl, _ in CLOSED_LEGS
        ]
    )

    assert round(sum(p["pnl"] for p in positions), 2) == 988.00


def test_a_leg_carried_forward_and_closed_today_counts_the_carried_amounts():
    position = one(flSellQty="10", cfBuyQty="10", cfBuyAmt="450.00", sellAmt="500.00")

    assert position["quantity"] == 0
    assert position["pnl"] == 50.0


def test_a_row_with_no_trades_at_all_reports_zero():
    assert one()["pnl"] == 0.0


# --- the open half -----------------------------------------------------------


def test_an_open_long_is_marked_to_market():
    # 100 bought for 2100 (avg 21.00), now worth 22.50 -> +150.
    position = one(flBuyQty="100", buyAmt="2100.00", _ltp=22.50)

    assert position["quantity"] == 100
    assert position["pnl"] == 150.0


def test_an_open_short_profits_when_the_price_falls():
    # 100 sold for 2100 (avg 21.00), now worth 19.50 -> +150.
    position = one(flSellQty="100", sellAmt="2100.00", _ltp=19.50)

    assert position["quantity"] == -100
    assert position["pnl"] == 150.0


def test_a_partly_closed_position_counts_both_halves():
    # 100 bought at 21.00, 40 sold at 22.00 (realized +40), 60 held at 22.50
    # (unrealized +90).
    position = one(flBuyQty="100", buyAmt="2100.00", flSellQty="40", sellAmt="880.00", _ltp=22.50)

    assert position["quantity"] == 60
    assert position["pnl"] == 130.0


def test_an_open_position_with_no_quote_reports_zero_not_its_cost():
    """The LTP backfill is best-effort; a failed quote must not read as a loss."""
    position = one(flBuyQty="100", buyAmt="2100.00")

    assert position["ltp"] == 0.0
    assert position["pnl"] == 0.0


def test_every_row_carries_a_pnl_key():
    """Flow's Position Check reads pos.get("pnl", 0); a missing key reads as 0."""
    positions = transform_positions_data(
        [
            row(flBuyQty="100", buyAmt="2100.00", _ltp=22.50),
            row(flBuyQty="20", flSellQty="20", buyAmt="1641.00", sellAmt="1810.00"),
            row(),
        ]
    )

    assert all("pnl" in p for p in positions)


# --- the scaling terms -------------------------------------------------------


def test_the_documented_multiplier_scales_the_open_leg():
    position = one(flBuyQty="10", buyAmt="1000.00", _ltp=110.0, multiplier="2")

    # realized -1000, marked 10 * 110 * 2 = 2200.
    assert position["pnl"] == 1200.0


@pytest.mark.parametrize("scaling", [{}, {"genDen": "0"}, {"prcNum": ""}, {"multiplier": None}])
def test_an_unusable_scaling_field_falls_back_to_one(scaling):
    position = one(flBuyQty="100", buyAmt="2100.00", _ltp=22.50, **scaling)

    assert position["pnl"] == 150.0
