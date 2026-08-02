"""Running a SIP against a price series.

The simulation is deliberately literal: buy units at the close on each
execution date, accumulate, and mark the holding to market every session. No
look-ahead, no fractional-session interpolation, no assumption that money is
invested on a day the market was shut.

Everything the results page needs is derived from two things this produces --
the cash-flow list and the daily value curve. Keeping the engine to those two
outputs is what stops metric code from quietly inventing its own version of the
simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .schedule import Installment, build_schedule


class SipError(ValueError):
    """The SIP could not be simulated."""


@dataclass(frozen=True)
class SipResult:
    """A completed SIP simulation.

    ``cash_flows`` is in XIRR convention: investments negative, the closing
    value positive on the final session. That single list is the input to every
    return figure, so there is exactly one definition of what was invested and
    when.
    """

    symbol: str
    exchange: str
    #: (date, amount) -- investments negative, terminal value positive.
    cash_flows: list[tuple[date, float]]
    #: Per-session marked-to-market value of the accumulated units.
    value: pd.Series
    #: Per-session running total of money put in, for the invested-vs-value chart.
    invested: pd.Series
    #: Per-session accumulated units.
    units: pd.Series
    installments: list[Installment]
    total_invested: float
    final_value: float
    total_units: float
    #: Cost actually paid per unit, versus the simple average close over the
    #: same sessions. The gap is the rupee-cost-averaging effect.
    average_cost: float
    average_price: float
    #: Money paid in that could not buy a whole share and is still sitting in
    #: the account. Indian cash equity trades in whole shares, so a fixed rupee
    #: installment almost never spends to the last paisa.
    cash: float = 0.0
    charges: float = 0.0
    #: Per-charge totals across every installment (stt, exchange_txn, sebi,
    #: stamp_duty, brokerage, tax, slippage). Empty when a flat model is used.
    charge_breakdown: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def installment_count(self) -> int:
        return len(self.installments)


def _charge_for(
    amount: float,
    brokerage_percent: float,
    brokerage_flat: float,
    costs=None,
) -> float:
    """Cost of one installment.

    Charged per installment, not once for the whole SIP: STT, exchange and
    SEBI fees, stamp duty and GST are levied on every buy, and with 60 monthly
    installments the difference between the two treatments is large.

    ``costs`` is a ``portfolio.costs`` schedule -- the same statutory model the
    portfolio backtester uses, so a SIP and a portfolio run report the same
    charges for the same trade. Each installment is one buy order, so the
    sell leg is zero: a SIP accumulates, it does not round-trip.
    """
    if costs is not None:
        return float(costs.charge(buy_value=amount, sell_value=0.0, orders=1))
    return amount * (brokerage_percent / 100.0) + brokerage_flat


def run_sip(
    closes: pd.Series,
    symbol: str,
    exchange: str,
    start: date,
    end: date,
    amount: float,
    *,
    frequency: str = "monthly",
    day_of_month: int = 1,
    step_up_percent: float = 0.0,
    brokerage_percent: float = 0.0,
    brokerage_flat: float = 0.0,
    costs=None,
    warnings: list[str] | None = None,
) -> SipResult:
    """Simulate a SIP into one symbol.

    Args:
        closes: session closes indexed by date, ascending.
        symbol, exchange: recorded on the result for display.
        start, end: SIP window.
        amount: base installment, before step-up.
        frequency: monthly, fortnightly, weekly or quarterly.
        day_of_month: target day for monthly and quarterly SIPs.
        step_up_percent: annual increase applied on each anniversary.
        brokerage_percent, brokerage_flat: charges per installment. The
            invested amount is what leaves the investor; units are bought with
            what remains after charges, which is why cost drag shows up as a
            lower unit count rather than a separate line item.
        warnings: carried through from the price loader, e.g. suspected
            unadjusted corporate actions.

    Returns:
        A ``SipResult``.

    Raises:
        SipError: no usable price data in the window.
    """
    if closes is None or closes.empty:
        raise SipError("no price data for this symbol and period")

    series = closes.dropna().sort_index()
    if series.empty:
        raise SipError("price series is empty after dropping missing sessions")

    window = series[(series.index.date >= start) & (series.index.date <= end)]
    if window.empty:
        raise SipError(
            f"no trading sessions between {start} and {end} for {symbol}"
        )
    if (window <= 0).any():
        raise SipError("price series contains non-positive closes")

    installments = build_schedule(
        window.index,
        start,
        end,
        amount,
        frequency=frequency,
        day_of_month=day_of_month,
        step_up_percent=step_up_percent,
    )

    price_on = {d.date(): float(p) for d, p in window.items()}

    units_by_date: dict[date, float] = {}
    cash_by_date: dict[date, float] = {}
    invested_by_date: dict[date, float] = {}
    total_units = 0.0
    cash = 0.0
    total_invested = 0.0
    total_charges = 0.0
    breakdown: dict[str, float] = {}
    cash_flows: list[tuple[date, float]] = []

    for inst in installments:
        price = price_on[inst.executed]

        # India has no fractional shares: cash equity and ETFs trade in whole
        # units. A fixed rupee installment therefore almost never spends to the
        # last paisa, and what is left stays in the account and is added to the
        # next installment. Modelling this matters -- pretending you can buy
        # 6.47 shares overstates the units held and every return derived from
        # them, and the error compounds with each installment.
        budget = cash + inst.amount

        # Charges depend on the traded value, and the traded value depends on
        # how many whole shares the charges leave room for. Size the trade
        # first, then charge it, then step down a share if the charge no longer
        # fits. One step is always enough: a charge is a small fraction of a
        # share's price.
        shares = int(budget // price)
        charge = _charge_for(shares * price, brokerage_percent, brokerage_flat, costs)
        while shares > 0 and shares * price + charge > budget:
            shares -= 1
            charge = _charge_for(shares * price, brokerage_percent, brokerage_flat, costs)
        if shares == 0:
            charge = 0.0  # nothing traded, nothing charged

        spent = shares * price
        cash = budget - spent - charge
        total_units += shares
        total_invested += inst.amount
        total_charges += charge
        if costs is not None and shares:
            for key, value in costs.breakdown(
                buy_value=spent, sell_value=0.0, orders=1
            ).items():
                if key != "orders":
                    breakdown[key] = breakdown.get(key, 0.0) + float(value)
        units_by_date[inst.executed] = total_units
        cash_by_date[inst.executed] = cash
        invested_by_date[inst.executed] = total_invested
        # Negative: money leaving the investor.
        cash_flows.append((inst.executed, -inst.amount))

    # Forward-fill units and invested across every session so the value curve
    # is continuous rather than only defined on installment dates.
    units = pd.Series(
        [units_by_date.get(d.date()) for d in window.index], index=window.index
    ).ffill().fillna(0.0)
    invested = pd.Series(
        [invested_by_date.get(d.date()) for d in window.index], index=window.index
    ).ffill().fillna(0.0)

    cash_held = pd.Series(
        [cash_by_date.get(d.date()) for d in window.index], index=window.index
    ).ffill().fillna(0.0)
    value = units * window + cash_held
    final_value = float(value.iloc[-1])
    last_session = window.index[-1].date()

    # The terminal value is a single positive flow: the investor gets it all
    # back at once on the final session.
    cash_flows.append((last_session, final_value))

    # Cost per share actually acquired: everything paid in, less the charges
    # and the cash still uninvested, divided by the shares it bought.
    if total_units == 0:
        raise SipError(
            "no installment could afford a single share: the price exceeds the "
            "amount available after charges. Increase the installment."
        )

    deployed_total = total_invested - total_charges - cash
    average_cost = (deployed_total / total_units) if total_units > 0 else 0.0
    executed_prices = [price_on[i.executed] for i in installments]
    average_price = sum(executed_prices) / len(executed_prices)

    return SipResult(
        symbol=symbol,
        exchange=exchange,
        cash_flows=cash_flows,
        value=value,
        invested=invested,
        units=units,
        installments=installments,
        total_invested=total_invested,
        final_value=final_value,
        total_units=total_units,
        average_cost=average_cost,
        average_price=average_price,
        cash=cash,
        charges=total_charges,
        charge_breakdown={k: round(v, 2) for k, v in breakdown.items()},
        warnings=list(warnings or []),
    )


def run_lumpsum(
    closes: pd.Series,
    start: date,
    end: date,
    amount: float,
    *,
    brokerage_percent: float = 0.0,
    brokerage_flat: float = 0.0,
    costs=None,
) -> dict:
    """Deploy ``amount`` in one go on the first session, for comparison.

    The honest comparison against a SIP is the *same total money* invested on
    day one, not the same monthly amount. A SIP that pays in 6,00,000 over five
    years is compared against 6,00,000 invested at the start -- which is
    usually the flattering case for lumpsum in a rising market, and that is
    exactly why it is worth showing rather than hiding.
    """
    series = closes.dropna().sort_index()
    window = series[(series.index.date >= start) & (series.index.date <= end)]
    if window.empty:
        raise SipError("no sessions available for the lumpsum comparison")

    entry_price = float(window.iloc[0])
    # Whole shares here too, or the comparison would give lumpsum a fractional
    # advantage the SIP is not allowed. The unspent remainder stays as cash.
    units = int(amount // entry_price)
    charge = _charge_for(units * entry_price, brokerage_percent, brokerage_flat, costs)
    while units > 0 and units * entry_price + charge > amount:
        units -= 1
        charge = _charge_for(units * entry_price, brokerage_percent, brokerage_flat, costs)
    residual = amount - units * entry_price - charge
    value = units * window + residual
    final_value = float(value.iloc[-1])

    return {
        "invested": amount,
        "final_value": final_value,
        "units": units,
        "entry_price": entry_price,
        "entry_date": window.index[0].date(),
        "value": value,
        "cash_flows": [
            (window.index[0].date(), -amount),
            (window.index[-1].date(), final_value),
        ],
    }
