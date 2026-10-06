# Signal Generation

## Core Pattern

Every signal generation follows this pipeline:

1. **Compute indicator(s)** using `openalgo.ta`
2. **Generate raw boolean signals** from conditions
3. **Fill NaN with False** (critical before exrem)
4. **Clean with `ta.exrem()`** to remove duplicate consecutive signals

```python
from openalgo import ta
import pandas as pd

# 1. Compute
ema_fast = ta.ema(close, 10)
ema_slow = ta.ema(close, 20)

# 2. Raw signals
buy_raw = pd.Series(ta.crossover(ema_fast, ema_slow), index=close.index)
sell_raw = pd.Series(ta.crossunder(ema_fast, ema_slow), index=close.index)

# 3. Fill NaN
buy_raw = buy_raw.fillna(False)
sell_raw = sell_raw.fillna(False)

# 4. Clean
entries = ta.exrem(buy_raw, sell_raw)
exits = ta.exrem(sell_raw, buy_raw)
```

---

## Crossover / Crossunder

```python
# Series A crosses above Series B
cross_up = ta.crossover(series_a, series_b)

# Series A crosses below Series B
cross_down = ta.crossunder(series_a, series_b)

# Any cross (either direction)
any_cross = ta.cross(series_a, series_b)
```

These return boolean numpy arrays (or pandas Series if input is Series).

---

## Signal Cleaning with exrem()

`ta.exrem(buy, sell)` removes consecutive duplicate signals. After an entry signal, all subsequent entry signals are removed until an exit signal occurs (and vice versa).

```
Raw:    BUY  BUY  BUY  SELL  SELL  BUY
Cleaned: BUY  ---  ---  SELL  ----  BUY
```

**ALWAYS call `.fillna(False)` before exrem** — NaN values break the cleaning logic.

---

## Common Signal Patterns

### EMA Crossover

```python
ema_fast = ta.ema(close, 10)
ema_slow = ta.ema(close, 20)
buy = pd.Series(ta.crossover(ema_fast, ema_slow), index=close.index).fillna(False)
sell = pd.Series(ta.crossunder(ema_fast, ema_slow), index=close.index).fillna(False)
```

### RSI Overbought/Oversold

```python
rsi = ta.rsi(close, 14)
buy = pd.Series(ta.crossover(rsi, pd.Series(np.full(len(rsi), 30.0), index=close.index)),
                index=close.index).fillna(False)
sell = pd.Series(ta.crossover(pd.Series(np.full(len(rsi), 70.0), index=close.index), rsi),
                 index=close.index).fillna(False)
```

Or simpler threshold approach:

```python
rsi = ta.rsi(close, 14)
buy = (rsi < 30) & (pd.Series(rsi).shift(1) >= 30)  # RSI crosses below 30
sell = (rsi > 70) & (pd.Series(rsi).shift(1) <= 70)  # RSI crosses above 70
buy = buy.fillna(False)
sell = sell.fillna(False)
```

### Supertrend Direction Change

```python
st, direction = ta.supertrend(high, low, close, 10, 3.0)
direction = pd.Series(direction, index=close.index)
buy = (direction == -1) & (direction.shift(1) == 1)   # Switch to uptrend
sell = (direction == 1) & (direction.shift(1) == -1)   # Switch to downtrend
buy = buy.fillna(False)
sell = sell.fillna(False)
```

### MACD Signal Cross

```python
macd_line, signal_line, histogram = ta.macd(close, 12, 26, 9)
buy = pd.Series(ta.crossover(macd_line, signal_line), index=close.index).fillna(False)
sell = pd.Series(ta.crossunder(macd_line, signal_line), index=close.index).fillna(False)
```

### Bollinger Band Breakout

```python
upper, middle, lower = ta.bbands(close, 20, 2.0)
buy = pd.Series(ta.crossover(close, lower), index=close.index).fillna(False)    # Price crosses above lower band
sell = pd.Series(ta.crossunder(close, upper), index=close.index).fillna(False)   # Price crosses below upper band
```

### ADX Trend Strength Filter

```python
di_plus, di_minus, adx_val = ta.adx(high, low, close, 14)
# Only generate signals when ADX > 25 (strong trend)
trend_filter = pd.Series(adx_val, index=close.index) > 25

# Combine with directional signals
buy = pd.Series(ta.crossover(di_plus, di_minus), index=close.index).fillna(False) & trend_filter
sell = pd.Series(ta.crossunder(di_plus, di_minus), index=close.index).fillna(False) & trend_filter
```

---

## Condition Helpers

```python
# Rising for N bars
is_rising = ta.rising(close, 3)   # True when close has risen for 3 consecutive bars

# Falling for N bars
is_falling = ta.falling(close, 3)

# Highest/Lowest over period
hh = ta.highest(high, 20)     # 20-bar highest high
ll = ta.lowest(low, 20)       # 20-bar lowest low

# Value when condition is true
entry_price = ta.valuewhen(buy_signal, close)

# Flip toggle
state = ta.flip(buy_signal)    # Alternates between True/False on each trigger
```

---

## Signal Counting

```python
import pandas as pd

entries_clean = ta.exrem(buy.fillna(False), sell.fillna(False))
exits_clean = ta.exrem(sell.fillna(False), buy.fillna(False))

n_buys = entries_clean.sum()
n_sells = exits_clean.sum()
print(f"Buy signals: {n_buys}, Sell signals: {n_sells}")
```
