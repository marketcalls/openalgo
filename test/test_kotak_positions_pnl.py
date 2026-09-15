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


# --- average price across the carried-forward leg ----------------------------


def test_a_carried_forward_position_reports_what_it_cost():
    """flBuyQty is 0 with nothing filled today, which used to give 0.00."""
    position = one(cfBuyQty="50", cfBuyAmt="40000.00", _ltp=815.0)

    assert position["quantity"] == 50
    assert position["average_price"] == 800.0
    assert position["pnl"] == 750.0


def test_an_average_blends_the_carried_leg_with_todays():
    # 50 carried at 800.00, 20 more bought today at 810.00.
    position = one(cfBuyQty="50", cfBuyAmt="40000.00", flBuyQty="20", buyAmt="16200.00")

    assert position["quantity"] == 70
    assert position["average_price"] == 802.86


def test_a_carried_forward_short_reports_what_it_sold_for():
    position = one(cfSellQty="50", cfSellAmt="40000.00", _ltp=790.0)

    assert position["quantity"] == -50
    assert position["average_price"] == 800.0
    assert position["pnl"] == 500.0


def test_a_position_opened_and_partly_closed_today_keeps_its_entry_price():
    position = one(flBuyQty="100", buyAmt="2100.00", flSellQty="40", sellAmt="880.00")

    assert position["quantity"] == 60
    assert position["average_price"] == 21.0


# --- fields Kotak sent in a shape we cannot use ------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"cfBuyAmt": None},
        {"cfSellAmt": ""},
        {"sellAmt": "NA"},
        {"cfBuyQty": None},
        {"flSellQty": ""},
        {"_ltp": None},
    ],
)
def test_one_unusable_field_does_not_take_the_whole_book_down(bad):
    positions = transform_positions_data([row(flBuyQty="10", buyAmt="1000.00", **bad)])

    assert len(positions) == 1
    assert "pnl" in positions[0]


def test_an_open_position_is_marked_against_the_unrounded_price():
    """CDS quotes carry four decimals, so the display value is not good enough.

    USDINR ticks at 0.0025. Marking 10,000 against 83.47 instead of 83.4725
    understates the position by 25 rupees.
    """
    position = one(flBuyQty="10000", buyAmt="834000.00", _ltp=83.4725)

    assert position["ltp"] == 83.47
    assert position["pnl"] == 725.0


# --- the carried-forward leg's cost basis (issue #2061) ----------------------

# The five overnight short option legs from issue #2061, as the reporter's own
# two screenshots show them. "carried" is cfSellAmt / cfSellQty, the price
# Kotak carried the leg in at, which OpenAlgo reported as the average; "avg" is
# the average the Kotak app showed, recovered to four decimals from the app's
# own P&L (it displays the average rounded to two). Both P&L columns are the
# app's, to the paisa.
CARRIED_SHORT_LEGS = [
    # symbol, qty, carried (settlement), upldPrc (cost), ltp, avg shown, pnl
    ("BPCL29SEP26315PE", 1975, 11.90, 4.7480, 11.90, 4.75, -14125.20),
    ("COFORGE29SEP261940PE", 475, 130.18, 43.8816, 101.20, 43.88, -27226.24),
    ("MFSL29SEP261540PE", 400, 65.40, 20.9912, 65.40, 20.99, -17763.52),
    ("POLYCAB29SEP269100PE", 125, 808.00, 171.92768, 808.00, 171.93, -79509.04),
    ("RBLBANK29SEP26415PE", 3175, 8.60, 7.2969, 8.60, 7.30, -4137.34),
]


def carried_short(symbol, qty, carried, upld, ltp, **kw):
    """One overnight short leg, with nothing filled today."""
    return row(
        trdSym=symbol,
        cfSellQty=str(qty),
        cfSellAmt=f"{carried * qty:.2f}",
        upldPrc=f"{upld}",
        _ltp=ltp,
        **kw,
    )


@pytest.mark.parametrize(
    ("symbol", "qty", "carried", "upld", "ltp", "avg", "pnl"), CARRIED_SHORT_LEGS
)
def test_a_carried_leg_reports_what_it_cost_not_what_it_was_carried_at(
    symbol, qty, carried, upld, ltp, avg, pnl
):
    position = transform_positions_data([carried_short(symbol, qty, carried, upld, ltp)])[0]

    assert position["quantity"] == -qty
    assert position["average_price"] == avg
    assert position["pnl"] == pnl


def test_the_carried_book_totals_what_the_broker_app_showed():
    """The whole of issue #2061: 1.42 lakh down, reported as +13,765.50."""
    positions = transform_positions_data(
        [carried_short(s, q, c, u, ltp) for s, q, c, u, ltp, _, _ in CARRIED_SHORT_LEGS]
    )

    assert round(sum(p["pnl"] for p in positions), 2) == -142761.34


def test_the_carried_valuation_is_not_an_average_price():
    """Kotak carries an overnight leg at the previous settlement price.

    Four of the five legs above were illiquid enough that their last trade was
    that same settlement price, so the average OpenAlgo derived from it came
    out equal to the LTP and the P&L read 0.00 on a losing position.
    """
    symbol, qty, carried, upld, ltp, _, _ = CARRIED_SHORT_LEGS[0]
    position = transform_positions_data([carried_short(symbol, qty, carried, upld, ltp)])[0]

    assert carried == ltp
    assert position["average_price"] != position["ltp"]
    assert position["pnl"] != 0.0


@pytest.mark.parametrize("missing", [{}, {"upldPrc": "0.00"}, {"upldPrc": None}, {"upldPrc": ""}])
def test_without_a_cost_basis_the_documented_amounts_still_apply(missing):
    """No upldPrc leaves #1985's behaviour exactly as it was.

    Kotak's own formula on its own amounts is the day's P&L rather than the
    P&L since entry, but it is the only thing the payload supports, and it is
    what a carried-forward leg reported before this changed.
    """
    position = one(cfSellQty="50", cfSellAmt="40000.00", _ltp=790.0, **missing)

    assert position["average_price"] == 800.0
    assert position["pnl"] == 500.0


def test_a_cost_basis_equal_to_the_carried_valuation_changes_nothing():
    """The property that makes upldPrc safe to prefer sight-unseen.

    If Kotak populates upldPrc with the settlement price rather than the cost,
    cf_qty * upldPrc is the carried amount already in use and every number
    here is the one #1985 produced. The two rows differ only in whether they
    say where the number came from, which is the whole point of the qualifier.
    """
    with_cost = one(cfBuyQty="50", cfBuyAmt="40000.00", upldPrc="800.00", _ltp=815.0)
    without = one(cfBuyQty="50", cfBuyAmt="40000.00", _ltp=815.0)

    numbers = ("quantity", "average_price", "ltp", "pnl")
    assert [with_cost[k] for k in numbers] == [without[k] for k in numbers]
    assert "average_price_basis" not in with_cost
    assert without["average_price_basis"] == "carry_forward_valuation"


def test_a_carried_long_partly_closed_today_splits_realized_from_unrealized():
    # 50 carried at 800.00, 20 sold today at 810.00 (+200 realized), 30 still
    # held and marked at 815.00 (+450 unrealized).
    position = one(
        cfBuyQty="50",
        cfBuyAmt="47000.00",  # carried at 940.00, the settlement price
        upldPrc="800.00",
        flSellQty="20",
        sellAmt="16200.00",
        _ltp=815.0,
    )

    assert position["quantity"] == 30
    assert position["average_price"] == 800.0
    assert position["pnl"] == 650.0


def test_a_carried_short_partly_covered_today_splits_realized_from_unrealized():
    # 50 carried short at 800.00, 20 bought back today at 790.00 (+200
    # realized), 30 still short and marked at 790.00 (+300 unrealized).
    position = one(
        cfSellQty="50",
        cfSellAmt="30000.00",  # carried at 600.00, the settlement price
        upldPrc="800.00",
        flBuyQty="20",
        buyAmt="15800.00",
        _ltp=790.0,
    )

    assert position["quantity"] == -30
    assert position["average_price"] == 800.0
    assert position["pnl"] == 500.0


def test_a_cost_basis_blends_with_what_was_added_today():
    # 50 carried at 800.00, 20 more bought today at 810.00.
    position = one(
        cfBuyQty="50",
        cfBuyAmt="47000.00",
        upldPrc="800.00",
        flBuyQty="20",
        buyAmt="16200.00",
    )

    assert position["quantity"] == 70
    assert position["average_price"] == 802.86


def test_a_row_with_no_carried_leg_ignores_upldPrc():
    """Kotak sends upldPrc "0.00" on such rows, but it must not be read either way."""
    position = one(flBuyQty="100", buyAmt="2100.00", upldPrc="999.00", _ltp=22.50)

    assert position["average_price"] == 21.0
    assert position["pnl"] == 150.0


def test_an_average_reproduces_its_own_pnl_under_a_multiplier():
    """Kotak's documented average divides by quantity * the scaling factor.

    Dividing by the quantity alone left the two on different bases: the P&L
    scales the mark-to-market leg by the factor and the average did not, so
    (ltp - average) * qty * factor no longer came back to the reported P&L.
    """
    position = one(flBuyQty="10", buyAmt="1000.00", _ltp=110.0, multiplier="2")

    assert position["average_price"] == 50.0
    assert (110.0 - position["average_price"]) * position["quantity"] * 2 == position["pnl"]


@pytest.mark.parametrize("bad", [{"upldPrc": "NA"}, {"upldPrc": "-5"}, {"cfSellQty": None}])
def test_an_unusable_cost_basis_does_not_take_the_book_down(bad):
    fields = {"cfSellQty": "50", "cfSellAmt": "40000.00", "_ltp": 790.0}
    fields.update(bad)
    positions = transform_positions_data([row(**fields)])

    assert len(positions) == 1
    assert "pnl" in positions[0]


# --- saying so on the row (issue #2061) --------------------------------------

# The five carried legs exactly as Kotak sent them on 15 Sep, from the raw
# /quick/user/positions payload in the issue. upldPrc is "0.00" on every one,
# so these are the rows that take the fallback path.
RAW_CARRIED_ROWS = [
    ("RBLBANK26SEP415PE", "3175", "27305.00", 8.60),
    ("BPCL26SEP315PE", "1975", "23502.50", 11.90),
    ("COFORGE26SEP1940PE", "475", "61835.50", 130.18),
    ("MFSL26SEP1540PE", "400", "26160.00", 65.40),
    ("POLYCAB26SEP9100PE", "125", "101000.00", 808.00),
]


@pytest.mark.parametrize(("symbol", "qty", "cf_sell_amt", "carried"), RAW_CARRIED_ROWS)
def test_a_leg_valued_at_the_carried_price_says_so(symbol, qty, cf_sell_amt, carried):
    """Kotak sends upldPrc "0.00" on a carried leg, so the average is its valuation."""
    position = one(trdSym=symbol, cfSellQty=qty, cfSellAmt=cf_sell_amt, upldPrc="0.00", _ltp=11.75)

    assert position["average_price"] == carried
    assert position["average_price_basis"] == "carry_forward_valuation"


def test_a_real_cost_basis_carries_no_qualifier():
    position = one(cfSellQty="50", cfSellAmt="40000.00", upldPrc="820.00", _ltp=790.0)

    assert position["average_price"] == 820.0
    assert "average_price_basis" not in position


def test_a_position_opened_today_carries_no_qualifier():
    position = one(flBuyQty="100", buyAmt="2100.00", _ltp=22.50)

    assert position["average_price"] == 21.0
    assert "average_price_basis" not in position


def test_a_closed_leg_that_was_carried_is_still_qualified():
    """average_price is 0.00 by Kotak's definition, but the P&L is today's slice.

    The leg was opened before today, so its realized P&L is measured from the
    previous settlement price and is not what the position made.
    """
    position = one(cfBuyQty="10", cfBuyAmt="450.00", flSellQty="10", sellAmt="500.00")

    assert position["quantity"] == 0
    assert position["average_price"] == 0.0
    assert position["average_price_basis"] == "carry_forward_valuation"


def test_a_closed_leg_opened_and_shut_today_is_not_qualified():
    position = one(flBuyQty="20", flSellQty="20", buyAmt="1641.00", sellAmt="1810.00")

    assert position["quantity"] == 0
    assert position["pnl"] == 169.00
    assert "average_price_basis" not in position


def test_the_qualifier_does_not_change_a_single_number():
    """The page is left exactly as it was; only the row now describes itself."""
    qualified = one(cfSellQty="3175", cfSellAmt="27305.00", upldPrc="0.00", _ltp=11.75)

    assert qualified["average_price"] == 8.60
    assert qualified["ltp"] == 11.75
    assert qualified["pnl"] == -10001.25


def test_a_leg_marked_at_the_price_it_was_carried_at_reports_plain_zero():
    """Negative zero serializes as "-0.0" and formats as "-0.00".

    26160.0 + -26160.000000000004 lands just below zero. Four of the five rows
    in #2061 are exactly this: an illiquid option whose last trade is the
    settlement price it was carried in at.
    """
    position = one(cfSellQty="400", cfSellAmt="26160.00", _ltp=65.40)

    assert position["pnl"] == 0.0
    assert str(position["pnl"]) == "0.0"
