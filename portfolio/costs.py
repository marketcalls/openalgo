"""
Transaction costs as a composable schedule, not a fixed list of Indian taxes.

A model with fields named ``stt`` and ``stamp_duty`` is still hardcoded — it
just moves the assumption from a constant into a schema, and it cannot express
a US SEC fee (sell side only), a UK stamp duty at 0.5% (buy only, no GST), or
a per-order commission with a cap. So a schedule here is a **list of rules**,
each saying what it is charged on and whether tax applies to it, and a market
is a preset of those rules.

That makes every number a control, and adding a market a matter of data rather
than code. The India delivery preset reproduces a public brokerage calculator
exactly: buy and sell 5,000 shares at 1,000 on NSE costs 11,124.06.

Four bases cover every charge encountered so far:

- ``turnover`` — both legs (STT on delivery, exchange transaction fees)
- ``buy`` / ``sell`` — one leg only (stamp duty; the US SEC fee)
- ``order``  — a flat amount per order, or a rate on the order capped per
  order, which is how discount brokerage works

Tax (GST, VAT) is charged on the rules marked ``taxed``, never on the others,
because taxing a tax is not a thing any regime does.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite

_CHARGE_BASES = frozenset({"turnover", "buy", "sell", "order"})


@dataclass(frozen=True)
class Charge:
    """One line on a contract note."""

    key: str
    label: str
    #: ``turnover`` | ``buy`` | ``sell`` | ``order``
    basis: str
    #: Fraction of the basis value. For ``order``, a fraction of that order.
    rate: float = 0.0
    #: Flat amount per order. Only meaningful for ``basis='order'``.
    flat: float = 0.0
    #: Per-order ceiling for a rate-based order charge. 0 disables it.
    cap: float = 0.0
    #: Whether the tax below applies to this line.
    taxed: bool = False
    #: Shown in the UI so a user knows what they are editing.
    note: str = ""

    def __post_init__(self) -> None:
        if self.basis not in _CHARGE_BASES:
            raise ValueError(
                f"unknown charge basis {self.basis!r}; expected one of "
                f"{sorted(_CHARGE_BASES)}"
            )
        for name in ("rate", "flat", "cap"):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"charge {name} must be finite and non-negative")

    def amount(self, buy_value: float, sell_value: float, orders: int) -> float:
        if self.basis == "turnover":
            return (buy_value + sell_value) * self.rate
        if self.basis == "buy":
            return buy_value * self.rate
        if self.basis == "sell":
            return sell_value * self.rate
        if self.basis == "order":
            if orders <= 0:
                return 0.0
            if self.flat > 0:
                return self.flat * orders
            # Rate on each order, capped per order. The exact split across
            # orders is unknowable from aggregates, so the average is used --
            # the cap only bites on the large ones either way.
            per_order = (buy_value + sell_value) / orders
            charged = per_order * self.rate
            if self.cap > 0:
                charged = min(charged, self.cap)
            return charged * orders
        raise ValueError(f"unknown charge basis {self.basis!r}")


@dataclass(frozen=True)
class CostSchedule:
    """A market's charges, plus the tax applied on top of the taxable ones."""

    name: str
    currency: str = "INR"
    charges: tuple[Charge, ...] = ()
    tax_label: str = "GST"
    tax_rate: float = 0.0
    #: Execution gap, as a fraction of turnover. Not a charge anyone bills, but
    #: it is a real cost of trading and belongs in the same total.
    slippage: float = 0.0

    def __post_init__(self) -> None:
        for name in ("tax_rate", "slippage"):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"cost schedule {name} must be finite and non-negative")

    def breakdown(
        self, buy_value: float, sell_value: float, orders: int = 0
    ) -> dict[str, float]:
        """Itemise every line, the tax, and the total."""
        out: dict[str, float] = {}
        taxable = 0.0
        for charge in self.charges:
            value = charge.amount(buy_value, sell_value, orders)
            out[charge.key] = value
            if charge.taxed:
                taxable += value

        out["tax"] = taxable * self.tax_rate
        out["slippage"] = (buy_value + sell_value) * self.slippage
        out["total"] = sum(out.values())
        out["orders"] = float(orders)
        return out

    def charge(self, buy_value: float, sell_value: float, orders: int = 0) -> float:
        return self.breakdown(buy_value, sell_value, orders)["total"]

    def effective_rate(
        self, buy_value: float, sell_value: float, orders: int = 0
    ) -> float:
        turnover = buy_value + sell_value
        if turnover <= 0:
            return 0.0
        return self.charge(buy_value, sell_value, orders) / turnover

    def with_overrides(self, overrides: dict[str, dict]) -> CostSchedule:
        """
        Apply per-charge edits from a form: ``{"stt": {"rate": 0.00125}}``.

        Unknown keys are ignored rather than raising, so a saved portfolio does
        not break when a market's schedule gains or loses a line.
        """
        updated = []
        for charge in self.charges:
            patch = overrides.get(charge.key)
            if not patch:
                updated.append(charge)
                continue
            allowed = {
                k: float(v)
                for k, v in patch.items()
                if k in ("rate", "flat", "cap") and v is not None
            }
            updated.append(replace(charge, **allowed) if allowed else charge)
        return replace(self, charges=tuple(updated))


def india_delivery(exchange: str = "NSE") -> CostSchedule:
    """
    NSE/BSE cash delivery.

    Every rate is the published statutory schedule; the exchange transaction
    fee is the only line that differs between the two venues.
    """
    txn = 0.0000375 if exchange.upper() == "BSE" else 0.0000307
    return CostSchedule(
        name=f"India delivery ({exchange.upper()})",
        currency="INR",
        tax_label="GST",
        tax_rate=0.18,
        charges=(
            Charge(
                key="brokerage", label="Brokerage", basis="order",
                flat=0.0, cap=20.0, taxed=True,
                note="Delivery is free at most discount brokers; flat per order otherwise",
            ),
            Charge(
                key="stt", label="STT", basis="turnover", rate=0.001,
                note="0.1% on both legs of a delivery trade",
            ),
            Charge(
                key="exchange_txn", label="Exchange txn charge", basis="turnover",
                rate=txn, taxed=True,
                note="NSE 0.00307%, BSE 0.00375% of turnover",
            ),
            Charge(
                key="sebi", label="SEBI charges", basis="turnover",
                rate=10.0 / 1_00_00_000, taxed=True,
                note="Rs 10 per crore of turnover",
            ),
            Charge(
                key="stamp_duty", label="Stamp duty", basis="buy", rate=0.00015,
                note="0.015% on the buy leg only",
            ),
        ),
    )


def us_equity() -> CostSchedule:
    """
    US cash equity, as a second market to prove the shape generalises.

    Note what differs and could not be expressed by an India-shaped model: the
    SEC fee is sell-side only, FINRA's TAF is per share rather than per value,
    and there is no consumption tax on any of it.
    """
    return CostSchedule(
        name="US equity",
        currency="USD",
        tax_label="Tax",
        tax_rate=0.0,
        charges=(
            Charge(
                key="commission", label="Commission", basis="order", flat=0.0,
                note="0 at most US brokers",
            ),
            Charge(
                key="sec_fee", label="SEC fee", basis="sell", rate=0.0000278,
                note="Sell side only",
            ),
        ),
    )


PRESETS = {
    "india_delivery_nse": lambda: india_delivery("NSE"),
    "india_delivery_bse": lambda: india_delivery("BSE"),
    "us_equity": us_equity,
}


def schedule_for(name: str, overrides: dict | None = None) -> CostSchedule:
    """Build a named preset, with any per-charge overrides applied."""
    factory = PRESETS.get(name)
    if factory is None:
        raise ValueError(f"unknown cost schedule {name!r}; have {sorted(PRESETS)}")
    schedule = factory()
    return schedule.with_overrides(overrides or {})


@dataclass(frozen=True)
class EquityCosts:
    """
    Backwards-compatible wrapper over a schedule.

    Kept so existing callers and tests keep working while the engine speaks the
    generic model.
    """

    exchange: str = "NSE"
    brokerage_pct: float = 0.0
    brokerage_cap: float = 20.0
    slippage: float = 0.0
    schedule: CostSchedule = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.schedule is None:
            base = india_delivery(self.exchange)
            base = replace(base, slippage=self.slippage)
            if self.brokerage_pct:
                base = base.with_overrides(
                    {"brokerage": {"rate": self.brokerage_pct, "cap": self.brokerage_cap}}
                )
            object.__setattr__(self, "schedule", base)

    def breakdown(self, buy_value: float, sell_value: float, orders: int = 0) -> dict:
        return self.schedule.breakdown(buy_value, sell_value, orders)

    def charge(self, buy_value: float, sell_value: float, orders: int = 0) -> float:
        return self.schedule.charge(buy_value, sell_value, orders)

    def effective_rate(self, buy_value: float, sell_value: float, orders: int = 0) -> float:
        return self.schedule.effective_rate(buy_value, sell_value, orders)
