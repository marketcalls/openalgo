# EMA9 MES experiment plan

## Phase 1: Verify mechanics

- Run on historical 1-minute MES data for at least 30 trading days.
- Confirm entries and exits are visible in the Lean order-event file.
- Confirm the strategy never carries a position past the 15:55 CT flatten.
- Run paper mode through IB with one MES contract and verify fills, reversals, and dashboard updates.

The current experimental mode enters once immediately after EMA warm-up, using price versus EMA9 for direction. Subsequent opposite EMA9 crosses exit and reverse the position; there are no stop, target, or maximum-hold exits in this mode.

## Phase 2: Evaluate whether it is worth researching

Record total trades, net P/L after commissions, profit factor, win rate, average win/loss, average hold time, maximum drawdown, daily loss distribution, and results by regular-session versus overnight hours.

The baseline should be compared with buy-and-hold MES, a no-trade result, and the same rules with realistic slippage. Do not optimize EMA/stop/target values until the baseline has enough trades across multiple market regimes.

## Current blocker

The local Lean data folder contains MES margin metadata and ES hourly/daily files, but no usable MES 1-minute history for the configured 2025 backtest window. The strategy is scaffolded and validated, but a meaningful result requires importing or downloading minute data first.
