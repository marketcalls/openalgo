"""Daily risk ledger for the NIFTY weekly momentum strategy.

Tracks realized P&L, bid-marked unrealized P&L, fees, slippage, and
reserved risk on pending/open orders. Enforces the 2% daily loss ceiling.

For ₹100,000 capital:
- Hard daily loss budget: ₹2,000 (2%)
- Soft stop (stop initiating): ₹1,800 (1.8%)
- Fee/slippage reserve: ₹500
- Per-trade risk: ₹500
- Max trades: 3
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskState(str, Enum):
    READY = "READY"
    OPEN = "OPEN"
    COOLDOWN = "COOLDOWN"
    SOFT_HALTED = "SOFT_HALTED"
    HARD_HALTED = "HARD_HALTED"
    FLAT = "FLAT"


@dataclass
class TradeRecord:
    trade_id: int
    entry_time: float
    exit_time: float | None = None
    direction: str = ""        # "long" | "short"
    position_side: str = "long"  # Both calls and puts are bought in v1
    symbol: str = ""
    lots: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    realized_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    status: str = "open"       # "open" | "closed"


class RiskLedger:
    """Strategy-scoped daily risk ledger."""

    def __init__(
        self,
        capital: float = 100_000.0,
        daily_loss_budget: float = 2_000.0,
        soft_stop_pct: float = 0.9,   # Stop initiating at 90% of budget
        fee_reserve: float = 500.0,
        per_trade_risk: float = 500.0,
        max_trades: int = 3,
    ):
        self._capital = capital
        self._daily_loss_budget = daily_loss_budget
        self._soft_stop_threshold = daily_loss_budget * soft_stop_pct
        self._fee_reserve = fee_reserve
        self._per_trade_risk = per_trade_risk
        self._max_trades = max_trades

        self._trades: list[TradeRecord] = []
        self._realized_pnl = 0.0
        self._total_fees = 0.0
        self._total_slippage = 0.0
        self._unrealized_pnl = 0.0
        self._reserved_risk = 0.0  # Risk on pending/open orders
        self._state = RiskState.READY
        self._cooldown_trades_remaining = 0

    @property
    def capital(self) -> float:
        return self._capital

    @property
    def daily_loss_budget(self) -> float:
        return self._daily_loss_budget

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_fees(self) -> float:
        return self._total_fees

    @property
    def unrealized_pnl(self) -> float:
        return self._unrealized_pnl

    @property
    def reserved_risk(self) -> float:
        return self._reserved_risk

    @property
    def net_pnl(self) -> float:
        """Net P&L: realized (already net of fees/slippage) + unrealized (gross)."""
        return self._realized_pnl + self._unrealized_pnl

    @property
    def remaining_risk(self) -> float:
        """Remaining risk budget for new trades."""
        used = abs(min(0.0, self.net_pnl)) + self._reserved_risk
        return max(0.0, self._daily_loss_budget - used)

    @property
    def trade_count(self) -> int:
        return sum(trade.status != "canceled" for trade in self._trades)

    @property
    def state(self) -> RiskState:
        return self._state

    def can_enter(self) -> bool:
        if self._state in (RiskState.SOFT_HALTED, RiskState.HARD_HALTED, RiskState.FLAT, RiskState.COOLDOWN, RiskState.OPEN):
            return False
        if self.trade_count >= self._max_trades:
            return False
        if self.remaining_risk < self._per_trade_risk:
            return False
        return True

    def open_trade(
        self,
        trade_id: int,
        timestamp: float,
        direction: str,
        symbol: str,
        lots: int,
        entry_price: float,
        reserved_risk: float,
        position_side: str = "long",
    ) -> TradeRecord:
        if not self.can_enter():
            raise RuntimeError(f"Cannot enter trade: state={self._state}, trades={self.trade_count}, remaining_risk={self.remaining_risk}")

        trade = TradeRecord(
            trade_id=trade_id,
            entry_time=timestamp,
            direction=direction,
            position_side=position_side,
            symbol=symbol,
            lots=lots,
            entry_price=entry_price,
            status="open",
        )
        self._trades.append(trade)
        self._reserved_risk = reserved_risk
        self._state = RiskState.OPEN
        return trade

    def update_open_trade(self, trade_id: int, entry_price: float, quantity: int) -> TradeRecord:
        """Apply the latest cumulative entry-fill state to an open trade."""
        trade = self._find_open_trade(trade_id)
        if entry_price <= 0 or quantity <= 0:
            raise ValueError("entry price and quantity must be positive")
        trade.entry_price = entry_price
        trade.lots = quantity
        return trade

    def cancel_trade(self, trade_id: int) -> TradeRecord:
        """Release an entry reservation after an order cancels without a fill."""
        trade = self._find_open_trade(trade_id)
        was_forced_flat = self._state == RiskState.FLAT
        trade.status = "canceled"
        self._reserved_risk = 0.0
        self._unrealized_pnl = 0.0
        self._state = RiskState.FLAT if was_forced_flat else RiskState.READY
        return trade

    def update_unrealized(self, bid_price: float, lots: int, direction: str, entry_price: float) -> None:
        if direction == "long":
            self._unrealized_pnl = (bid_price - entry_price) * lots
        else:
            self._unrealized_pnl = (entry_price - bid_price) * lots

        # Check soft/hard halt
        net = self.net_pnl
        if net <= -self._daily_loss_budget:
            self._state = RiskState.HARD_HALTED
        elif net <= -self._soft_stop_threshold:
            self._state = RiskState.SOFT_HALTED

    def close_trade(
        self,
        trade_id: int,
        exit_time: float,
        exit_price: float,
        fees: float = 0.0,
        slippage: float = 0.0,
    ) -> TradeRecord:
        trade = self._find_open_trade(trade_id)
        was_forced_flat = self._state == RiskState.FLAT

        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.fees = fees
        trade.slippage = slippage

        if trade.position_side == "long":
            pnl = (exit_price - trade.entry_price) * trade.lots
        else:
            pnl = (trade.entry_price - exit_price) * trade.lots
        trade.realized_pnl = pnl - fees - slippage

        self._realized_pnl += trade.realized_pnl
        self._total_fees += fees
        self._total_slippage += slippage
        self._unrealized_pnl = 0.0
        self._reserved_risk = 0.0
        trade.status = "closed"

        # Check halt
        net = self.net_pnl
        if was_forced_flat:
            self._state = RiskState.FLAT
        elif net <= -self._daily_loss_budget:
            self._state = RiskState.HARD_HALTED
        elif net <= -self._soft_stop_threshold:
            self._state = RiskState.SOFT_HALTED
        else:
            self._state = RiskState.COOLDOWN

        return trade

    def _find_open_trade(self, trade_id: int) -> TradeRecord:
        for trade in self._trades:
            if trade.trade_id == trade_id and trade.status == "open":
                return trade
        raise RuntimeError(f"No open trade {trade_id}")

    def end_cooldown(self) -> None:
        if self._state == RiskState.COOLDOWN:
            self._state = RiskState.READY

    def force_flat(self) -> None:
        self._state = RiskState.FLAT

    def is_halted(self) -> bool:
        return self._state in (RiskState.SOFT_HALTED, RiskState.HARD_HALTED, RiskState.FLAT)

    def summary(self) -> dict:
        return {
            "state": self._state.value,
            "capital": self._capital,
            "realized_pnl": round(self._realized_pnl, 2),
            "unrealized_pnl": round(self._unrealized_pnl, 2),
            "total_fees": round(self._total_fees, 2),
            "total_slippage": round(self._total_slippage, 2),
            "net_pnl": round(self.net_pnl, 2),
            "remaining_risk": round(self.remaining_risk, 2),
            "trade_count": self.trade_count,
            "max_trades": self._max_trades,
        }
