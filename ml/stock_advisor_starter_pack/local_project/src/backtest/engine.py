from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backtest.cost_model import IndiaCashCostModel
from backtest.metrics import compute_equity_curve, compute_max_drawdown_pct, compute_sharpe_ratio


@dataclass(slots=True)
class BacktestResult:
    total_trades: int
    total_return_pct: float
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    equity_curve: pd.Series
    trade_log: pd.DataFrame


def run_backtest(
    df: pd.DataFrame,
    signal_column: str = "signal",
    stop_loss_pct: float = 0.02,
    take_profit_pct: float = 0.04,
    cost_model: IndiaCashCostModel | None = None,
) -> BacktestResult:
    working = df.copy().reset_index(drop=True)
    working["next_open"] = working["open"].shift(-1)
    trades: list[dict[str, float | int]] = []

    for idx in range(len(working) - 1):
        side = int(working.loc[idx, signal_column]) if signal_column in working.columns else 0
        if side == 0:
            continue
        entry = float(working.loc[idx + 1, "open"])
        high = float(working.loc[idx + 1, "high"])
        low = float(working.loc[idx + 1, "low"])
        close = float(working.loc[idx + 1, "close"])
        if side > 0:
            stop = entry * (1 - stop_loss_pct)
            target = entry * (1 + take_profit_pct)
            if low <= stop:
                exit_price = stop
            elif high >= target:
                exit_price = target
            else:
                exit_price = close
            gross_return = exit_price / entry - 1.0
        else:
            stop = entry * (1 + stop_loss_pct)
            target = entry * (1 - take_profit_pct)
            if high >= stop:
                exit_price = stop
            elif low <= target:
                exit_price = target
            else:
                exit_price = close
            gross_return = entry / exit_price - 1.0

        net_return = cost_model.apply(gross_return) if cost_model else gross_return
        trades.append(
            {
                "bar_index": idx,
                "side": side,
                "entry": entry,
                "exit": exit_price,
                "gross_return": gross_return,
                "net_return": net_return,
            }
        )

    trade_log = pd.DataFrame(trades)
    returns = trade_log["net_return"] if not trade_log.empty else pd.Series(dtype=float)
    equity_curve = compute_equity_curve(returns)
    return BacktestResult(
        total_trades=len(trade_log),
        total_return_pct=float(returns.sum()) if not trade_log.empty else 0.0,
        win_rate=float((returns > 0).mean()) if not trade_log.empty else 0.0,
        max_drawdown_pct=compute_max_drawdown_pct(equity_curve) if not trade_log.empty else 0.0,
        sharpe_ratio=compute_sharpe_ratio(returns) if not trade_log.empty else 0.0,
        equity_curve=equity_curve,
        trade_log=trade_log,
    )
