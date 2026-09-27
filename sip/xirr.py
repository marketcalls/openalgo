"""Extended internal rate of return for dated, irregular cash flows.

A SIP has money going in on many dates and one value coming out at the end.
CAGR cannot describe that: it assumes a single amount compounding for the whole
period, so an installment paid in month 60 would be credited with five years of
growth it never had. XIRR is the rate that makes the present value of every
dated flow sum to zero, which is the only return figure that respects *when*
each rupee arrived.

The solver is deliberate about the cases where XIRR does not exist, because a
backtester that silently returns a plausible-looking number for an undefined
input is worse than one that says "undefined".
"""

from __future__ import annotations

import math
from datetime import date, datetime

DAYS_PER_YEAR = 365.0

# Rates outside this range are not meaningful for an investment product and are
# usually a sign of a degenerate cash-flow series (a few days of holding, or a
# near-total loss). Bracketing here keeps the solver from wandering into
# regions where (1 + r) ** t overflows.
MIN_RATE = -0.9999
MAX_RATE = 100.0


class XirrError(ValueError):
    """XIRR is not defined for the given cash flows."""


def _to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _npv(rate: float, flows: list[tuple[date, float]], t0: date) -> float:
    """Net present value of ``flows`` discounted at ``rate``.

    Uses ``(1 + rate) ** years`` rather than continuous compounding so the
    result matches what spreadsheet XIRR reports, which is what a user will
    compare it against.
    """
    total = 0.0
    for when, amount in flows:
        years = (when - t0).days / DAYS_PER_YEAR
        total += amount / ((1.0 + rate) ** years)
    return total


def xirr(cash_flows: list[tuple[object, float]]) -> float:
    """Solve for the annualised rate that zeroes the NPV of ``cash_flows``.

    Args:
        cash_flows: ``(date, amount)`` pairs. Investments are negative (money
            leaving the investor), redemptions and the closing value positive.
            Order does not matter; dates need not be regular.

    Returns:
        The annualised rate as a fraction: ``0.142`` for 14.2%.

    Raises:
        XirrError: when XIRR is genuinely undefined — fewer than two flows, all
            flows the same sign, every flow on one date, or no root inside a
            sane rate range.

    The sign-change requirement is not a solver limitation, it is arithmetic:
    if no money ever comes back there is no rate at which the series breaks
    even, and any number returned would be an invention.
    """
    flows = [(_to_date(when), float(amount)) for when, amount in cash_flows]
    flows = [(d, a) for d, a in flows if a != 0.0]

    if len(flows) < 2:
        raise XirrError("XIRR needs at least two non-zero cash flows")

    flows.sort(key=lambda item: item[0])
    t0 = flows[0][0]

    if flows[-1][0] == t0:
        raise XirrError("XIRR needs cash flows on at least two different dates")

    has_negative = any(a < 0 for _, a in flows)
    has_positive = any(a > 0 for _, a in flows)
    if not (has_negative and has_positive):
        direction = "all outflows" if has_negative else "all inflows"
        raise XirrError(
            f"XIRR is undefined for {direction}: the series never crosses zero"
        )

    def f(rate: float) -> float:
        return _npv(rate, flows, t0)

    # Brent's method on a bracket. Preferred over Newton because NPV is very
    # flat for long series -- a Newton step can jump past -100% into a region
    # where (1 + r) is negative and the powers become complex.
    lo, hi = MIN_RATE, MAX_RATE
    try:
        f_lo, f_hi = f(lo), f(hi)
    except (OverflowError, ZeroDivisionError) as exc:
        raise XirrError(f"cash flows produced an unsolvable NPV: {exc}") from exc

    if not (math.isfinite(f_lo) and math.isfinite(f_hi)):
        raise XirrError("NPV is not finite at the bracket edges")

    if f_lo * f_hi > 0:
        # No sign change across the whole sane range: the true rate lies outside
        # it, which for an investment product means the input is degenerate.
        raise XirrError(
            f"no rate between {MIN_RATE:.0%} and {MAX_RATE:.0%} zeroes the NPV; the cash flows "
            "are likely degenerate (a very short period, or a near-total loss)"

        )

    try:
        from scipy.optimize import brentq

        return float(brentq(f, lo, hi, xtol=1e-10, maxiter=200))
    except ImportError:
        pass
    except (ValueError, RuntimeError) as exc:
        raise XirrError(f"solver failed to converge: {exc}") from exc

    # Bisection fallback, so a missing scipy degrades to slower rather than
    # broken. 200 halvings of the bracket is far tighter than any display
    # precision we use.
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < 1e-10 or (hi - lo) < 1e-12:
            return float(mid)
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return float((lo + hi) / 2.0)


def xirr_or_none(cash_flows: list[tuple[object, float]]) -> float | None:
    """``xirr`` that returns ``None`` instead of raising.

    For grid computations -- the start-date and duration heatmaps -- where some
    cells are legitimately undefined and the grid should render with a gap
    rather than fail as a whole.
    """
    try:
        return xirr(cash_flows)
    except XirrError:
        return None


def absolute_return(invested: float, current_value: float) -> float:
    """Total gain as a fraction of what was put in.

    Reported alongside XIRR because they answer different questions: absolute
    return is what the account statement shows, XIRR is what it means per year.
    A long SIP with a large absolute return and a mediocre XIRR is a common and
    genuinely useful thing to see.
    """
    if invested <= 0:
        return 0.0
    return (current_value - invested) / invested
