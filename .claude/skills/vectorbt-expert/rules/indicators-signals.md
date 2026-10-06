---
name: indicators-signals
description: Creating technical indicators and entry/exit signals - OpenAlgo ta by default, TA-Lib only when the user explicitly asks for it
metadata:
  tags: indicators, signals, rsi, ema, sma, macd, crossover, entries, exits, openalgo, talib
---

# Creating Indicators & Signals

## CRITICAL RULE: OpenAlgo ta by Default, TA-Lib Only on Request

**Default to `openalgo.ta`** (`from openalgo import ta`) for ALL technical indicators, including simple ones like EMA and SMA. OpenAlgo ta covers 80+ indicators (trend, momentum, volatility, volume, statistical, hybrid) and is already the required import for signal cleaning (`ta.exrem()`, `ta.crossover()`, `ta.crossunder()`, `ta.flip()`), so using it for indicators too keeps every script to a single indicator import.

**Only use TA-Lib (`talib`) when the user explicitly says "talib" or "TA-Lib"** in their request (e.g., "backtest EMA crossover using talib"). In that case, use TA-Lib for the indicators the user asked about, but still use `openalgo.ta` for signal helpers (`exrem`, `crossover`, `crossunder`, `flip`) - those are not part of TA-Lib.

NEVER use VectorBT's built-in `vbt.MA.run()`, `vbt.RSI.run()`, or similar indicators - regardless of which indicator library is in play. The only exception is `vbt.MA.run()` for broadcasted parameter-sweep optimization (see [parameter-optimization](./parameter-optimization.md)).

```python
from openalgo import ta
```

## EMA Crossover Strategy (Default: OpenAlgo ta)

```python
from openalgo import ta

fast_period, slow_period = 10, 20
ema_fast = ta.ema(close, fast_period)
ema_slow = ta.ema(close, slow_period)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

# ALWAYS clean signals with ta.exrem()
entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## SMA Crossover Strategy (Default: OpenAlgo ta)

```python
from openalgo import ta

fast_sma = ta.sma(close, 10)
slow_sma = ta.sma(close, 20)

buy_raw = (fast_sma > slow_sma) & (fast_sma.shift(1) <= slow_sma.shift(1))
sell_raw = (fast_sma < slow_sma) & (fast_sma.shift(1) >= slow_sma.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## RSI Strategy (Default: OpenAlgo ta)

```python
from openalgo import ta

rsi = ta.rsi(close, period=14)

buy_raw = (rsi < 30) & (rsi.shift(1) >= 30)      # RSI crosses below 30 (oversold)
sell_raw = (rsi > 70) & (rsi.shift(1) <= 70)      # RSI crosses above 70 (overbought)

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## MACD Strategy (Default: OpenAlgo ta)

```python
from openalgo import ta

macd_line, signal_line, histogram = ta.macd(close, fast_period=12, slow_period=26, signal_period=9)

buy_raw = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
sell_raw = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## Bollinger Bands Strategy (Default: OpenAlgo ta)

```python
from openalgo import ta

upper, middle, lower = ta.bbands(close, period=20, std_dev=2.0)

buy_raw = (close < lower) & (close.shift(1) >= lower.shift(1))   # Price touches lower band
sell_raw = (close > upper) & (close.shift(1) <= upper.shift(1))   # Price touches upper band

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

## ATR (Average True Range)

```python
from openalgo import ta

atr = ta.atr(high, low, close, period=14)
```

## Complete OpenAlgo ta Indicator Reference (Default)

| Indicator | OpenAlgo ta Function | Usage |
|-----------|----------------------|-------|
| EMA | `ta.ema(close, period)` | Trend following |
| SMA | `ta.sma(close, period)` | Trend following |
| WMA | `ta.wma(close, period)` | Weighted trend |
| RSI | `ta.rsi(close, period=14)` | Overbought/oversold |
| MACD | `ta.macd(close, fast_period=12, slow_period=26, signal_period=9)` | Trend + momentum |
| Bollinger | `ta.bbands(close, period=20, std_dev=2.0)` | Volatility bands |
| ATR | `ta.atr(high, low, close, period=14)` | Volatility measure |
| ADX system | `ta.adx(high, low, close, period=14)` -> `(di_plus, di_minus, adx)` | Trend strength (tuple, not just ADX) |
| STDDEV | `ta.stdev(data, period)` | Standard deviation |
| MOM (momentum) | `ta.mom(data, period=10)` | Momentum: `data - data[period]` (exact TA-Lib MOM equivalent) |
| STOCH | `ta.stochastic(high, low, close, k_period=14, smooth_k=3, d_period=3)` -> `(k, d)` | Stochastic |
| CCI | `ta.cci(high, low, close, period=20)` | Commodity channel |

This table covers the common strategy-building indicators only. OpenAlgo ta ships 100+ indicators total (trend, momentum, volatility, volume, oscillators, statistical, hybrid, TA-Lib-compatible extras, utility). See [openalgo-ta-helpers](./openalgo-ta-helpers.md) for the full catalog, specialty indicators (Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA), and signal utilities.

Most OpenAlgo ta functions already return a `pandas.Series` aligned to the input index - no need to re-wrap in `pd.Series(..., index=close.index)` like TA-Lib requires.

## TA-Lib (Only When User Explicitly Requests It)

If the user's request explicitly names "talib" or "TA-Lib", use `talib` for the indicators they asked about instead of `openalgo.ta`. TA-Lib returns raw `numpy.ndarray` - always wrap the output in `pd.Series(..., index=close.index)` to preserve the datetime index. Signal helpers (`exrem`, `crossover`, `crossunder`, `flip`) still come from `openalgo.ta` regardless.

```python
import talib as tl
from openalgo import ta

fast_period, slow_period = 10, 20
ema_fast = pd.Series(tl.EMA(close.values, timeperiod=fast_period), index=close.index)
ema_slow = pd.Series(tl.EMA(close.values, timeperiod=slow_period), index=close.index)

buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

entries = ta.exrem(buy_raw.fillna(False), sell_raw.fillna(False))
exits = ta.exrem(sell_raw.fillna(False), buy_raw.fillna(False))
```

### TA-Lib Indicator Reference (Opt-In)

| Indicator | TA-Lib Function | Usage |
|-----------|----------------|-------|
| EMA | `tl.EMA(close.values, timeperiod=N)` | Trend following |
| SMA | `tl.SMA(close.values, timeperiod=N)` | Trend following |
| WMA | `tl.WMA(close.values, timeperiod=N)` | Weighted trend |
| RSI | `tl.RSI(close.values, timeperiod=14)` | Overbought/oversold |
| MACD | `tl.MACD(close.values, 12, 26, 9)` | Trend + momentum |
| Bollinger | `tl.BBANDS(close.values, 20, 2, 2)` | Volatility bands |
| ATR | `tl.ATR(high.values, low.values, close.values, 14)` | Volatility measure |
| ADX | `tl.ADX(high.values, low.values, close.values, 14)` | Trend strength (single ADX value, unlike `ta.adx()`) |
| STDDEV | `tl.STDDEV(close.values, timeperiod=N)` | Standard deviation |
| MOM | `tl.MOM(close.values, timeperiod=N)` | Momentum |
| STOCH | `tl.STOCH(high.values, low.values, close.values)` | Stochastic |
| CCI | `tl.CCI(high.values, low.values, close.values, 14)` | Commodity channel |

### Fallback: Standalone DuckDB Without OpenAlgo Installed

If the environment has no `openalgo` package (e.g., a standalone DuckDB setup with only `talib`/`vectorbt`/`duckdb` installed), fall back to TA-Lib for indicators and the inline `exrem()` helper - see [duckdb-data](./duckdb-data.md).

## Signal Cleaning: Why ta.exrem() Matters

Raw crossover signals can produce consecutive buy signals without an intervening sell. `ta.exrem()` keeps only the FIRST entry before an exit and vice versa:

```
Raw:    BUY  BUY  BUY  SELL  SELL  BUY
Clean:  BUY  ---  ---  SELL  ----  BUY
```

Always apply `ta.exrem()` after generating raw signals, regardless of which indicator library computed them. See [openalgo-ta-helpers](./openalgo-ta-helpers.md) for full helper reference.

## NEVER Do This

- **NEVER use `vbt.MA.run()`, `vbt.RSI.run()`**, or any VectorBT built-in indicator (with either library)
- Never switch to TA-Lib unless the user explicitly asked for it
- Never generate signals using future data (lookahead bias)
- Never skip `ta.exrem()` signal cleaning - duplicate signals cause incorrect position sizing
- Never use `close[i]` in Python loops when vectorized operations exist
- Never forget `.fillna(False)` on boolean signal series - NaN signals cause silent errors
- When using TA-Lib, never forget to wrap its output in `pd.Series(..., index=close.index)` (OpenAlgo ta does not need this)
