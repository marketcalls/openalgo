from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IndiaCashCostModel:
    brokerage_bps: float = 2.0
    slippage_bps: float = 3.0
    taxes_bps: float = 1.5

    def round_trip_cost_pct(self) -> float:
        return (self.brokerage_bps + self.slippage_bps + self.taxes_bps) * 2 / 10_000

    def apply(self, gross_return_pct: float) -> float:
        return gross_return_pct - self.round_trip_cost_pct()
