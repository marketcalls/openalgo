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
    assert paid.charges == pytest.approx(600.0), "1% of 60000"


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


def test_rejects_charges_larger_than_the_installment():
    with pytest.raises(SipError, match="charges exceed"):
        run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 100,
                brokerage_flat=500.0)


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
    # STT 0.1% + stamp 0.015% + exchange + SEBI + GST on the taxed lines.
    assert s.charges == pytest.approx(11.87 * 6, rel=1e-3)


def test_charge_breakdown_itemises_every_statutory_line():
    s = run_sip(flat(), "X", "NSE", date(2020, 1, 1), date(2020, 6, 30), 10000,
                costs=india_costs())
    for line in ("stt", "exchange_txn", "sebi", "stamp_duty", "tax"):
        assert s.charge_breakdown[line] > 0, f"{line} missing from the breakdown"
    assert s.charge_breakdown["stt"] == pytest.approx(60.0), "0.1% of 60,000"


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
    charged = 60000 - lump["units"] * 100.0
    assert charged > 0
    assert charged == pytest.approx(71.22, rel=1e-2), "one buy of 60,000"
