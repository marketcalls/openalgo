---
name: performance-analysis
description: Portfolio performance metrics, trade analysis, and benchmark comparison in VectorBT
metadata:
  tags: stats, metrics, sharpe, sortino, drawdown, win-rate, trades, benchmark, cagr
---

# Performance Analysis

## Full Stats

```python
pf.stats()                          # Complete performance summary
```

## Individual Metrics

```python
pf.total_return() * 100             # Total return %
pf.sharpe_ratio()                   # Sharpe ratio
pf.sortino_ratio()                  # Sortino ratio
pf.max_drawdown()                   # Maximum drawdown
pf.trades.win_rate()                # Win rate
pf.trades.count()                   # Total trades
pf.trades.profit_factor()           # Profit factor
```

## Trade Records

```python
pf.trades.records_readable          # DataFrame of all trades
pf.orders.records_readable          # DataFrame of all orders
pf.positions.records_readable       # DataFrame of all positions
```

## Equity & Cash

```python
pf.value()                          # Equity curve over time
pf.cash()                           # Cash balance over time
```

## Export Trades

```python
pf.positions.records_readable.to_csv("trades.csv", index=False)
```

## CAGR Calculation

```python
def calc_cagr(start_val, end_val, years):
    """Calculate Compound Annual Growth Rate."""
    if years <= 0 or start_val <= 0:
        return 0.0
    return (end_val / start_val) ** (1.0 / years) - 1.0
```

## Benchmark Comparison

Default benchmark: NIFTY 50 via OpenAlgo (`NSE_INDEX`). For yfinance fallback: `^NSEI` for India, `^GSPC` for US.

```python
# Primary: OpenAlgo (preferred)
df_bench = client.history(
    symbol="NIFTY", exchange="NSE_INDEX", interval=INTERVAL,
    start_date=start_date, end_date=end_date,
)
if "timestamp" in df_bench.columns:
    df_bench["timestamp"] = pd.to_datetime(df_bench["timestamp"])
    df_bench = df_bench.set_index("timestamp")
else:
    df_bench.index = pd.to_datetime(df_bench.index)
df_bench = df_bench.sort_index()
if df_bench.index.tz is not None:
    df_bench.index = df_bench.index.tz_convert(None)
bench_close = df_bench["close"].reindex(close.index).ffill().bfill()
pf_bench = vbt.Portfolio.from_holding(bench_close, init_cash=INIT_CASH, fees=0.00111, freq="1D")
```

```python
# Fallback: yfinance (if OpenAlgo not available)
import yfinance as yf

nifty = yf.download("^NSEI", start=close.index.min(), end=close.index.max(),
                    auto_adjust=True, multi_level_index=False)["Close"]
bench_rets = nifty.reindex(close.index).ffill().bfill().vbt.to_returns()
pf.returns_stats(benchmark_rets=bench_rets)
```

## Consecutive Wins/Losses Analysis

```python
def analyze_consecutive_trades(pf):
    """Analyze max consecutive wins and losses from a portfolio."""
    trades_df = pf.trades.records_readable
    if len(trades_df) == 0:
        return {}

    pnl_list = ((trades_df['Exit Price'] - trades_df['Entry Price']) > 0).tolist()

    consecutive_wins, consecutive_losses = [], []
    current_wins, current_losses = 0, 0

    for is_win in pnl_list:
        if is_win:
            if current_losses > 0:
                consecutive_losses.append(current_losses)
                current_losses = 0
            current_wins += 1
        else:
            if current_wins > 0:
                consecutive_wins.append(current_wins)
                current_wins = 0
            current_losses += 1

    if current_wins > 0:
        consecutive_wins.append(current_wins)
    if current_losses > 0:
        consecutive_losses.append(current_losses)

    return {
        'max_consecutive_wins': max(consecutive_wins) if consecutive_wins else 0,
        'max_consecutive_losses': max(consecutive_losses) if consecutive_losses else 0,
        'avg_consecutive_wins': np.mean(consecutive_wins) if consecutive_wins else 0,
        'avg_consecutive_losses': np.mean(consecutive_losses) if consecutive_losses else 0,
    }
```

## Key Metrics to Always Report

| Metric | What It Tells You |
|--------|------------------|
| Total Return | Overall P&L |
| CAGR | Annualized growth rate |
| Sharpe Ratio | Risk-adjusted return (>1 good, >2 excellent) |
| Sortino Ratio | Downside risk-adjusted return |
| Max Drawdown | Worst peak-to-trough decline |
| Win Rate | Percentage of winning trades |
| Profit Factor | Gross profit / gross loss (>1.5 good) |
| Trade Count | Number of completed trades (too few = unreliable) |
| Avg Win / Avg Loss | Reward-to-risk per trade |
