---
name: openalgo-ta-helpers
description: Complete OpenAlgo ta reference (100+ indicators across trend, momentum, volatility, volume, oscillators, statistical, hybrid) plus signal helpers (exrem, crossover, crossunder, flip). OpenAlgo ta is the default indicator library project-wide - TA-Lib is opt-in only.
metadata:
  tags: openalgo, ta, exrem, crossover, crossunder, flip, donchian, supertrend, ichimoku, sma, ema, kama, indicators, catalog
---

# OpenAlgo ta - Complete Reference (`openalgo.ta`)

`openalgo.ta` is the **default indicator library for every backtest in this project** - over 100 indicators across trend, momentum, volatility, volume, oscillators, statistical, and hybrid categories, plus the signal-cleaning helpers (`exrem`, `crossover`, `crossunder`, `flip`) that every strategy needs regardless of indicator source.

```python
from openalgo import ta
```

**Only switch to TA-Lib when the user explicitly says "talib" or "TA-Lib"** in their request - see [indicators-signals](./indicators-signals.md). Signal helpers (`exrem`, `crossover`, `crossunder`, `flip`) always come from `openalgo.ta`, even in a TA-Lib-indicator script.

> The tables below are sourced directly from the installed `openalgo` Python package (`openalgo/indicators/__init__.py`), not just the hosted docs pages - a couple of signatures differ from `docs.openalgo.in` in the current version (noted inline). If a call raises `TypeError` on an unexpected keyword, check the installed version with `python -c "import openalgo, inspect; print(inspect.signature(openalgo.ta.<fn>))"`.

## Signal Helpers

### exrem - Remove Excess Signals (CRITICAL)

Keeps only the first entry before an exit, and the first exit before an entry. Prevents duplicate consecutive buy/sell signals.

```python
entries = ta.exrem(buy_raw, sell_raw)
exits = ta.exrem(sell_raw, buy_raw)
```

**Before exrem:** `BUY BUY BUY SELL SELL BUY`
**After exrem:**  `BUY --- --- SELL ---- BUY`

Always use `ta.exrem()` after generating raw signals.

### crossover / crossunder / cross

```python
cross_up = ta.crossover(close, upper_band)      # series1 crosses above series2
cross_down = ta.crossunder(close, lower_band)   # series1 crosses below series2
either_cross = ta.cross(close, sma_20)          # either direction
```

### flip - Regime Detection

Returns True regime from trigger1 until trigger2 fires:

```python
bull_regime = ta.flip(bull_trigger, bear_trigger)
bear_regime = ta.flip(bear_trigger, bull_trigger)
```

### Other Utility Functions

```python
ta.highest(data, period)          # highest value over window
ta.lowest(data, period)           # lowest value over window
ta.change(data, length=1)         # value - value[length]
ta.roc(data, length)              # rate of change, percentage
ta.stdev(data, period)            # rolling standard deviation
ta.valuewhen(expr, array, n=1)    # value of array when expr last true
ta.rising(data, length)           # bool: data rising over length
ta.falling(data, length)          # bool: data falling over length
```

## Complete Indicator Catalog (100+)

Every function below is called as `ta.<name>(...)`. Series/array inputs (`close`, `high`, `low`, `open`, `volume`) accept `pandas.Series` or `numpy.ndarray`.

### Trend (20)

| Function | Signature | Returns |
|----------|-----------|---------|
| SMA | `ta.sma(data, period)` | Series |
| EMA | `ta.ema(data, period)` | Series |
| WMA | `ta.wma(data, period)` | ndarray |
| DEMA | `ta.dema(data, period)` | ndarray |
| TEMA | `ta.tema(data, period)` | ndarray |
| HMA | `ta.hma(data, period)` | ndarray |
| VWMA | `ta.vwma(data, volume, period)` | ndarray |
| ALMA | `ta.alma(data, period=21, offset=0.85, sigma=6.0)` | ndarray |
| KAMA | `ta.kama(data, length=14, fast_length=2, slow_length=30)` | ndarray |
| ZLEMA | `ta.zlema(data, period)` | ndarray |
| T3 | `ta.t3(data, period=21, v_factor=0.7)` | ndarray |
| FRAMA | `ta.frama(high, low, period=26)` | Series |
| TRIMA | `ta.trima(data, period=20)` | ndarray |
| McGinley Dynamic | `ta.mcginley(data, period=14)` | ndarray |
| VIDYA | `ta.vidya(data, period=14, alpha=0.2)` | ndarray |
| Alligator | `ta.alligator(data, jaw_period=13, jaw_shift=8, teeth_period=8, teeth_shift=5, lips_period=5, lips_shift=3)` | (jaw, teeth, lips) |
| MA Envelopes | `ta.ma_envelopes(data, period=20, percentage=2.5, ma_type='SMA')` | (upper, basis, lower) |
| Supertrend | `ta.supertrend(high, low, close, period=10, multiplier=3.0)` | (line, direction: -1 up / 1 down) |
| Ichimoku Cloud | `ta.ichimoku(high, low, close, conversion_periods=9, base_periods=26, lagging_span2_periods=52, displacement=26)` | (conversion, base, span_a, span_b, lagging) |
| Chande Kroll Stop | `ta.ckstop(high, low, close, p=10, x=1.0, q=9)` | (long_stop, short_stop) |

### Momentum (9)

| Function | Signature | Returns |
|----------|-----------|---------|
| RSI | `ta.rsi(data, period=14)` | ndarray |
| MACD | `ta.macd(data, fast_period=12, slow_period=26, signal_period=9)` | (macd, signal, histogram) |
| Stochastic | `ta.stochastic(high, low, close, k_period=14, smooth_k=3, d_period=3)` | (%K, %D) |
| CCI | `ta.cci(high, low, close, period=20)` | ndarray |
| Williams %R | `ta.williams_r(high, low, close, period=14)` | ndarray |
| Balance of Power | `ta.bop(open, high, low, close)` | Series |
| Elder Ray | `ta.elderray(high, low, close, period=13)` | (bull_power, bear_power) |
| Fisher Transform | `ta.fisher(high, low, length=9)` | (fisher, trigger) |
| Connors RSI | `ta.crsi(data, lenrsi=3, lenupdown=2, lenroc=100)` | Series |

### Volatility (16)

| Function | Signature | Returns |
|----------|-----------|---------|
| ATR | `ta.atr(high, low, close, period=14)` | ndarray |
| Bollinger Bands | `ta.bbands(data, period=20, std_dev=2.0)` | (upper, middle, lower) |
| Keltner Channel | `ta.keltner(high, low, close, ema_period=20, atr_period=10, multiplier=2.0)` | (upper, middle, lower) |
| Donchian Channel | `ta.donchian(high, low, period=20)` | (upper, middle, lower) |
| Chaikin Volatility | `ta.chaikin(high, low, ema_period=10, roc_period=10)` | ndarray |
| NATR | `ta.natr(high, low, close, period=14)` | ndarray |
| Relative Volume | `ta.rvol(volume, period=20)` | Series |
| Ultimate Oscillator | `ta.ultimate_oscillator(high, low, close, period1=7, period2=14, period3=28)` | ndarray |
| True Range | `ta.true_range(high, low, close)` | ndarray |
| Mass Index | `ta.massindex(high, low, length=10)` | ndarray |
| Bollinger %B | `ta.bbpercent(data, period=20, std_dev=2.0)` | ndarray |
| Bollinger Bandwidth | `ta.bbwidth(data, period=20, std_dev=2.0)` | ndarray |
| Chandelier Exit | `ta.chandelier_exit(high, low, close, period=22, multiplier=3.0)` | (long_exit, short_exit) |
| Historical Volatility | `ta.hv(close, length=10, annual=365, per=1)` | ndarray |
| Ulcer Index | `ta.ulcerindex(data, length=14, smooth_length=14, signal_length=52, signal_type="SMA", return_signal=False)` | ndarray, or (ndarray, signal) if `return_signal=True` |
| STARC Bands | `ta.starc(high, low, close, ma_period=5, atr_period=15, multiplier=1.33)` | (upper, middle, lower) |

**Naming collision to watch for:** the hosted docs page for Volatility describes `ta.rvi(data, stdev_period=10, rsi_period=14)` as "Relative Volatility Index". In the currently installed package, `ta.rvi()` is bound to the **Oscillator's Relative Vigor Index** instead (see Oscillators table below) - a different indicator with a different signature (`open, high, low, close, period=10`). There is no separate public accessor for the volatility Relative Volatility Index in this version. Verify with `inspect.signature(openalgo.ta.rvi)` before relying on either interpretation.

### Volume (14)

| Function | Signature | Returns |
|----------|-----------|---------|
| OBV | `ta.obv(close, volume)` | ndarray |
| OBV Smoothed | `ta.obv_smoothed(close, volume, ma_type="None", ma_length=20, bb_length=20, bb_mult=2.0)` | Series, or (mid, upper, lower) for `"SMA + Bollinger Bands"` |
| VWAP | `ta.vwap(high, low, close, volume, anchor="Session", source="hlc3")` | ndarray (note: `anchor` precedes `source` in the installed signature) |
| MFI | `ta.mfi(high, low, close, volume, period=14)` | ndarray |
| ADL | `ta.adl(high, low, close, volume)` | ndarray |
| CMF | `ta.cmf(high, low, close, volume, period=20)` | ndarray |
| EMV | `ta.emv(high, low, volume, length=14, divisor=10000)` | Series |
| Elder Force Index | `ta.force_index(close, volume, length=13)` | Series |
| NVI | `ta.nvi(close, volume)` / `ta.nvi_with_ema(close, volume, ema_length=255)` | ndarray / (nvi, ema) |
| PVI | `ta.pvi(close, volume, initial_value=100.0)` / `ta.pvi_with_signal(close, volume, initial_value=100.0, signal_type="EMA", signal_length=255)` | ndarray / (pvi, signal) |
| Volume Oscillator | `ta.volosc(volume, short_length=5, long_length=10, check_volume_validity=True)` | ndarray |
| VROC | `ta.vroc(volume, period=25)` | ndarray |
| Klinger Volume Oscillator | `ta.kvo(high, low, close, volume, trig_len=13, fast_x=34, slow_x=55)` | (kvo, trigger) |
| Price Volume Trend | `ta.pvt(close, volume)` | Series |

### Oscillators (19)

| Function | Signature | Returns |
|----------|-----------|---------|
| CMO | `ta.cmo(data, period=14)` | ndarray |
| TRIX | `ta.trix(data, length=18)` | ndarray |
| Ultimate Oscillator (alias) | `ta.uo_oscillator(high, low, close, period1=7, period2=14, period3=28)` | ndarray |
| Awesome Oscillator | `ta.awesome_oscillator(high, low, fast_period=5, slow_period=34)` | ndarray |
| Accelerator Oscillator | `ta.accelerator_oscillator(high, low, period=5)` | ndarray |
| PPO | `ta.ppo(data, fast_period=12, slow_period=26, signal_period=9)` | (ppo, signal, histogram) |
| Price Oscillator | `ta.po(data, fast_period=10, slow_period=20, ma_type="SMA")` | ndarray |
| DPO | `ta.dpo(data, period=21, is_centered=False)` | Series |
| Aroon Oscillator | `ta.aroon_oscillator(high, low, period=14)` | ndarray |
| Stochastic RSI | `ta.stochrsi(data, rsi_period=14, stoch_period=14, k_period=3, d_period=3)` | (%K, %D) |
| Relative Vigor Index | `ta.rvi(open, high, low, close, period=10)` | (rvi, signal) - see naming-collision note above |
| Chaikin Oscillator | `ta.cho(high, low, close, volume, fast_period=3, slow_period=10)` | Series |
| Choppiness Index | `ta.chop(high, low, close, period=14)` | ndarray |
| Know Sure Thing | `ta.kst(data, roclen1=10, roclen2=15, roclen3=20, roclen4=30, smalen1=10, smalen2=10, smalen3=10, smalen4=15, siglen=9)` | ndarray |
| True Strength Index | `ta.tsi(data, long_period=25, short_period=13, signal_period=13)` | ndarray |
| Vortex Indicator | `ta.vi(high, low, close, period=14)` | (vi_plus, vi_minus) |
| Schaff Trend Cycle | `ta.stc(data, fast_length=23, slow_length=50, cycle_length=10, d1_length=3, d2_length=3)` | ndarray |
| Gator Oscillator | `ta.gator_oscillator(high, low, jaw_period=13, teeth_period=8, lips_period=5)` | (upper, lower) |
| Coppock Curve | `ta.coppock(data, wma_length=10, long_roc_length=14, short_roc_length=11)` | Series |

### Statistical (9)

| Function | Signature | Returns |
|----------|-----------|---------|
| Linear Regression | `ta.linreg(data, period=14)` | ndarray |
| Linear Regression Slope | `ta.lrslope(data, period=100, interval=1)` | ndarray |
| Pearson Correlation | `ta.correlation(data1, data2, period=20)` | ndarray |
| Beta | `ta.beta(asset, market, period=252)` | ndarray |
| Variance | `ta.variance(data, lookback=20, mode="PR", ema_period=20, filter_lookback=20, ema_length=14, return_components=False)` | ndarray, or (variance, ema_variance, zscore, ema_zscore, stdev) if `return_components=True` |
| Time Series Forecast | `ta.tsf(data, period=14)` | ndarray |
| Rolling Median | `ta.median(data, period=3)` | ndarray |
| Median Bands | `ta.median_bands(high, low, close, source=None, median_length=3, atr_length=14, atr_mult=2.0)` | (median, upper, lower, median_ema) |
| Rolling Mode | `ta.mode(data, period=20, bins=10)` | ndarray |

### Hybrid (7)

| Function | Signature | Returns |
|----------|-----------|---------|
| ADX System | `ta.adx(high, low, close, period=14)` | (+DI, -DI, ADX) |
| Aroon | `ta.aroon(high, low, period=25)` | (aroon_up, aroon_down) |
| Pivot Points | `ta.pivot_points(high, low, close)` | (pivot, r1, s1, r2, s2, r3, s3) |
| DMI | `ta.dmi(high, low, close, period=14)` | (+DI, -DI) |
| Parabolic SAR | `ta.psar(high, low, acceleration=0.02, maximum=0.2)` | SAR values only (ndarray) - the hosted docs show `(sar, trend)`, the installed version returns only `sar` |
| Williams Fractals | `ta.fractals(high, low, periods=2)` | (fractal_up, fractal_down) |
| Random Walk Index | `ta.rwi(high, low, close, period=14)` | (rwi_high, rwi_low) |

### TA-Lib-Compatible Extras (18)

OpenAlgo ta also ships direct equivalents of common TA-Lib functions that are not part of its own native catalog above - use these instead of reaching for `talib` when the user has not asked for TA-Lib:

| Function | Signature | TA-Lib Equivalent |
|----------|-----------|--------------------|
| Momentum | `ta.mom(data, period=10)` | `MOM`: `data - data[period]` |
| ROC Percentage | `ta.rocp(data, period=10)` | `ROCP`: `(price-prev)/prev` |
| ROC Ratio | `ta.rocr(data, period=10)` | `ROCR`: `price/prev` |
| ROC Ratio x100 | `ta.rocr100(data, period=10)` | `ROCR100` |
| MidPoint | `ta.midpoint(data, period=14)` | `MIDPOINT` |
| Midpoint Price | `ta.midprice(high, low, period=14)` | `MIDPRICE` |
| Absolute Price Oscillator | `ta.apo(data, fast_period=12, slow_period=26, ma_type="SMA")` | `APO` |
| Average Price | `ta.avgprice(open, high, low, close)` | `AVGPRICE` |
| Median Price | `ta.medprice(high, low)` | `MEDPRICE` |
| Typical Price | `ta.typprice(high, low, close)` | `TYPPRICE` |
| Weighted Close Price | `ta.wclprice(high, low, close)` | `WCLPRICE` |
| Plus Directional Movement | `ta.plus_dm(high, low, period=14)` | `PLUS_DM` |
| Minus Directional Movement | `ta.minus_dm(high, low, period=14)` | `MINUS_DM` |
| Directional Movement Index | `ta.dx(high, low, close, period=14)` | `DX` |
| Average DM Rating | `ta.adxr(high, low, close, period=14)` | `ADXR` |
| Stochastic Fast | `ta.stochf(high, low, close, fastk_period=5, fastd_period=3)` | `STOCHF` -> (fastk, fastd) |
| Linear Reg Angle | `ta.linregangle(data, period=14)` | `LINEARREG_ANGLE` |
| Linear Reg Intercept | `ta.linregintercept(data, period=14)` | `LINEARREG_INTERCEPT` |

### Utility / Signal Functions (13)

Already documented above under "Signal Helpers" and "Other Utility Functions": `crossover`, `crossunder`, `cross`, `highest`, `lowest`, `change`, `roc`, `stdev`, `exrem`, `flip`, `valuewhen`, `rising`, `falling`.

## Specialty Indicator Notes (Not Available in TA-Lib)

These have no TA-Lib equivalent at all, so they are always sourced from `openalgo.ta`, even in a TA-Lib-opt-in script:

```python
st_line, st_direction = ta.supertrend(df['high'], df['low'], df['close'], period=10, multiplier=3.0)
# direction: -1 = uptrend (bullish), 1 = downtrend (bearish)

upper, middle, lower = ta.donchian(df['high'], df['low'], period=20)
# Always shift by 1 to avoid lookahead:
upper_shifted = upper.shift(1)

conversion, base, span_a, span_b, lagging = ta.ichimoku(
    df['high'], df['low'], df['close'],
    conversion_periods=9, base_periods=26,
    lagging_span2_periods=52, displacement=26
)
```

## When to Use OpenAlgo ta vs TA-Lib

**Default: use `openalgo.ta` for everything** - it covers every indicator TA-Lib does (EMA, SMA, RSI, MACD, BBANDS, ATR, ADX, STDDEV, MOM, STOCH, CCI, ...) plus ~90 more that TA-Lib does not have (Supertrend, Donchian, Ichimoku, HMA, KAMA, ALMA, ZLEMA, VWMA, all Oscillators, all Statistical indicators, etc).

**Switch to TA-Lib only when the user explicitly asks for "talib" or "TA-Lib"** in their request. Even then, keep signal helpers (`exrem`, `crossover`, `crossunder`, `flip`) on `openalgo.ta` - TA-Lib does not provide them.

**Fallback:** if `openalgo` is not importable at all (standalone DuckDB setup with no OpenAlgo install), fall back to TA-Lib for indicators - see [duckdb-data](./duckdb-data.md).

## Common Signal Pipeline

```python
from openalgo import ta

# 1. Compute indicators (openalgo.ta by default)
ema_fast = ta.ema(close, 10)
ema_slow = ta.ema(close, 20)

# 2. Generate raw signals
buy_raw = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
sell_raw = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

# 3. Fill NaN with False
buy_raw = buy_raw.fillna(False)
sell_raw = sell_raw.fillna(False)

# 4. Clean with exrem
entries = ta.exrem(buy_raw, sell_raw)
exits = ta.exrem(sell_raw, buy_raw)
```

## NEVER Do This

- Never skip `ta.exrem()` - duplicate signals corrupt position sizing
- Never forget `.fillna(False)` before `ta.exrem()` - NaN values propagate incorrectly
- Never use shifted Donchian/channel values without `.shift(1)` - that is lookahead bias
- Never switch to TA-Lib unless the user explicitly asked for it
- Never assume a docs-page signature is exact - a few (`ta.vwap`, `ta.stochastic`, `ta.psar`, `ta.rvi`) differ from `docs.openalgo.in` in the installed version; verify with `inspect.signature()` if a call fails
