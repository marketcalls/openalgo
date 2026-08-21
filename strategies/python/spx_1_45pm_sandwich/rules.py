"""Pure trade-selection rules for the SPX 1:45 PM Sandwich strategy."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class CondorStrikes:
    long_put: float
    short_put: float
    short_call: float
    long_call: float


@dataclass(frozen=True)
class CreditMetrics:
    credit: float
    defined_risk: float
    reward_risk_ratio: float
    max_loss_dollars: float


def nearest_grid(value: float, grid: float = 5.0) -> float:
    """Round to the nearest option strike grid, using half-up behavior."""
    return floor((float(value) / grid) + 0.5) * grid


def build_strikes(reference_price: float, grid: float = 5.0, wing: float = 5.0) -> CondorStrikes:
    """Build the observed long/short $5-grid iron-condor structure."""
    center = nearest_grid(reference_price, grid)
    short_put = center - grid
    short_call = center + grid
    return CondorStrikes(
        long_put=short_put - wing,
        short_put=short_put,
        short_call=short_call,
        long_call=short_call + wing,
    )


def calculate_credit_metrics(
    short_put_bid: float,
    short_call_bid: float,
    long_put_ask: float,
    long_call_ask: float,
    wing_width: float = 5.0,
    contract_multiplier: float = 100.0,
) -> CreditMetrics | None:
    """Calculate conservative executable credit and defined risk."""
    credit = float(short_put_bid) + float(short_call_bid) - float(long_put_ask) - float(long_call_ask)
    defined_risk = float(wing_width) - credit
    if credit <= 0 or defined_risk <= 0:
        return None
    return CreditMetrics(
        credit=credit,
        defined_risk=defined_risk,
        reward_risk_ratio=credit / defined_risk,
        max_loss_dollars=defined_risk * contract_multiplier,
    )
