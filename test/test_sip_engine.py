"""SIP simulation: units, value curve, cash flows, rupee-cost averaging."""
from datetime import date

import pandas as pd
import pytest

from sip.engine import SipError, run_lumpsum, run_sip


def prices(values, start="2020-01-01"):
    idx = pd.DatetimeIndex(pd.bdate_range(start, periods=len(values)))
    return pd.Series(values, index=idx, dtype=float)


def flat(n=300, price=100.0):
    return prices([price] * n)


def test_units_accumulate_at_the_close_of_each_installment():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.installment_count == 6
    assert s.total_invested == pytest.approx(60000)
    assert s.total_units == pytest.approx(600.0), "60000 / 100"


def test_value_is_units_times_price():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.final_value == pytest.approx(60000), "flat price: value == invested"
    assert (s.value.iloc[-1]) == pytest.approx(s.total_units * 100.0)


def test_cash_flows_use_xirr_convention():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    invested = [a for _, a in s.cash_flows if a < 0]
    terminal = [a for _, a in s.cash_flows if a > 0]
    assert len(invested) == 6 and all(a == -10000 for a in invested)
    assert len(terminal) == 1 and terminal[0] == pytest.approx(s.final_value)
    assert s.cash_flows[-1][0] == s.value.index[-1].date()


def test_rupee_cost_averaging_never_pays_more_than_the_average_price():
    """A mathematical property, not a market opinion: buying a fixed rupee
    amount gives a harmonic-style mean, which cannot exceed the arithmetic
    mean of the same prices. If this ever fails the unit maths is wrong."""
    volatile = prices([100, 80, 120, 60, 140, 90, 110, 70] * 40)
    s = run_sip(volatile, "X", "NSE", date(2020, 1, 1), date(2021, 6, 30), 10000)
    assert s.average_cost <= s.average_price + 1e-9
    assert s.average_cost < s.average_price, "a volatile series must show a gap"


def test_flat_prices_give_no_averaging_advantage():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.average_cost == pytest.approx(s.average_price)


def test_charges_reduce_units_not_the_invested_amount():
    """Invested is what leaves the investor; charges show up as fewer units."""
    free = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    paid = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                   brokerage_percent=1.0)
    assert paid.total_invested == free.total_invested
    assert paid.total_units < free.total_units
    # 1% of the value actually TRADED, not of the installment. At Rs 100 a
    # share a Rs 10,000 installment buys 99 whole shares (Rs 9,900) once the
    # charge is allowed for, so 1% of 9,900 per installment. Charging the full
    # installment would overstate brokerage on money that never traded.
    assert paid.charges == pytest.approx(99.0 * 6)


def test_charges_are_levied_per_installment():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                brokerage_flat=20.0)
    assert s.charges == pytest.approx(120.0), "20 x 6 installments, not 20 once"


def test_invested_curve_is_monotonic_and_ends_at_the_total():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.invested.is_monotonic_increasing
    assert s.invested.iloc[-1] == pytest.approx(s.total_invested)


def test_step_up_increases_later_installments():
    s = run_sip(flat(400), "X", "NSE", date(2020, 1, 1), date(2021, 6, 30), 10000,
                step_up_percent=10.0)
    first = s.installments[0].amount
    last = s.installments[-1].amount
    assert last > first
    assert s.total_invested > 10000 * s.installment_count * 0.99


@pytest.mark.parametrize("freq,expected_min", [
    ("weekly", 20), ("fortnightly", 10), ("monthly", 5), ("quarterly", 1),
])
def test_every_frequency_produces_installments(freq, expected_min):
    s = run_sip(flat(400), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 5000,
                frequency=freq)
    assert s.installment_count >= expected_min


def test_rejects_a_symbol_with_no_sessions_in_the_window():
    with pytest.raises(SipError, match="no trading sessions"):
        run_sip(flat(), "X", "NSE", date(2030, 1, 1), date(2030, 6, 30), 10000)


def test_rejects_a_sip_that_can_never_afford_a_share():
    """With whole shares, an installment too small to buy one is not an error
    on its own -- the cash carries forward and buys later. It is only unusable
    when nothing is ever bought."""
    px = prices([100_000.0] * 200)   # one share costs more than the whole SIP
    with pytest.raises(SipError, match="afford a single share"):
        run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 1000)


def test_lumpsum_deploys_everything_on_the_first_session():
    lump = run_lumpsum(flat(), date(2020, 1, 1), date(2020, 6, 30), 60000)
    assert lump["units"] == pytest.approx(600.0)
    assert lump["final_value"] == pytest.approx(60000)
    assert len(lump["cash_flows"]) == 2


def test_lumpsum_beats_sip_in_a_steadily_rising_market():
    """Not a bug -- the honest comparison. Money in earlier compounds longer."""
    rising = prices([100 + i for i in range(300)])
    s = run_sip(rising, "X", "NSE", date(2020, 1, 1), date(2021, 1, 31), 10000)
    lump = run_lumpsum(rising, date(2020, 1, 1), date(2021, 1, 31), s.total_invested)
    assert lump["final_value"] > s.final_value


# ---------------------------------------------------------------------------
# Statutory charges, shared with the portfolio backtester
# ---------------------------------------------------------------------------


def india_costs(exchange="NSE"):
    from services.sip_service import _build_costs

    return _build_costs(
        cost_model="indian_equity", brokerage_percent=0, brokerage_flat=0,
        cost_exchange=exchange, charge_overrides=None, gst_rate=None,
        cost_bps=0, slippage=0,
    )


def test_statutory_charges_are_levied_per_installment():
    """Not once for the SIP. Over 60 buys the difference is large, and the
    per-installment figure is what a contract note would show."""
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                costs=india_costs())
    assert s.installment_count == 6
    # Charged on the value actually traded, which whole shares make slightly
    # less than the installment. Derived, not hardcoded: a fixed number here
    # would silently re-encode the fractional-share assumption.
    traded = s.total_invested - s.cash - s.charges
    assert s.charges == pytest.approx(traded * 0.0011872, rel=5e-3)
    assert s.charges < 11.87 * 6, "charging the full installment would overstate it"


def test_charge_breakdown_itemises_every_statutory_line():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                costs=india_costs())
    for line in ("stt", "exchange_txn", "sebi", "stamp_duty", "tax"):
        assert s.charge_breakdown[line] > 0, f"{line} missing from the breakdown"
    traded = s.total_invested - s.cash - s.charges
    assert s.charge_breakdown["stt"] == pytest.approx(traded * 0.001, rel=1e-6), \
        "STT is 0.1% of the value traded, not of the money paid in"


def test_bse_and_nse_differ_only_in_the_exchange_fee():
    nse = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                  costs=india_costs("NSE"))
    bse = run_sip(flat(), "X", "BSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                  costs=india_costs("BSE"))
    assert bse.charge_breakdown["exchange_txn"] > nse.charge_breakdown["exchange_txn"]
    assert bse.charge_breakdown["stt"] == pytest.approx(nse.charge_breakdown["stt"])


def test_charges_reduce_units_so_the_drag_is_real():
    free = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    paid = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                   costs=india_costs())
    assert paid.total_invested == free.total_invested, "invested is what left the investor"
    assert paid.total_units < free.total_units
    assert paid.final_value < free.final_value


def test_lumpsum_uses_the_same_charge_model():
    """Otherwise the SIP-versus-lumpsum comparison would be rigged."""
    lump = run_lumpsum(flat(), date(2020, 1, 1), date(2020, 6, 30), 60000,
                       costs=india_costs())
    traded = lump["units"] * 100.0
    assert traded > 0
    assert lump["units"] == int(lump["units"]), "lumpsum bought fractional shares"
    # Everything is either in shares, in charges, or left as cash -- the same
    # conservation the SIP path obeys.
    expected_charge = traded * 0.0011872
    residual = 60000 - traded - expected_charge
    assert lump["final_value"] == pytest.approx(traded + residual, rel=1e-3)


# ---------------------------------------------------------------------------
# Whole shares: India has no fractional units in cash equity or ETFs
# ---------------------------------------------------------------------------


def test_only_whole_shares_are_bought():
    """A Rs 10,000 installment into a Rs 1,500 share buys 6, not 6.67.

    Not exactly 6 every month: the Rs 1,000 remainder carries, so some months
    afford 7. What must always hold is that the count is a whole number.
    """
    px = prices([1500.0] * 200)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.total_units == int(s.total_units), "fractional shares were bought"
    assert s.total_units == 40, "6 x 10,000 at 1,500, with the remainder carried"


def test_no_money_is_created_or_lost():
    """The invariant that makes the whole model trustworthy: everything paid in
    is either in shares, in charges, or still in cash."""
    px = prices([1500.0] * 200)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.total_units * 1500.0 + s.cash + s.charges == pytest.approx(
        s.total_invested
    )


def test_the_remainder_carries_forward_rather_than_being_lost():
    """Rs 1,000 left over is not discarded -- it joins the next installment and
    buys a 7th share in some months."""
    px = prices([1500.0] * 400)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 12, 31), 10000)
    assert s.total_units > 6 * s.installment_count, "carried cash never bought"
    # A single installment on its own cannot spend to the last rupee.
    one = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 1, 31), 10000)
    assert one.cash == pytest.approx(1000.0), "10,000 - 6 x 1,500"


def test_uninvested_cash_is_counted_in_the_value():
    """The investor paid it in and still holds it. Excluding it would make the
    SIP look worse than it was."""
    px = prices([1500.0] * 200)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 5, 31), 10000)
    assert s.cash > 0, "this schedule should leave a remainder"
    assert s.final_value == pytest.approx(s.total_units * 1500.0 + s.cash)
    # Flat price and no charges: you get back exactly what you put in.
    assert s.final_value == pytest.approx(s.total_invested)


def test_average_cost_is_per_share_actually_bought():
    px = prices([1500.0] * 200)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000)
    assert s.average_cost == pytest.approx(1500.0)


def test_lumpsum_also_buys_whole_shares():
    """Otherwise the comparison would hand lumpsum a fractional advantage the
    SIP is not allowed."""
    px = prices([1500.0] * 200)
    lump = run_lumpsum(px, date(2020, 1, 1), date(2020, 6, 30), 60000)
    assert lump["units"] == int(lump["units"])
    assert lump["units"] == 40, "60000 / 1500"


def test_an_expensive_share_still_accumulates():
    """A Rs 5,000 installment into a Rs 12,000 share buys nothing for two
    months, then one share in the third. Nothing is lost meanwhile."""
    px = prices([12000.0] * 400)
    s = run_sip(px, "X", "NSE", date(2020, 1, 1), date(2020, 12, 31), 5000)
    assert s.total_units >= 4, "12 x 5000 = 60000 buys 5 shares"
    assert s.total_units == int(s.total_units)
