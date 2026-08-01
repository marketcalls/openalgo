"""
Analyse the portfolio someone actually holds, rather than one they typed in.

The backtester answers "what would this allocation have done". This answers the
question an investor asks about the account in front of them: what am I really
holding, is it diversified in substance, how has it behaved, and what is it
costing me.

The weights come from live positions -- quantity times price -- so the analysis
describes the portfolio as it is now, including the drift the investor never
chose. Historical behaviour is then measured by running those *current* weights
over past prices, which is a deliberate simplification worth being explicit
about: it answers "how would today's portfolio have behaved", not "how did my
account perform", because the broker does not expose when each lot was bought.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Holding:
    symbol: str
    exchange: str
    quantity: float
    average_price: float
    last_price: float
    pnl: float
    product: str = ""

    @property
    def invested(self) -> float:
        return self.quantity * self.average_price

    @property
    def current(self) -> float:
        return self.quantity * self.last_price


def _number(value: object) -> float:
    """Coerce a broker's numeric, which may arrive as a string or be absent."""
    try:
        return float(value) if value not in (None, "", "-") else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse_holdings(rows: list[dict]) -> list[Holding]:
    """
    Normalise a broker holdings payload.

    Brokers agree on the field names the service exposes but not on their
    types -- quantities and prices arrive as strings from several of them -- so
    every numeric is coerced rather than trusted.

    The only fields a row genuinely needs are **quantity and a current price**,
    because every weight is `quantity x last_price`. Average price is not
    required: several brokers (Upstox among them) return holdings with no
    average at all, and gating on it discarded entire accounts that were
    perfectly analysable. When it is missing, cost and P&L-percent are simply
    unavailable for that row; weights, exposure and the whole analysis are not.

    A current price is recovered from average plus P&L per share when the feed
    omits `last_price` but supplies both. Failing that the row is dropped --
    a position with no price cannot be weighted, and inventing one would put a
    fabricated number into every downstream metric.
    """
    out: list[Holding] = []
    for row in rows or []:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue

        quantity = _number(row.get("quantity"))
        average = _number(row.get("average_price"))
        pnl = _number(row.get("pnl"))
        last_price = _number(row.get("last_price") or row.get("ltp"))
        if not all(isfinite(value) for value in (quantity, average, pnl, last_price)):
            continue
        if quantity <= 0:
            continue

        if last_price <= 0 and average > 0:
            # No live price, but average and P&L pin it down.
            last_price = average + pnl / quantity
        if last_price <= 0:
            continue

        out.append(
            Holding(
                symbol=symbol,
                exchange=str(row.get("exchange", "NSE")).strip().upper(),
                quantity=quantity,
                average_price=average,
                last_price=last_price,
                pnl=pnl,
                product=str(row.get("product", "")),
            )
        )
    return out


def holdings_summary(holdings: list[Holding]) -> dict:
    """
    Invested, current value, and P&L, plus the weights the analysis needs.

    Weights are by **current** value, not cost. An investor's exposure is what
    a position is worth today; weighting by what it cost would understate every
    winner and overstate every loser -- exactly backwards for a risk measure.
    """
    if not holdings:
        return {
            "holdings": [],
            "weights": {},
            "invested": 0.0,
            "current": 0.0,
            "pnl": 0.0,
            "pnl_pct": 0.0,
            "has_cost_basis": False,
            "count": 0,
        }

    invested = sum(h.invested for h in holdings)
    current = sum(h.current for h in holdings)
    # A feed with no average price gives no cost basis. Report the P&L the
    # broker states rather than a percentage of zero.
    has_cost = all(h.average_price > 0 for h in holdings)
    rows = []
    weights: dict[str, float] = {}

    for h in holdings:
        weight = h.current / current if current > 0 else 0.0
        weights[h.symbol] = weight * 100.0
        rows.append(
            {
                "symbol": h.symbol,
                "exchange": h.exchange,
                "quantity": h.quantity,
                "average_price": round(h.average_price, 2),
                "last_price": round(h.last_price, 2),
                "invested": round(h.invested, 2),
                "current": round(h.current, 2),
                "pnl": round(h.pnl, 2),
                "pnl_pct": (
                    round((h.current / h.invested - 1.0) * 100, 2) if h.invested else None
                ),
                "weight": round(weight, 5),
                "product": h.product,
            }
        )

    rows.sort(key=lambda r: r["current"], reverse=True)
    return {
        "holdings": rows,
        "weights": weights,
        "invested": round(invested, 2) if has_cost else None,
        "current": round(current, 2),
        # Without a cost basis the only honest total is the P&L the broker
        # itself reports, summed.
        "pnl": round(current - invested, 2) if has_cost else round(sum(h.pnl for h in holdings), 2),
        "pnl_pct": round((current / invested - 1.0) * 100, 2) if has_cost else None,
        "has_cost_basis": has_cost,
        "count": len(rows),
    }
