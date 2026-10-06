---
name: strategy-catalog
description: Complete strategy implementations - EMA, Donchian, Momentum, MACD, SDA2, Supertrend, Dual Momentum
metadata:
  tags: strategies, ema-crossover, donchian, momentum, macd, sda2, supertrend, dual-momentum
---

# Strategy Catalog

All strategies use `openalgo.ta` for indicators (default) and signal cleaning. Switch indicators to TA-Lib only if the user explicitly asks for it - see [indicators-signals](./indicators-signals.md). Each strategy has a production-ready template in the `assets/` directory.

## 1. EMA Crossover

Fast/slow EMA crossover with `ta.exrem()` signal cleaning.

Template: [assets/ema_crossover/backtest.py](./assets/ema_crossover/backtest.py)

```python
from openalgo import ta

ema_fast = ta.ema(close, 10)
ema_slow = ta.ema(close, 20)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## 2. Donchian Channel Breakout

Price breaks above/below the N-period high/low channel.

Template: [assets/donchian/backtest.py](./assets/donchian/backtest.py)

```python
from openalgo import ta

upper, middle, lower = ta.donchian(df["high"], df["low"], period=20)

# Shift to avoid lookahead
upper_shifted = upper.shift(1)
lower_shifted = lower.shift(1)

entries = pd.Series(ta.crossover(df["close"], upper_shifted), index=df.index)
exits = pd.Series(ta.crossunder(df["close"], lower_shifted), index=df.index)
```

## 3. Momentum (Double MOM)

Uses MOM + MOM-of-MOM for directional confirmation with next-bar fill.

Template: [assets/momentum/backtest.py](./assets/momentum/backtest.py)

```python
from openalgo import ta

LENGTH = 12
mom0 = ta.mom(close, LENGTH)
mom1 = ta.mom(mom0, 1)

cond_long = (mom0 > 0) & (mom1 > 0)
cond_short = (mom0 < 0) & (mom1 < 0)

prev_high = high.shift(1)
prev_low = low.shift(1)
MINTICK = 0.05

entries_long = (cond_long.shift(1) & (high >= (prev_high + MINTICK))).fillna(False)
entries_short = (cond_short.shift(1) & (low <= (prev_low - MINTICK))).fillna(False)

entries_long = ta.exrem(entries_long, entries_short)
entries_short = ta.exrem(entries_short, entries_long)

exits_long = entries_short
exits_short = entries_long
```

## 4. MACD Signal-Candle Breakout

MACD zero-line defines regimes; entry on breakout of signal candle.

Template: [assets/macd/backtest.py](./assets/macd/backtest.py)

```python
from openalgo import ta

macd_series, macd_signal, macd_hist = ta.macd(close, fast_period=12, slow_period=26, signal_period=9)
zero = pd.Series(0.0, index=close.index)

bull_flip = ta.crossover(macd_series, zero)
bear_flip = ta.crossunder(macd_series, zero)

bull_regime = ta.flip(bull_flip, bear_flip)
bear_regime = ta.flip(bear_flip, bull_flip)

sig_high = high.where(bull_flip).ffill()
sig_low = low.where(bear_flip).ffill()

long_entry_raw = ta.crossover(high, sig_high) & bull_regime
short_entry_raw = ta.crossunder(low, sig_low) & bear_regime

entries_long = ta.exrem(long_entry_raw, bear_flip)
entries_short = ta.exrem(short_entry_raw, bull_flip)

exits_long = ta.exrem(bear_flip, entries_long)
exits_short = ta.exrem(bull_flip, entries_short)
```

## 5. SDA2 Trend Following System

WMA-based channel with STDDEV and ATR bands.

Template: [assets/sda2/backtest.py](./assets/sda2/backtest.py)

```python
from openalgo import ta

base = ((high + low) / 2.0) + (df["open"] - close)
derived = ta.wma(base, 3)

sd7 = ta.stdev(derived, 7)
atr2 = ta.atr(high, low, close, period=2)

upper = derived + sd7 + (atr2 / 1.5)
lower = derived - sd7 - (atr2 / 1.0)

entries = (close > upper) & (close.shift(1) <= upper.shift(1))
exits = (lower > close) & (lower.shift(1) <= close.shift(1))

entries = ta.exrem(entries.fillna(False), exits.fillna(False))
exits = ta.exrem(exits.fillna(False), entries)
```

## 6. Supertrend (Intraday with Time-Based Exit)

Supertrend crossover with Indian market session-aware entry/exit windows.

Template: [assets/supertrend/backtest.py](./assets/supertrend/backtest.py)

```python
from openalgo import ta
from datetime import time

st_line, st_direction = ta.supertrend(df["high"], df["low"], df["close"],
                                       period=10, multiplier=3.0)

close = df["close"]
t = df.index.time

cross_up = (close > st_line) & (close.shift(1) <= st_line.shift(1))
cross_down = (close < st_line) & (close.shift(1) >= st_line.shift(1))

# Indian market session windows
entry_window = (t >= time(9, 30)) & (t <= time(15, 0))
at_1515 = (t == time(15, 15))

long_entries = cross_up & entry_window
long_exits = cross_down | at_1515
short_entries = cross_down & entry_window
short_exits = cross_up | at_1515
```

## 7. Dual Momentum (ETF Rotation)

Quarterly momentum rotation between two ETFs.

Template: [assets/dual_momentum/backtest.py](./assets/dual_momentum/backtest.py)

See the template for the full implementation including quarterly returns calculation, winner selection with lookahead prevention, and target-weight portfolio construction.
