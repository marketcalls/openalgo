"""
Crisis-period analysis: how the portfolio behaved when it mattered.

An average return says nothing about the days an investor actually remembers.
This measures the portfolio and its benchmark over named historical stress
windows, so "defensive" becomes a number rather than a claim.

Periods are **data**, not code, for the same reason the cost schedule is: they
differ by market, they get added to as history happens, and a user may want
their own. The Indian set below is the default; a global set can sit beside it
without touching the logic.

The set spans 1995 to date -- from the earliest window NSE equities can be
measured over -- but most installs hold far less history than that, and any
window with no overlap is simply dropped. A list reaching back further than the
data does costs nothing and becomes useful the moment deeper history is
ingested.

Windows that fall outside the backtest are dropped rather than clipped to
nothing, and a window only partly covered is reported as partial -- a portfolio
that existed for three days of the COVID crash did not "survive" it, and
saying so is more useful than a number that implies it did.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CrisisPeriod:
    key: str
    label: str
    start: str
    end: str
    note: str = ""
    #: ``india`` for a domestic event, ``global`` for one that arrived from
    #: outside. Both move Indian portfolios, but they say different things: a
    #: portfolio can be diversified against domestic shocks and still fully
    #: exposed to global ones.
    scope: str = "global"


# Indian equity stress windows. Dates are the commonly cited peak-to-trough (or
# event) spans; a few are recoveries rather than crashes, because how a
# portfolio participates in the rebound matters as much as how it falls.
INDIA_CRISES: tuple[CrisisPeriod, ...] = (
    # ── 1995-1999 ──────────────────────────────────────────────────────────
    #
    # NSE equities began trading in November 1994, so these are the earliest
    # windows the Indian market can be measured over at all. Treat them with
    # more caution than the rest: several were BSE-centric, index continuity
    # and corporate-action adjustment before about 2000 are poor, and few data
    # vendors carry clean daily history that far back.
    CrisisPeriod("bear_1995", "1995-96 Bear Market", "1995-01-02", "1996-01-31",
                 "The long slide after the 1994 peak", "india"),
    CrisisPeriod("asian_crisis", "Asian Financial Crisis", "1997-07-02", "1998-09-30",
                 "Baht float and the contagion that followed", "global"),
    CrisisPeriod("pokhran", "Pokhran-II Sanctions", "1998-05-11", "1998-06-30",
                 "Nuclear tests and the sanctions that followed", "india"),
    CrisisPeriod("russia_ltcm", "Russia Default / LTCM", "1998-08-03", "1998-10-30",
                 "Sovereign default and a hedge-fund collapse", "global"),
    CrisisPeriod("kargil", "Kargil Conflict", "1999-05-03", "1999-07-26",
                 "Border conflict; the market recovered before it ended", "india"),

    # ── Global shocks that reached Indian markets ──────────────────────────
    CrisisPeriod("dotcom", "Dot-com Crash", "2000-02-14", "2001-09-21",
                 "Global technology unwind", "global"),
    CrisisPeriod("gfc", "Global Financial Crisis", "2008-01-08", "2009-03-09",
                 "Nifty fell around 60% peak to trough", "global"),
    CrisisPeriod("gfc_recovery", "GFC Recovery", "2009-03-10", "2009-12-31",
                 "The snap-back off the March 2009 low", "global"),
    CrisisPeriod("nine_eleven", "9/11 Attacks", "2001-09-11", "2001-09-21",
                 "Markets shut worldwide; a sharp risk-off on reopening", "global"),
    CrisisPeriod("may_2006", "May 2006 EM Correction", "2006-05-11", "2006-06-14",
                 "Emerging markets sold off about 30% in a month", "global"),
    CrisisPeriod("subprime_2007", "2007 Subprime Tremor", "2007-07-24", "2007-08-17",
                 "The first crack before the crisis proper", "global"),
    CrisisPeriod("euro_debt", "European Debt Crisis", "2011-07-01", "2011-12-20",
                 "Sovereign contagion and a global risk-off", "global"),
    CrisisPeriod("taper_tantrum", "Taper Tantrum", "2013-05-22", "2013-08-28",
                 "Fed taper signal; the rupee hit a record low", "global"),
    CrisisPeriod("china_deval", "China Devaluation", "2015-08-11", "2016-02-11",
                 "Yuan devaluation into the early-2016 low", "global"),
    CrisisPeriod("brexit", "Brexit Vote", "2016-06-23", "2016-06-30",
                 "Referendum shock", "global"),
    CrisisPeriod("volmageddon", "Volmageddon", "2018-02-01", "2018-02-09",
                 "Short-volatility unwind", "global"),
    CrisisPeriod("q4_2018", "Q4 2018 Selloff", "2018-10-01", "2018-12-26",
                 "Global growth scare and tightening", "global"),
    CrisisPeriod("covid_crash", "COVID Crash", "2020-02-20", "2020-03-23",
                 "Fastest bear market on record", "global"),
    CrisisPeriod("covid_recovery", "COVID Recovery", "2020-03-24", "2020-12-31",
                 "Liquidity-driven rebound", "global"),
    CrisisPeriod("rate_shock_2022", "2022 Rate Shock", "2022-01-17", "2022-06-17",
                 "Global tightening and the Ukraine invasion", "global"),
    CrisisPeriod("svb", "SVB / Banking Crisis", "2023-03-08", "2023-03-24",
                 "US regional bank failures", "global"),
    CrisisPeriod("japan_carry", "Japan Carry Unwind", "2024-07-31", "2024-08-07",
                 "Yen surge forced a global deleveraging", "global"),
    CrisisPeriod("tariff_2025", "2025 Tariff Shock", "2025-04-02", "2025-04-30",
                 "Global tariff escalation", "global"),

    # ── Domestic events ────────────────────────────────────────────────────
    CrisisPeriod("ketan_parekh", "Ketan Parekh / UTI Crisis", "2001-03-01", "2001-04-30",
                 "Broker default and the freezing of US-64", "india"),
    CrisisPeriod("election_2004", "2004 Election Crash", "2004-05-14", "2004-05-28",
                 "17 May 2004: trading halted twice in one session", "india"),
    CrisisPeriod("satyam", "Satyam Scandal", "2009-01-07", "2009-01-30",
                 "Corporate governance shock", "india"),
    CrisisPeriod("demonetisation", "Demonetisation", "2016-11-08", "2016-12-26",
                 "Overnight withdrawal of 500 and 1000 rupee notes", "india"),
    CrisisPeriod("ilfs", "IL&FS / NBFC Crisis", "2018-09-01", "2018-10-26",
                 "Credit freeze across non-bank lenders", "india"),
    CrisisPeriod("yes_bank", "Yes Bank Moratorium", "2020-03-05", "2020-03-13",
                 "RBI moratorium on a major private bank", "india"),
    CrisisPeriod("adani", "Adani / Hindenburg", "2023-01-24", "2023-02-28",
                 "Index-heavy single-group drawdown", "india"),
    CrisisPeriod("election_2024", "2024 Election Shock", "2024-06-03", "2024-06-05",
                 "Counting-day reversal on an unexpected margin", "india"),
    CrisisPeriod("fii_selloff_2024", "Oct 2024 FII Selloff", "2024-09-27", "2024-11-21",
                 "Sustained foreign outflows", "india"),
)

PERIOD_SETS = {"india": INDIA_CRISES}


def _window_return(series: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """Compounded return over the sessions inside [start, end]."""
    chunk = series.loc[(series.index >= start) & (series.index <= end)]
    if len(chunk) < 2:
        return None
    return float((1.0 + chunk).prod() - 1.0)


def crisis_analysis(
    returns: pd.Series,
    benchmark: pd.Series | None = None,
    *,
    periods: tuple[CrisisPeriod, ...] = INDIA_CRISES,
    min_coverage: float = 0.6,
) -> dict:
    """
    Portfolio and benchmark returns across each stress window.

    ``min_coverage`` is the fraction of a window's calendar span that must be
    covered by the data before the result is treated as complete. Below it the
    row is still returned but flagged partial, because a portfolio that only
    overlapped the tail of a crash did not live through it.
    """
    if returns.empty:
        return {"periods": [], "summary": None}

    first, last = returns.index[0], returns.index[-1]
    rows: list[dict] = []

    for period in periods:
        start = pd.Timestamp(period.start)
        end = pd.Timestamp(period.end)
        # No overlap at all: the portfolio simply did not exist then.
        if end < first or start > last:
            continue

        covered_start = max(start, first)
        covered_end = min(end, last)
        span = (end - start).days or 1
        coverage = ((covered_end - covered_start).days or 0) / span

        port = _window_return(returns, covered_start, covered_end)
        if port is None:
            continue
        # Sessions, not calendar days: how long a crisis *felt* is measured in
        # trading days, and a two-week window spanning a long weekend is a
        # shorter ordeal than the calendar suggests.
        sessions = int(
            ((returns.index >= covered_start) & (returns.index <= covered_end)).sum()
        )
        bench = (
            _window_return(benchmark, covered_start, covered_end)
            if benchmark is not None
            else None
        )

        rows.append(
            {
                "key": period.key,
                "label": period.label,
                "note": period.note,
                "start": str(covered_start.date()),
                "end": str(covered_end.date()),
                "portfolio": port,
                "benchmark": bench,
                "excess": None if bench is None else port - bench,
                "days": int((covered_end - covered_start).days),
                "sessions": sessions,
                "coverage": round(min(coverage, 1.0), 3),
                "partial": coverage < min_coverage,
            }
        )

    for row in rows:
        row["scope"] = next(
            (p.scope for p in periods if p.key == row["key"]), "global"
        )

    complete = [r for r in rows if not r["partial"]]
    beat = [r for r in complete if r["excess"] is not None and r["excess"] > 0]
    summary = None
    if complete:
        summary = {
            "count": len(complete),
            "average_return": float(np.mean([r["portfolio"] for r in complete])),
            # Share of crises where the portfolio beat its benchmark -- the
            # question "is this defensive" reduces to this number.
            "hit_rate": (
                float(len(beat) / len(complete))
                if any(r["excess"] is not None for r in complete)
                else None
            ),
            "worst": min(r["portfolio"] for r in complete),
            "best": max(r["portfolio"] for r in complete),
            "by_scope": {
                scope: {
                    "count": len(group),
                    "average_return": float(np.mean([r["portfolio"] for r in group])),
                    "hit_rate": (
                        float(
                            len([r for r in group if (r["excess"] or 0) > 0]) / len(group)
                        )
                        if any(r["excess"] is not None for r in group)
                        else None
                    ),
                }
                for scope in ("global", "india")
                if (group := [r for r in complete if r["scope"] == scope])
            },
        }

    return {"periods": rows, "summary": summary}
