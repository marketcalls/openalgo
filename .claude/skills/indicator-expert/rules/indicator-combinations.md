# Indicator Combinations

## Why Combine Indicators

No single indicator is reliable alone. Combining indicators from different categories (trend + momentum + volume) creates confluence zones where multiple signals agree, reducing false signals.

---

## Category Mixing Rules

| Combination | Purpose | Example |
|-------------|---------|---------|
| Trend + Momentum | Confirm trend with momentum | EMA crossover + RSI filter |
| Trend + Volume | Validate trend with volume | Supertrend + OBV |
| Momentum + Volume | Confirm reversals | RSI oversold + MFI oversold |
| Trend + Volatility | Dynamic levels | EMA + Bollinger Bands |
| Multiple Trend | Strong trend confirmation | EMA + Supertrend + ADX |

**Avoid**: Combining indicators from the same category that measure the same thing (e.g., RSI + Stochastic both measure momentum).

---

## Pattern 1: Trend + Momentum (EMA + RSI)

```python
from openalgo import ta
import pandas as pd

# Trend: EMA direction
ema_20 = ta.ema(close, 20)
trend_bullish = close > ema_20

# Momentum: RSI not overbought
rsi = ta.rsi(close, 14)
rsi_ok = rsi < 70  # Not overbought for buys

# Combined signal
buy_raw = pd.Series(ta.crossover(close, ema_20), index=close.index).fillna(False)
buy_filtered = buy_raw & (pd.Series(rsi, index=close.index) < 70)

sell_raw = pd.Series(ta.crossunder(close, ema_20), index=close.index).fillna(False)
sell_filtered = sell_raw & (pd.Series(rsi, index=close.index) > 30)

entries = ta.exrem(buy_filtered.fillna(False), sell_filtered.fillna(False))
exits = ta.exrem(sell_filtered.fillna(False), buy_filtered.fillna(False))
```

---

## Pattern 2: Supertrend + Volume Confirmation

```python
st, direction = ta.supertrend(high, low, close, 10, 3.0)
direction = pd.Series(direction, index=close.index)
obv = ta.obv(close, volume)
obv_sma = ta.sma(obv, 20)

# Supertrend flips to uptrend AND OBV above its SMA (accumulation)
buy = ((direction == -1) & (direction.shift(1) == 1) &
       (pd.Series(obv, index=close.index) > pd.Series(obv_sma, index=close.index)))
sell = ((direction == 1) & (direction.shift(1) == -1))

entries = ta.exrem(buy.fillna(False), sell.fillna(False))
exits = ta.exrem(sell.fillna(False), buy.fillna(False))
```

---

## Pattern 3: Triple Screen (Elder)

Uses 3 timeframes and 3 indicator types:

```python
# Screen 1: Weekly trend (higher timeframe)
weekly_ema = ta.ema(weekly_close, 26)
weekly_trend = weekly_close.iloc[-1] > weekly_ema.iloc[-1]

# Screen 2: Daily momentum (oscillator for entry timing)
daily_rsi = ta.rsi(daily_close, 14)
daily_macd, daily_signal, daily_hist = ta.macd(daily_close, 12, 26, 9)

# Screen 3: Intraday entry (tight stop)
if weekly_trend:
    # Weekly bullish -> look for daily RSI pullback
    buy = (daily_rsi < 40) & (daily_rsi.shift(1) >= 40) & (daily_hist > daily_hist.shift(1))
else:
    sell = (daily_rsi > 60) & (daily_rsi.shift(1) <= 60) & (daily_hist < daily_hist.shift(1))
```

---

## Pattern 4: Bollinger + Keltner Squeeze

```python
upper_bb, mid_bb, lower_bb = ta.bbands(close, 20, 2.0)
upper_kc, mid_kc, lower_kc = ta.keltner(high, low, close, 20, 10, 1.5)

# Squeeze: BB inside KC
squeeze_on = (upper_bb < upper_kc) & (lower_bb > lower_kc)

# Momentum (using MACD histogram as proxy)
_, _, hist = ta.macd(close, 12, 26, 9)

# Buy when squeeze releases + positive momentum
squeeze_release = (~squeeze_on) & (squeeze_on.shift(1))
buy = squeeze_release & (hist > 0)
sell = squeeze_release & (hist < 0)
```

---

## Pattern 5: ADX + DI Crossover (Strong Trend Trading)

```python
di_plus, di_minus, adx_val = ta.adx(high, low, close, 14)
di_plus = pd.Series(di_plus, index=close.index)
di_minus = pd.Series(di_minus, index=close.index)
adx_series = pd.Series(adx_val, index=close.index)

# Strong trend filter
strong_trend = adx_series > 25

# DI crossover with ADX filter
buy = (pd.Series(ta.crossover(di_plus, di_minus), index=close.index).fillna(False) & strong_trend)
sell = (pd.Series(ta.crossunder(di_plus, di_minus), index=close.index).fillna(False) & strong_trend)

entries = ta.exrem(buy.fillna(False), sell.fillna(False))
exits = ta.exrem(sell.fillna(False), buy.fillna(False))
```

---

## Pattern 6: Multi-Indicator Score Card

Assign scores to multiple indicator conditions and trade only when score exceeds a threshold:

```python
import numpy as np

score = np.zeros(len(close))

# +1 for each bullish condition
rsi = ta.rsi(close, 14)
ema_20 = ta.ema(close, 20)
ema_50 = ta.ema(close, 50)
_, _, adx = ta.adx(high, low, close, 14)
macd_line, signal_line, _ = ta.macd(close, 12, 26, 9)

score += (close > ema_20).astype(float)         # Price above EMA(20)
score += (ema_20 > ema_50).astype(float)         # EMA(20) above EMA(50)
score += (rsi > 50).astype(float)                # RSI bullish
score += (rsi < 70).astype(float)                # RSI not overbought
score += (macd_line > signal_line).astype(float)  # MACD bullish
score += (adx > 20).astype(float)                # Trend present

score = pd.Series(score, index=close.index)

# Trade when 5+ conditions are met
buy = (score >= 5) & (score.shift(1) < 5)
sell = (score < 3) & (score.shift(1) >= 3)

entries = ta.exrem(buy.fillna(False), sell.fillna(False))
exits = ta.exrem(sell.fillna(False), buy.fillna(False))
```

---

## Charting Confluence Zones

```python
# Highlight bars where multiple indicators agree
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# Create background shading for high-score zones
high_score = score >= 5
for i in range(len(df)):
    if high_score.iloc[i]:
        fig.add_vrect(
            x0=x_labels[max(0, i-1)], x1=x_labels[i],
            fillcolor="rgba(0,255,0,0.05)", line_width=0,
            row=1, col=1,
        )
```
