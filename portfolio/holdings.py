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


def parse_holdings(rows: list[dict]) -> list[Holding]:
    """
    Normalise a broker holdings payload.

    Brokers agree on the field names the service exposes but not on their
    types -- quantities and prices arrive as strings from several of them -- so
    every numeric is coerced rather than trusted. A row without a usable
    quantity or price is dropped: it cannot be weighted, and guessing a price
    would put a fabricated number into every downstream metric.
    """
    out: list[Holding] = []
    for row in rows or []:
        try:
            quantity = float(row.get("quantity") or 0)
            average = float(row.get("average_price") or 0)
        except (TypeError, ValueError):
            continue
        if quantity <= 0 or average <= 0:
            continue

        pnl = float(row.get("pnl") or 0)
        # `last_price` is not in every broker's holdings payload, but P&L is,
        # so the current price can be recovered from it rather than dropped.
        last = row.get("last_price")
        try:
            last_price = float(last) if last not in (None, "") else average + pnl / quantity
        except (TypeError, ValueError):
            last_price = average + pnl / quantity

        out.append(
            Holding(
                symbol=str(row.get("symbol", "")).strip().upper(),
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
            "count": 0,
        }

    invested = sum(h.invested for h in holdings)
    current = sum(h.current for h in holdings)
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
                "pnl_pct": round((h.current / h.invested - 1.0) * 100, 2) if h.invested else 0.0,
                "weight": round(weight, 5),
                "product": h.product,
            }
        )

    rows.sort(key=lambda r: r["current"], reverse=True)
    return {
        "holdings": rows,
        "weights": weights,
        "invested": round(invested, 2),
        "current": round(current, 2),
        "pnl": round(current - invested, 2),
        "pnl_pct": round((current / invested - 1.0) * 100, 2) if invested else 0.0,
        "count": len(rows),
    }
