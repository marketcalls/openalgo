"""What a SIP begun around a crisis would have returned.

A lumpsum investor asks "how far did it fall?". A SIP investor is asking
something different and more useful: **was starting into the fall a mistake?**

For a lumpsum the answer is obvious -- buying before a crash is worse than
buying after it. For a SIP it frequently inverts, because a SIP started into a
falling market spends the whole decline accumulating cheap units, while one
started after the recovery pays post-rebound prices from its first installment.
That inversion is counterintuitive enough to be worth measuring rather than
asserting, and it is the single most useful thing this page can tell someone
who is afraid to begin.

So each crisis is run two ways, from the same price history to the same end
date, differing only in when the first installment lands:

* **Started into it** -- the first installment falls on the crisis start.
* **Waited for the dust** -- the first installment falls on the crisis end.

Both are then held to the end of the available data, so the comparison is like
for like: the same money per month, the same finish, only the beginning moved.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from portfolio.crisis import INDIA_CRISES

from .engine import SipError, run_sip
from .xirr import xirr_or_none

#: A window shorter than this leaves too few installments for a monthly SIP to
#: mean anything -- a two-week crash produces one buy, and one buy is a
#: lumpsum, not a plan.
MIN_SIP_DAYS = 120


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if pd.notna(out) and abs(out) != float("inf") else None


def _run(closes: pd.Series, start: date, end: date, amount: float, sip_kw: dict) -> dict | None:
    try:
        r = run_sip(closes, "x", "x", start, end, amount, **sip_kw)
    except (SipError, Exception):  # noqa: BLE001 - a missing case is a gap, not a failure
        return None
    return {
        "start": str(start),
        "invested": _f(r.total_invested),
        "final_value": _f(r.final_value),
        "installments": r.installment_count,
        "xirr": _f(xirr_or_none(r.cash_flows)),
        "multiple": _f(r.final_value / r.total_invested) if r.total_invested else None,
        "absolute_return": _f(
            (r.final_value - r.total_invested) / r.total_invested
        ) if r.total_invested else None,
        "average_cost": _f(r.average_cost),
    }


def crisis_sip_analysis(
    closes: pd.Series,
    amount: float,
    *,
    periods=INDIA_CRISES,
    sip_kw: dict | None = None,
) -> list[dict]:
    """For each crisis the data covers, compare starting into it with waiting.

    Args:
        closes: session closes, ascending.
        amount: the installment.
        periods: crisis windows; defaults to the Indian set the portfolio
            backtester uses, so both tools name the same events.
        sip_kw: frequency, day_of_month, step_up_percent, costs.

    Returns:
        One entry per crisis that the price history actually covers, newest
        first. Windows the data does not reach are dropped rather than reported
        from partial history -- a SIP that existed for three days of the COVID
        crash did not live through it, and saying otherwise would be worse than
        saying nothing.
    """
    if closes is None or closes.empty:
        return []

    kw = dict(sip_kw or {})
    first = closes.index[0].date()
    last = closes.index[-1].date()

    out: list[dict] = []
    for period in periods:
        c_start = date.fromisoformat(period.start)
        c_end = date.fromisoformat(period.end)

        # The whole window must be inside the data, and there must be enough
        # runway after it for both variants to accumulate.
        if c_start < first or c_end > last:
            continue
        if (last - c_end).days < MIN_SIP_DAYS:
            continue

        into_it = _run(closes, c_start, last, amount, kw)
        waited = _run(closes, c_end, last, amount, kw)
        if into_it is None or waited is None:
            continue

        # What the market itself did across the window, for context: a SIP
        # result is easier to read next to the fall that produced it.
        window = closes[(closes.index.date >= c_start) & (closes.index.date <= c_end)]
        if len(window) >= 2:
            move = float(window.iloc[-1] / window.iloc[0] - 1.0)
            trough = float(window.min() / window.iloc[0] - 1.0)
        else:
            move = trough = None

        into_x, waited_x = into_it["xirr"], waited["xirr"]
        out.append({
            "key": period.key,
            "label": period.label,
            "note": period.note,
            "scope": period.scope,
            "crisis_start": period.start,
            "crisis_end": period.end,
            "market_move": _f(move),
            "market_trough": _f(trough),
            "started_into_it": into_it,
            "waited_for_the_end": waited,
            # Positive means starting into the crisis beat waiting -- which is
            # the usual result, and the point of showing this at all.
            "xirr_advantage": _f(into_x - waited_x)
            if (into_x is not None and waited_x is not None) else None,
            "starting_early_won": bool(
                into_x is not None and waited_x is not None and into_x > waited_x
            ),
        })

    out.sort(key=lambda row: row["crisis_start"], reverse=True)
    return out


def crisis_summary(rows: list[dict]) -> dict:
    """One line for the top of the panel.

    Counting how often starting into a crisis beat waiting is the honest way to
    present this: it is a tendency in the data, not a law, and a reader should
    see the score rather than a claim.
    """
    scored = [r for r in rows if r["xirr_advantage"] is not None]
    if not scored:
        return {"crises": 0, "early_wins": 0, "share": None, "median_advantage": None}

    wins = sum(1 for r in scored if r["starting_early_won"])
    advantages = sorted(r["xirr_advantage"] for r in scored)
    mid = len(advantages) // 2
    median = (
        advantages[mid]
        if len(advantages) % 2
        else (advantages[mid - 1] + advantages[mid]) / 2
    )
    return {
        "crises": len(scored),
        "early_wins": wins,
        "share": _f(wins / len(scored)),
        "median_advantage": _f(median),
    }
