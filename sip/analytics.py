"""Metrics for a completed SIP.

Two rules shape this module.

**Cash-flow metrics, not price metrics.** A SIP's value curve rises partly
because money was added to it. Sharpe, Sortino and CAGR computed on that curve
describe the deposit schedule as much as the investment, so they are not here.
What is here is measured either from the dated cash flows (XIRR and its
variants) or from quantities an investor can actually check against a statement.

**Report what an investor would ask.** "How long was I underwater?" is a more
useful number than annualised volatility, and almost nobody publishes it.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .engine import SipResult, run_lumpsum, run_sip
from .xirr import absolute_return, xirr_or_none

#: Rolling-window lengths offered, in years. Anything longer than the available
#: history is skipped rather than reported from a partial window.
ROLLING_YEARS = (1, 3, 5, 7, 10)

#: Cap on grid cells so a long history cannot turn one request into thousands
#: of simulations.
MAX_GRID_CELLS = 900


def _f(value) -> float | None:
    """Finite float, or None. JSON has no NaN and charts render None as a gap."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if pd.notna(out) and abs(out) != float("inf") else None


def headline(result: SipResult) -> dict:
    """The numbers that belong at the top of the page.

    Deliberately small. A reader who takes only these away should still have an
    accurate picture: what went in, what it became, and the rate that respects
    when each installment arrived.
    """
    rate = xirr_or_none(result.cash_flows)
    gain = result.final_value - result.total_invested
    return {
        "invested": _f(result.total_invested),
        "final_value": _f(result.final_value),
        "gain": _f(gain),
        "multiple": _f(result.final_value / result.total_invested)
        if result.total_invested
        else None,
        "xirr": _f(rate),
        "absolute_return": _f(absolute_return(result.total_invested, result.final_value)),
        "installments": result.installment_count,
        "units": _f(result.total_units),
        "average_cost": _f(result.average_cost),
        "average_price": _f(result.average_price),
        # Negative means each unit cost less than the average price paid over
        # the same dates -- the rupee-cost-averaging effect, quantified.
        "cost_advantage": _f(
            (result.average_cost - result.average_price) / result.average_price
        )
        if result.average_price
        else None,
        "charges": _f(result.charges),
        # India has no fractional shares, so a fixed rupee installment leaves a
        # remainder. It is the investor's money and sits in the account.
        "cash": _f(result.cash),
        "start": str(result.value.index[0].date()),
        "end": str(result.value.index[-1].date()),
        "years": _f((result.value.index[-1] - result.value.index[0]).days / 365.0),
    }


def underwater(result: SipResult) -> dict:
    """How long the portfolio was worth less than the money put into it.

    This is the number that makes people abandon a SIP, and it is almost never
    reported. Measured against *invested*, not against a previous peak: an
    investor does not compare today with the high, they compare it with what
    they have paid in.
    """
    below = result.value < result.invested
    sessions_below = int(below.sum())
    total = int(len(below))

    longest, current, longest_end = 0, 0, None
    for when, flag in below.items():
        if flag:
            current += 1
            if current > longest:
                longest, longest_end = current, when
        else:
            current = 0

    # .where rather than .replace(0, pd.NA): the latter promotes the Series to
    # object dtype, which makes every downstream fillna a deprecated downcast.
    gap = (result.value - result.invested) / result.invested.where(result.invested != 0)
    worst_gap = _f(gap.min())

    return {
        "sessions_below": sessions_below,
        "sessions_total": total,
        "share_below": _f(sessions_below / total) if total else None,
        "longest_streak_sessions": longest,
        "longest_streak_ended": str(longest_end.date()) if longest_end is not None else None,
        "worst_shortfall": worst_gap,
        "ever_underwater": bool(sessions_below),
    }


def drawdown(result: SipResult) -> dict:
    """Peak-to-trough on the value curve, with recovery time.

    Kept alongside ``underwater`` because they answer different questions: a
    drawdown is how far the holding fell from its best, while underwater is
    whether it fell below cost. In a SIP the first can be severe while the
    second never happens.
    """
    value = result.value
    peak = value.cummax()
    dd = (value - peak) / peak.where(peak != 0)

    trough_at = dd.idxmin() if len(dd.dropna()) else None
    max_dd = _f(dd.min())

    recovery_sessions = None
    if trough_at is not None:
        peak_value = float(peak.loc[trough_at])
        after = value.loc[trough_at:]
        recovered = after[after >= peak_value]
        if len(recovered):
            recovery_sessions = int(
                value.index.get_loc(recovered.index[0]) - value.index.get_loc(trough_at)
            )

    return {
        "max_drawdown": max_dd,
        "trough_date": str(trough_at.date()) if trough_at is not None else None,
        "recovery_sessions": recovery_sessions,
        "recovered": recovery_sessions is not None,
        "curve": [
            {"date": str(d.date()), "value": _f(v)}
            for d, v in dd.items()
        ],
    }


def _sip_xirr(closes: pd.Series, start: date, end: date, amount: float, **kw) -> float | None:
    try:
        r = run_sip(closes, "x", "x", start, end, amount, **kw)
    except Exception:  # noqa: BLE001 - a blank grid cell is the right answer
        return None
    return xirr_or_none(r.cash_flows)


def rolling_xirr(
    closes: pd.Series,
    amount: float,
    *,
    years: tuple[int, ...] = ROLLING_YEARS,
    step_months: int = 3,
    **sip_kw,
) -> list[dict]:
    """XIRR of every SIP window of each length, stepped through history.

    Answers the question a single headline XIRR cannot: "what if I had started
    at a bad time?" A strategy whose 5-year windows range from 4% to 22% is a
    different proposition from one that ranges from 11% to 14%, at identical
    average.
    """
    if closes.empty:
        return []

    first = closes.index[0].date()
    last = closes.index[-1].date()
    out = []

    for span in years:
        points = []
        cursor = first
        while True:
            try:
                end = date(cursor.year + span, cursor.month, min(cursor.day, 28))
            except ValueError:
                break
            if end > last:
                break
            rate = _sip_xirr(closes, cursor, end, amount, **sip_kw)
            if rate is not None:
                points.append({"start": str(cursor), "end": str(end), "xirr": _f(rate)})
            month = cursor.month - 1 + step_months
            cursor = date(cursor.year + month // 12, month % 12 + 1, min(cursor.day, 28))

        if not points:
            continue
        rates = [p["xirr"] for p in points if p["xirr"] is not None]
        out.append({
            "years": span,
            "windows": len(points),
            "points": points,
            "best": _f(max(rates)) if rates else None,
            "worst": _f(min(rates)) if rates else None,
            "median": _f(pd.Series(rates).median()) if rates else None,
            "positive_share": _f(sum(1 for r in rates if r > 0) / len(rates))
            if rates else None,
        })
    return out


def start_date_heatmap(
    closes: pd.Series,
    amount: float,
    *,
    durations: tuple[int, ...] = (1, 3, 5, 7, 10),
    **sip_kw,
) -> dict:
    """Start month down, holding period across, XIRR in the cells.

    The most useful grid for a SIP: it shows at a glance whether entry timing
    mattered, and how quickly that mattering fades as the horizon lengthens.
    """
    if closes.empty:
        return {"rows": [], "columns": [], "values": []}

    first, last = closes.index[0].date(), closes.index[-1].date()
    starts = []
    cursor = date(first.year, first.month, 1)
    while cursor <= last:
        starts.append(cursor)
        cursor = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)

    usable = [d for d in durations if d]
    while starts and len(starts) * len(usable) > MAX_GRID_CELLS:
        starts = starts[::2]

    values = []
    for s in starts:
        row = []
        for span in usable:
            try:
                end = date(s.year + span, s.month, 1)
            except ValueError:
                row.append(None)
                continue
            row.append(_f(_sip_xirr(closes, s, min(end, last), amount, **sip_kw))
                       if end <= last else None)
        values.append(row)

    return {
        "rows": [s.strftime("%b %Y") for s in starts],
        "columns": [f"{d}Y" for d in usable],
        "values": values,
    }


def sip_date_heatmap(
    closes: pd.Series, start: date, end: date, amount: float, **sip_kw
) -> dict:
    """XIRR by day-of-month, 1st through 28th.

    Settles the "which date should I SIP on?" argument with evidence. The
    answer is almost always "it barely matters", and showing that is more
    useful than leaving people to guess.
    """
    kw = {k: v for k, v in sip_kw.items() if k != "day_of_month"}
    days, rates = [], []
    for day in range(1, 29):
        rate = _sip_xirr(closes, start, end, amount, day_of_month=day, **kw)
        days.append(day)
        rates.append(_f(rate))

    clean = [r for r in rates if r is not None]
    return {
        "days": days,
        "values": rates,
        "best_day": days[rates.index(max(clean))] if clean else None,
        "worst_day": days[rates.index(min(clean))] if clean else None,
        "spread": _f(max(clean) - min(clean)) if clean else None,
    }


def frequency_comparison(
    closes: pd.Series, start: date, end: date, monthly_amount: float, **sip_kw
) -> list[dict]:
    """The same yearly outlay, paid weekly, fortnightly, monthly or quarterly.

    Amounts are scaled so every frequency invests roughly the same money per
    year -- otherwise a weekly SIP of the monthly amount simply invests four
    times as much and "wins" for a reason that has nothing to do with
    frequency.
    """
    kw = {k: v for k, v in sip_kw.items() if k != "frequency"}
    per_year = {"weekly": 52, "fortnightly": 26, "monthly": 12, "quarterly": 4}
    annual = monthly_amount * 12

    out = []
    for freq, count in per_year.items():
        amount = annual / count
        try:
            r = run_sip(closes, "x", "x", start, end, amount, frequency=freq, **kw)
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "frequency": freq,
            "amount_per_installment": _f(amount),
            "installments": r.installment_count,
            "invested": _f(r.total_invested),
            "final_value": _f(r.final_value),
            "xirr": _f(xirr_or_none(r.cash_flows)),
            "average_cost": _f(r.average_cost),
            "charges": _f(r.charges),
        })
    return out


def yearly_breakdown(result: SipResult) -> list[dict]:
    """Per calendar year: invested, closing value, and the gain attributable.

    The table people actually scan before reading anything else.
    """
    df = pd.DataFrame({"value": result.value, "invested": result.invested})
    out = []
    for year, chunk in df.groupby(df.index.year):
        opening_value = float(chunk["value"].iloc[0])
        opening_invested = float(chunk["invested"].iloc[0])
        closing_value = float(chunk["value"].iloc[-1])
        closing_invested = float(chunk["invested"].iloc[-1])
        added = closing_invested - opening_invested
        out.append({
            "year": int(year),
            "invested_during_year": _f(added),
            "invested_to_date": _f(closing_invested),
            "value": _f(closing_value),
            "gain": _f(closing_value - closing_invested),
            # Growth of the money that was already there plus what came in.
            "change": _f(closing_value - opening_value - added),
        })
    return out


def monthly_value_heatmap(result: SipResult) -> dict:
    """Year down, month across: the market's contribution, close to close.

    Two deliberate choices.

    **Close to close, never open to close.** Each cell compares this month's
    closing value with the *previous month's closing value* -- month-end to
    month-end. Resampling with ``.last()`` takes the final session of each
    month, so consecutive cells are contiguous: no gap is skipped and no
    intramonth open is used as a base. An open-to-close return would silently
    discard the overnight and weekend moves between months.

    **The installment is subtracted.** Raw value change would mostly show the
    money paid in, not what the market did. Removing the contribution leaves
    the part attributable to price.

    The first month is ``None``, not zero: with no prior close there is no
    close-to-close return to report, and printing 0% would claim a flat month
    that was never measured.
    """
    df = pd.DataFrame({"value": result.value, "invested": result.invested})
    # .last() = the closing value of the final session in each month.
    monthly = df.resample("ME").last()

    prior_close = monthly["value"].shift(1)
    prior_invested = monthly["invested"].shift(1)

    # Money added between the two closes, so it is not counted as performance.
    added = monthly["invested"] - prior_invested
    market = (monthly["value"] - prior_close) - added

    # .where rather than .replace(0, pd.NA): the latter promotes the Series to
    # object dtype, and object-dtype fillna is a deprecated downcast. A zero
    # prior close is real -- it happens when a whole month ends before the
    # first installment -- so it must be handled, not assumed away.
    base = prior_close.where(prior_close != 0)
    pct = market / base

    grid: dict[int, list] = {}
    for when, val in pct.items():
        grid.setdefault(when.year, [None] * 12)[when.month - 1] = _f(val)

    return {
        "years": [str(y) for y in sorted(grid)],
        "columns": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "values": [grid[y] for y in sorted(grid)],
        "basis": "close-to-close, contribution removed",
    }


def lumpsum_comparison(
    closes: pd.Series, result: SipResult, start: date, end: date, **kw
) -> dict | None:
    """The same total money deployed on day one.

    Included because it is the comparison a SIP investor is entitled to see,
    even when it is unflattering. In a market that rose steadily, lumpsum wins,
    and hiding that would make the tool an advertisement rather than a
    backtester.
    """
    try:
        lump = run_lumpsum(closes, start, end, result.total_invested, **kw)
    except Exception:  # noqa: BLE001
        return None
    return {
        "invested": _f(lump["invested"]),
        "final_value": _f(lump["final_value"]),
        "xirr": _f(xirr_or_none(lump["cash_flows"])),
        "entry_price": _f(lump["entry_price"]),
        "entry_date": str(lump["entry_date"]),
        "sip_final_value": _f(result.final_value),
        "difference": _f(lump["final_value"] - result.final_value),
        "sip_won": bool(result.final_value > lump["final_value"]),
    }
