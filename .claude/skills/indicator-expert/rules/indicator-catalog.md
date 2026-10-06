# Indicator Catalog — Complete Reference

All indicators are accessed via `from openalgo import ta`. Every indicator accepts numpy arrays, pandas Series, or lists. Output type matches input type. Since openalgo 2.0, all kernels are computed by a compiled Rust core shipped inside the wheel — full speed from the first call.

---

## Trend Indicators (20)

### Moving Averages

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| SMA | `ta.sma` | `(data, period)` | Array |
| EMA | `ta.ema` | `(data, period)` | Array (first-value seed) |
| WMA | `ta.wma` | `(data, period)` | Array |
| DEMA | `ta.dema` | `(data, period)` | Array |
| TEMA | `ta.tema` | `(data, period)` | Array |
| HMA | `ta.hma` | `(data, period)` | Array |
| VWMA | `ta.vwma` | `(data, volume, period)` | Array |
| ALMA | `ta.alma` | `(data, period=21, offset=0.85, sigma=6.0)` | Array |
| KAMA | `ta.kama` | `(data, length=14, fast_length=2, slow_length=30)` | Array |
| ZLEMA | `ta.zlema` | `(data, period)` | Array |
| T3 | `ta.t3` | `(data, period=21, v_factor=0.7)` | Array |
| FRAMA | `ta.frama` | `(high, low, period=26)` | Array |
| TRIMA | `ta.trima` | `(data, period)` | Array |
| McGinley | `ta.mcginley` | `(data, period=14)` | Array |
| VIDYA | `ta.vidya` | `(data, period=14)` | Array |

### Advanced Trend

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| Supertrend | `ta.supertrend` | `(high, low, close, period=10, multiplier=3.0)` | Tuple: (supertrend, direction) |
| Ichimoku | `ta.ichimoku` | `(high, low, close, conversion=9, base=26, lagging=52, displacement=26)` | Tuple: (conversion, base, span_a, span_b, lagging) |
| ChandeKrollStop | `ta.chande_kroll_stop` | `(high, low, close, p=10, q=9, x=1)` | Tuple: (stop_long, stop_short) |
| Alligator | `ta.alligator` | `(high, low, close)` | Tuple: (jaw, teeth, lips) |
| MA Envelopes | `ta.ma_envelopes` | `(data, period=20, percent=2.5)` | Tuple: (upper, basis, lower) |

**Supertrend direction**: -1 = uptrend (green), 1 = downtrend (red)

---

## Momentum Indicators (9)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| RSI | `ta.rsi` | `(close, period=14)` | Array (0-100) |
| MACD | `ta.macd` | `(close, fast=12, slow=26, signal=9)` | Tuple: (macd, signal, histogram) |
| Stochastic | `ta.stochastic` | `(high, low, close, k_period=14, smooth_k=3, d_period=3)` | Tuple: (slow_k, slow_d) |
| CCI | `ta.cci` | `(high, low, close, period=20)` | Array |
| Williams %R | `ta.williams_r` | `(high, low, close, period=14)` | Array (0 to -100) |
| BOP | `ta.bop` | `(open, high, low, close)` | Array (-1 to 1) |
| ElderRay | `ta.elder_ray` | `(high, low, close, period=13)` | Tuple: (bull_power, bear_power) |
| Fisher | `ta.fisher` | `(high, low, period=9)` | Tuple: (fisher, trigger) |
| CRSI | `ta.crsi` | `(close, rsi_period=3, streak_rsi=2, pct_rank=100)` | Array |

---

## Volatility Indicators (16)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| ATR | `ta.atr` | `(high, low, close, period=14)` | Array |
| BollingerBands | `ta.bbands` | `(close, period=20, std_dev=2.0)` | Tuple: (upper, middle, lower) |
| Keltner | `ta.keltner` | `(high, low, close, ema=20, atr=10, mult=2.0)` | Tuple: (upper, middle, lower) |
| Donchian | `ta.donchian` | `(high, low, period=20)` | Tuple: (upper, middle, lower) |
| Chaikin Vol | `ta.chaikin_volatility` | `(high, low, ema=10, roc=10)` | Array |
| NATR | `ta.natr` | `(high, low, close, period=14)` | Array (% of close) |
| True Range | `ta.true_range` | `(high, low, close)` | Array |
| Mass Index | `ta.massindex` | `(high, low, length=10)` | Array |
| BB %B | `ta.bb_percent` | `(close, period=20, std_dev=2.0)` | Array (0-1) |
| BB Width | `ta.bb_width` | `(close, period=20, std_dev=2.0)` | Array |
| Chandelier Exit | `ta.chandelier_exit` | `(high, low, close, period=22, mult=3.0)` | Tuple: (long, short) |
| Historical Vol | `ta.historical_volatility` | `(close, period=20)` | Array |
| Ulcer Index | `ta.ulcer_index` | `(close, period=14)` | Array |
| STARC | `ta.starc` | `(high, low, close, period=15, mult=1.33)` | Tuple: (upper, lower) |
| RVI | `ta.rvi` | `(close, period=14)` | Array |
| Ultimate Osc | `ta.ultimate_oscillator` | `(high, low, close, p1=7, p2=14, p3=28)` | Array |

---

## Volume Indicators (15)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| OBV | `ta.obv` | `(close, volume)` | Array |
| OBV Smoothed | `ta.obv_smoothed` | `(close, volume, ma_type="None", ma_length=20, ...)` | Array or Tuple |
| VWAP | `ta.vwap` | `(high, low, close, volume, anchor="Session", ...)` | Array |
| MFI | `ta.mfi` | `(high, low, close, volume, period=14)` | Array (0-100) |
| ADL | `ta.adl` | `(high, low, close, volume)` | Array |
| CMF | `ta.cmf` | `(high, low, close, volume, period=20)` | Array |
| EMV | `ta.emv` | `(high, low, volume, length=14, divisor=10000)` | Array |
| Force Index | `ta.force_index` | `(close, volume, length=13)` | Array |
| NVI | `ta.nvi` | `(close, volume)` | Array |
| PVI | `ta.pvi` | `(close, volume, initial_value=100.0)` | Array |
| Volume Osc | `ta.volosc` | `(volume, short=5, long=10)` | Array (%) |
| VROC | `ta.vroc` | `(volume, period=25)` | Array |
| KVO | `ta.kvo` | `(high, low, close, volume, trig=13, fast=34, slow=55)` | Tuple: (kvo, trigger) |
| PVT | `ta.pvt` | `(close, volume)` | Array |
| RVOL | `ta.rvol` | `(volume, period=20)` | Array (relative volume ratio) |

---

## Oscillators (20+)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| CMO | `ta.cmo` | `(close, period=14)` | Array |
| TRIX | `ta.trix` | `(close, length=18)` | Array |
| ROC | `ta.roc` | `(close, period=12)` | Array (%) |
| AO | `ta.awesome_oscillator` | `(high, low, fast=5, slow=34)` | Array |
| AC | `ta.accelerator_oscillator` | `(high, low, period=5)` | Array |
| PPO | `ta.ppo` | `(close, fast=12, slow=26, signal=9)` | Tuple: (ppo, signal, histogram) |
| PO | `ta.po` | `(close, fast=10, slow=20, ma_type="SMA")` | Array |
| DPO | `ta.dpo` | `(close, period=21, is_centered=False)` | Array |
| Aroon Osc | `ta.aroon_oscillator` | `(high, low, period=14)` | Array |
| StochRSI | `ta.stoch_rsi` | `(close, period=14, k=3, d=3)` | Tuple: (k, d) |
| CHO | `ta.cho` | `(high, low, close, volume, fast=3, slow=10)` | Array |
| CHOP | `ta.chop` | `(high, low, close, period=14)` | Array |
| KST | `ta.kst` | `(close, ...)` | Tuple: (kst, signal) |
| TSI | `ta.tsi` | `(close, long=25, short=13, signal=13)` | Tuple: (tsi, signal) |
| Vortex | `ta.vortex` | `(high, low, close, period=14)` | Tuple: (vi_plus, vi_minus) |
| Gator Osc | `ta.gator_oscillator` | `(high, low, close)` | Tuple: (upper, lower) |
| STC | `ta.stc` | `(close, fast=23, slow=50, cycle=10)` | Array |
| Coppock | `ta.coppock` | `(close, wma=10, long_roc=14, short_roc=11)` | Array |
| UO | `ta.uo_oscillator` | `(high, low, close, p1=7, p2=14, p3=28)` | Array |

---

## Statistical Indicators (9)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| LINREG | `ta.linreg` | `(close, period=14)` | Array |
| LR Slope | `ta.lrslope` | `(close, period=100, interval=1)` | Array |
| Correlation | `ta.correlation` | `(data1, data2, period=20)` | Array (-1 to 1) |
| Beta | `ta.beta` | `(asset, market, period=252)` | Array |
| Variance | `ta.variance` | `(close, lookback=20, mode="PR", ...)` | Array or Tuple |
| TSF | `ta.tsf` | `(close, period=14)` | Array |
| Median | `ta.median` | `(data, period=5)` | Array |
| Mode | `ta.mode` | `(data, period=5)` | Array |
| Median Bands | `ta.median_bands` | `(close, period=5, mult=1.0)` | Tuple: (upper, median, lower) |

---

## Hybrid / Advanced Indicators (6+)

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| ADX | `ta.adx` | `(high, low, close, period=14)` | Tuple: (di_plus, di_minus, adx) |
| DMI | `ta.dmi` | `(high, low, close, period=14)` | Tuple: (di_plus, di_minus) |
| Aroon | `ta.aroon` | `(high, low, period=14)` | Tuple: (aroon_up, aroon_down) |
| Pivot Points | `ta.pivot_points` | `(high, low, close)` | Tuple: (pivot, r1, s1, r2, s2, r3, s3) |
| Parabolic SAR | `ta.sar` | `(high, low, acceleration=0.02, maximum=0.2)` | Tuple: (sar, trend) |
| Williams Fractals | `ta.williams_fractals` | `(high, low, period=2)` | Tuple: (up_fractals, down_fractals) |
| RWI | `ta.rwi` | `(high, low, close, period=14)` | Tuple: (rwi_high, rwi_low) |

---

## TA-Lib Compatible Indicators (18)

Added in openalgo 2.0. These match TA-Lib definitions exactly (where openalgo intentionally follows TradingView/Pine conventions elsewhere — EMA/ATR/ADX seeding, etc. — the differences are documented in the library's TALIB_COMPATIBILITY notes).

| Indicator | Method | Signature | Returns |
|-----------|--------|-----------|---------|
| Momentum | `ta.mom` | `(data, period=10)` | Array (data - data[period] ago) |
| ROC Percentage | `ta.rocp` | `(data, period=10)` | Array ((price - prev) / prev) |
| ROC Ratio | `ta.rocr` | `(data, period=10)` | Array (price / prev) |
| ROC Ratio 100 | `ta.rocr100` | `(data, period=10)` | Array (price / prev * 100) |
| APO | `ta.apo` | `(data, fast_period=12, slow_period=26, ma_type="SMA")` | Array (MA(fast) - MA(slow)) |
| MidPoint | `ta.midpoint` | `(data, period=14)` | Array ((highest + lowest) / 2 of source) |
| MidPrice | `ta.midprice` | `(high, low, period=14)` | Array ((highest(high) + lowest(low)) / 2) |
| Average Price | `ta.avgprice` | `(open_prices, high, low, close)` | Array ((O + H + L + C) / 4) |
| Median Price | `ta.medprice` | `(high, low)` | Array ((H + L) / 2) |
| Typical Price | `ta.typprice` | `(high, low, close)` | Array ((H + L + C) / 3) |
| Weighted Close | `ta.wclprice` | `(high, low, close)` | Array ((H + L + 2C) / 4) |
| Plus DM | `ta.plus_dm` | `(high, low, period=14)` | Array (Wilder-summed +DM) |
| Minus DM | `ta.minus_dm` | `(high, low, period=14)` | Array (Wilder-summed -DM) |
| DX | `ta.dx` | `(high, low, close, period=14)` | Array (100 * abs(+DI - -DI) / (+DI + -DI)) |
| ADXR | `ta.adxr` | `(high, low, close, period=14)` | Array ((ADX + ADX[period-1] ago) / 2) |
| Stochastic Fast | `ta.stochf` | `(high, low, close, fastk_period=5, fastd_period=3)` | Tuple: (fastk, fastd) |
| LinReg Angle | `ta.linregangle` | `(data, period=14)` | Array (degrees(atan(slope))) |
| LinReg Intercept | `ta.linregintercept` | `(data, period=14)` | Array |

---

## Utility Functions

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `ta.crossover` | `(series1, series2)` | Boolean array | True where series1 crosses above series2 |
| `ta.crossunder` | `(series1, series2)` | Boolean array | True where series1 crosses below series2 |
| `ta.cross` | `(series1, series2)` | Boolean array | True where any cross occurs |
| `ta.highest` | `(data, period)` | Array | Rolling maximum over period (O(n)) |
| `ta.lowest` | `(data, period)` | Array | Rolling minimum over period (O(n)) |
| `ta.change` | `(data, length=1)` | Array | Difference from N bars ago |
| `ta.stdev` | `(data, period)` | Array | Rolling standard deviation |
| `ta.exrem` | `(buy, sell)` | Cleaned series | Remove consecutive duplicate signals |
| `ta.flip` | `(series)` | Flipped series | Toggle on/off states |
| `ta.valuewhen` | `(condition, value)` | Array | Value at condition trigger |
| `ta.rising` | `(data, period)` | Boolean array | True when rising for N bars |
| `ta.falling` | `(data, period)` | Boolean array | True when falling for N bars |
