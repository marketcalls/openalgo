from datetime import date

import pytest

from sip.xirr import XirrError, _npv, absolute_return, xirr, xirr_or_none


def test_matches_the_excel_xirr_reference():
    """The documented Excel XIRR example. If we disagree with a spreadsheet,
    users will trust the spreadsheet, so this is the anchor."""
    flows = [
        ("2008-01-01", -10000), ("2008-03-01", 2750), ("2008-10-30", 4250),
        ("2009-02-15", 3250), ("2009-04-01", 2750),
    ]
    assert xirr(flows) == pytest.approx(0.373362535, abs=1e-6)

def test_solved_rate_actually_zeroes_the_npv():
    """Self-validating: whatever rate comes back, the NPV at that rate must be
    zero. Catches a solver that converges on the wrong root."""
    flows = [(f"2020-{m:02d}-01", -5000) for m in range(1, 13)]
    flows.append(("2021-01-01", 64000))
    r = xirr(flows)
    parsed = sorted((date.fromisoformat(d), a) for d, a in flows)
    assert _npv(r, parsed, parsed[0][0]) == pytest.approx(0.0, abs=1e-6)

def test_a_flat_investment_returns_about_zero():
    assert xirr([("2020-01-01", -100000), ("2023-01-01", 100000)]) == pytest.approx(0.0, abs=1e-9)

def test_doubling_in_one_year_is_100_percent():
    """365 days exactly. 2020 is a leap year, so 2020-01-01 to 2021-01-01 is
    366 days and doubling over it is 99.81% -- correct, but it would make this
    test look like an off-by-something. Uses a non-leap span so the expected
    number is unambiguous."""
    assert xirr([("2021-01-01", -1000), ("2022-01-01", 2000)]) == pytest.approx(1.0, rel=1e-6)


def test_day_count_is_actual_over_365():
    """Leap years are not special-cased: a 366-day double is slightly under
    100% because it took slightly over a year. This matches Excel XIRR."""
    r = xirr([("2020-01-01", -1000), ("2021-01-01", 2000)])
    assert r == pytest.approx(2 ** (365 / 366) - 1, rel=1e-6)
    assert r < 1.0

def test_losses_give_a_negative_rate():
    r = xirr([("2020-01-01", -100000), ("2022-01-01", 60000)])
    assert -1.0 < r < 0.0

@pytest.mark.parametrize("flows,why", [
    ([], "empty"),
    ([("2020-01-01", -1000)], "one flow"),
    ([("2020-01-01", -1000), ("2020-01-01", 2000)], "same date"),
    ([("2020-01-01", -1000), ("2021-01-01", -2000)], "all outflows"),
    ([("2020-01-01", 1000), ("2021-01-01", 2000)], "all inflows"),
])
def test_undefined_inputs_raise_rather_than_invent_a_number(flows, why):
    with pytest.raises(XirrError):
        xirr(flows)

def test_xirr_or_none_returns_none_for_grid_cells():
    assert xirr_or_none([("2020-01-01", -1000)]) is None
    assert xirr_or_none([("2020-01-01", -1000), ("2021-01-01", 1100)]) is not None

def test_absolute_return():
    assert absolute_return(600000, 942310) == pytest.approx(0.5705, abs=1e-4)
    assert absolute_return(0, 100) == 0.0
