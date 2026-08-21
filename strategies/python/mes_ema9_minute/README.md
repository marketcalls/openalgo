# MES EMA9 minute strategy

This is a deliberately simple research and paper-trading experiment for the Micro E-mini S&P 500 future (MES).

Rules:

- Resolution: 1-minute bars.
- Entry: immediately after warm-up, go long when close is at/above EMA9 and short otherwise.
- Position: one MES contract by default.
- Exit: opposite EMA9 cross reverses the position; 15:55 CT flatten remains the day-trading safety exit.
- Contract: Lean's mapped/front-month MES contract unless `mes-contract-expiry` is supplied.

Run a historical test with:

```bash
scripts/run-backtest.sh strategies/python/mes_ema9_minute/MesEma9MinuteStrategy.py MesEma9MinuteStrategy
```

The backtest runner archives the result and can launch the local visualizer. For paper IB testing, copy `.env.example` to `.env`, fill the repository's IB settings, then run:

```bash
LIVE_CONFIRM=true IB_TRADING_MODE=paper strategies/python/mes_ema9_minute/run-live.sh
```

The runner starts/reuses the metrics stack when installed and prints the Grafana dashboard URL. It is not a profitability claim: evaluate net profit after fees/slippage, trade count, win/loss distribution, max drawdown, average hold time, and performance by session.
