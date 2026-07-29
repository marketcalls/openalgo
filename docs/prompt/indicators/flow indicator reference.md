# Flow Indicator Reference

Generated from the installed `openalgo` build: every entry was produced by
introspecting the callable and then executing it over 400 deterministic
OHLCV bars. Each one returned a non-null value in that run, so each is
usable from the Flow `indicator` node.

**Do not hand-edit.** Regenerate with:

```bash
uv run python scripts/generate_indicator_reference.py
```

- **Inputs** are the OHLCV columns the node feeds in for you.
- **Parameters** go in the node's `params` object.
- **Outputs** are the keys under `latest` / `previous` / `at_offset`. A single
  output is always `value`; multiple outputs are `out0`, `out1`, ...

| Indicator | Python call | Inputs | Parameters | Outputs | `params` example |
|---|---|---|---|---|---|
| `accelerator_oscillator` | `ta.accelerator_oscillator(high, low, period=5)` | `high`, `low` | `period`=5 | `value` | `{"period": 5}` |
| `adl` | `ta.adl(high, low, close, volume)` | `high`, `low`, `close`, `volume` | - | `value` | `{}` |
| `adx` | `ta.adx(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `out0`, `out1`, `out2` | `{"period": 14}` |
| `adxr` | `ta.adxr(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `alligator` | `ta.alligator(close, jaw_period=13, jaw_shift=8)` | `close` | `jaw_period`=13, `jaw_shift`=8, `teeth_period`=8, `teeth_shift`=5, `lips_period`=5, `lips_shift`=3 | `out0`, `out1`, `out2` | `{"jaw_period": 13, "jaw_shift": 8}` |
| `alma` | `ta.alma(close, period=21, offset=0.85)` | `close` | `period`=21, `offset`=0.85, `sigma`=6.0 | `value` | `{"period": 21, "offset": 0.85}` |
| `apo` | `ta.apo(close, fast_period=12, slow_period=26)` | `close` | `fast_period`=12, `slow_period`=26, `ma_type`='SMA' | `value` | `{"fast_period": 12, "slow_period": 26}` |
| `aroon` | `ta.aroon(high, low, period=25)` | `high`, `low` | `period`=25 | `out0`, `out1` | `{"period": 25}` |
| `aroon_oscillator` | `ta.aroon_oscillator(high, low, period=14)` | `high`, `low` | `period`=14 | `value` | `{"period": 14}` |
| `atr` | `ta.atr(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `avgprice` | `ta.avgprice(open, high, low, close)` | `open`, `high`, `low`, `close` | - | `value` | `{}` |
| `awesome_oscillator` | `ta.awesome_oscillator(high, low, fast_period=5, slow_period=34)` | `high`, `low` | `fast_period`=5, `slow_period`=34 | `value` | `{"fast_period": 5, "slow_period": 34}` |
| `bbands` | `ta.bbands(close, period=20, std_dev=2.0)` | `close` | `period`=20, `std_dev`=2.0 | `out0`, `out1`, `out2` | `{"period": 20, "std_dev": 2.0}` |
| `bbpercent` | `ta.bbpercent(close, period=20, std_dev=2.0)` | `close` | `period`=20, `std_dev`=2.0 | `value` | `{"period": 20, "std_dev": 2.0}` |
| `bbwidth` | `ta.bbwidth(close, period=20, std_dev=2.0)` | `close` | `period`=20, `std_dev`=2.0 | `value` | `{"period": 20, "std_dev": 2.0}` |
| `bop` | `ta.bop(open, high, low, close)` | `open`, `high`, `low`, `close` | - | `value` | `{}` |
| `cci` | `ta.cci(high, low, close, period=20)` | `high`, `low`, `close` | `period`=20 | `value` | `{"period": 20}` |
| `chaikin` | `ta.chaikin(high, low, ema_period=10, roc_period=10)` | `high`, `low` | `ema_period`=10, `roc_period`=10 | `value` | `{"ema_period": 10, "roc_period": 10}` |
| `chandelier_exit` | `ta.chandelier_exit(high, low, close, period=22, multiplier=3.0)` | `high`, `low`, `close` | `period`=22, `multiplier`=3.0 | `out0`, `out1` | `{"period": 22, "multiplier": 3.0}` |
| `change` | `ta.change(close, length=1)` | `close` | `length`=1 | `value` | `{"length": 1}` |
| `cho` | `ta.cho(high, low, close, volume, fast_period=3, slow_period=10)` | `high`, `low`, `close`, `volume` | `fast_period`=3, `slow_period`=10 | `value` | `{"fast_period": 3, "slow_period": 10}` |
| `chop` | `ta.chop(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `ckstop` | `ta.ckstop(high, low, close, p=10, x=1.0)` | `high`, `low`, `close` | `p`=10, `x`=1.0, `q`=9 | `out0`, `out1` | `{"p": 10, "x": 1.0}` |
| `cmf` | `ta.cmf(high, low, close, volume, period=20)` | `high`, `low`, `close`, `volume` | `period`=20 | `value` | `{"period": 20}` |
| `cmo` | `ta.cmo(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `coppock` | `ta.coppock(close, wma_length=10, long_roc_length=14)` | `close` | `wma_length`=10, `long_roc_length`=14, `short_roc_length`=11 | `value` | `{"wma_length": 10, "long_roc_length": 14}` |
| `crsi` | `ta.crsi(close, lenrsi=3, lenupdown=2)` | `close` | `lenrsi`=3, `lenupdown`=2, `lenroc`=100 | `value` | `{"lenrsi": 3, "lenupdown": 2}` |
| `dema` | `ta.dema(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `dmi` | `ta.dmi(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `out0`, `out1` | `{"period": 14}` |
| `donchian` | `ta.donchian(high, low, period=20)` | `high`, `low` | `period`=20 | `out0`, `out1`, `out2` | `{"period": 20}` |
| `dpo` | `ta.dpo(close, period=21, is_centered=False)` | `close` | `period`=21, `is_centered`=False | `value` | `{"period": 21, "is_centered": False}` |
| `dx` | `ta.dx(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `elderray` | `ta.elderray(high, low, close, period=13)` | `high`, `low`, `close` | `period`=13 | `out0`, `out1` | `{"period": 13}` |
| `ema` | `ta.ema(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `emv` | `ta.emv(high, low, volume, length=14, divisor=10000)` | `high`, `low`, `volume` | `length`=14, `divisor`=10000 | `value` | `{"length": 14, "divisor": 10000}` |
| `falling` | `ta.falling(close, length=1)` | `close` | `length`=1 | `value` | `{"length": 1}` |
| `fisher` | `ta.fisher(high, low, length=9)` | `high`, `low` | `length`=9 | `out0`, `out1` | `{"length": 9}` |
| `force_index` | `ta.force_index(close, volume, length=13)` | `close`, `volume` | `length`=13 | `value` | `{"length": 13}` |
| `fractals` | `ta.fractals(high, low, periods=2)` | `high`, `low` | `periods`=2 | `out0`, `out1` | `{"periods": 2}` |
| `frama` | `ta.frama(high, low, period=26)` | `high`, `low` | `period`=26 | `value` | `{"period": 26}` |
| `gator_oscillator` | `ta.gator_oscillator(high, low, jaw_period=13, teeth_period=8)` | `high`, `low` | `jaw_period`=13, `teeth_period`=8, `lips_period`=5 | `out0`, `out1` | `{"jaw_period": 13, "teeth_period": 8}` |
| `highest` | `ta.highest(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `hma` | `ta.hma(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `hv` | `ta.hv(close, length=10, annual=365)` | `close` | `length`=10, `annual`=365, `per`=1 | `value` | `{"length": 10, "annual": 365}` |
| `ichimoku` | `ta.ichimoku(high, low, close, conversion_periods=9, base_periods=26)` | `high`, `low`, `close` | `conversion_periods`=9, `base_periods`=26, `lagging_span2_periods`=52, `displacement`=26 | `out0`, `out1`, `out2`, `out3`, `out4` | `{"conversion_periods": 9, "base_periods": 26}` |
| `kama` | `ta.kama(close, length=14, fast_length=2)` | `close` | `length`=14, `fast_length`=2, `slow_length`=30 | `value` | `{"length": 14, "fast_length": 2}` |
| `keltner` | `ta.keltner(high, low, close, ema_period=20, atr_period=10)` | `high`, `low`, `close` | `ema_period`=20, `atr_period`=10, `multiplier`=2.0 | `out0`, `out1`, `out2` | `{"ema_period": 20, "atr_period": 10}` |
| `kst` | `ta.kst(close, roclen1=10, roclen2=15)` | `close` | `roclen1`=10, `roclen2`=15, `roclen3`=20, `roclen4`=30, `smalen1`=10, `smalen2`=10, `smalen3`=10, `smalen4`=15, `siglen`=9 | `out0`, `out1` | `{"roclen1": 10, "roclen2": 15}` |
| `kvo` | `ta.kvo(high, low, close, volume, trig_len=13, fast_x=34)` | `high`, `low`, `close`, `volume` | `trig_len`=13, `fast_x`=34, `slow_x`=55 | `out0`, `out1` | `{"trig_len": 13, "fast_x": 34}` |
| `linreg` | `ta.linreg(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `linregangle` | `ta.linregangle(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `linregintercept` | `ta.linregintercept(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `lowest` | `ta.lowest(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `lrslope` | `ta.lrslope(close, period=100, interval=1)` | `close` | `period`=100, `interval`=1 | `value` | `{"period": 100, "interval": 1}` |
| `ma_envelopes` | `ta.ma_envelopes(close, period=20, percentage=2.5)` | `close` | `period`=20, `percentage`=2.5, `ma_type`='SMA' | `out0`, `out1`, `out2` | `{"period": 20, "percentage": 2.5}` |
| `macd` | `ta.macd(close, fast_period=12, slow_period=26)` | `close` | `fast_period`=12, `slow_period`=26, `signal_period`=9 | `out0`, `out1`, `out2` | `{"fast_period": 12, "slow_period": 26}` |
| `massindex` | `ta.massindex(high, low, length=10)` | `high`, `low` | `length`=10 | `value` | `{"length": 10}` |
| `mcginley` | `ta.mcginley(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `median` | `ta.median(close, period=3)` | `close` | `period`=3 | `value` | `{"period": 3}` |
| `medprice` | `ta.medprice(high, low)` | `high`, `low` | - | `value` | `{}` |
| `mfi` | `ta.mfi(high, low, close, volume, period=14)` | `high`, `low`, `close`, `volume` | `period`=14 | `value` | `{"period": 14}` |
| `midpoint` | `ta.midpoint(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `midprice` | `ta.midprice(high, low, period=14)` | `high`, `low` | `period`=14 | `value` | `{"period": 14}` |
| `minus_dm` | `ta.minus_dm(high, low, period=14)` | `high`, `low` | `period`=14 | `value` | `{"period": 14}` |
| `mode` | `ta.mode(close, period=20, bins=10)` | `close` | `period`=20, `bins`=10 | `value` | `{"period": 20, "bins": 10}` |
| `mom` | `ta.mom(close, period=10)` | `close` | `period`=10 | `value` | `{"period": 10}` |
| `natr` | `ta.natr(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `nvi` | `ta.nvi(close, volume)` | `close`, `volume` | - | `value` | `{}` |
| `nvi_with_ema` | `ta.nvi_with_ema(close, volume, ema_length=255)` | `close`, `volume` | `ema_length`=255 | `out0`, `out1` | `{"ema_length": 255}` |
| `obv` | `ta.obv(close, volume)` | `close`, `volume` | - | `value` | `{}` |
| `obv_smoothed` | `ta.obv_smoothed(close, volume, ma_type='None', ma_length=20)` | `close`, `volume` | `ma_type`='None', `ma_length`=20, `bb_length`=20, `bb_mult`=2.0 | `value` | `{"ma_type": "None", "ma_length": 20}` |
| `pivot_points` | `ta.pivot_points(high, low, close)` | `high`, `low`, `close` | - | `out0`, `out1`, `out2`, `out3`, `out4`, `out5`, `out6` | `{}` |
| `plus_dm` | `ta.plus_dm(high, low, period=14)` | `high`, `low` | `period`=14 | `value` | `{"period": 14}` |
| `po` | `ta.po(close, fast_period=10, slow_period=20)` | `close` | `fast_period`=10, `slow_period`=20, `ma_type`='SMA' | `value` | `{"fast_period": 10, "slow_period": 20}` |
| `ppo` | `ta.ppo(close, fast_period=12, slow_period=26)` | `close` | `fast_period`=12, `slow_period`=26, `signal_period`=9 | `out0`, `out1`, `out2` | `{"fast_period": 12, "slow_period": 26}` |
| `psar` | `ta.psar(high, low, acceleration=0.02, maximum=0.2)` | `high`, `low` | `acceleration`=0.02, `maximum`=0.2 | `value` | `{"acceleration": 0.02, "maximum": 0.2}` |
| `pvi` | `ta.pvi(close, volume, initial_value=100.0)` | `close`, `volume` | `initial_value`=100.0 | `value` | `{"initial_value": 100.0}` |
| `pvi_with_signal` | `ta.pvi_with_signal(close, volume, initial_value=100.0, signal_type='EMA')` | `close`, `volume` | `initial_value`=100.0, `signal_type`='EMA', `signal_length`=255 | `out0`, `out1` | `{"initial_value": 100.0, "signal_type": "EMA"}` |
| `pvt` | `ta.pvt(close, volume)` | `close`, `volume` | - | `value` | `{}` |
| `rising` | `ta.rising(close, length=1)` | `close` | `length`=1 | `value` | `{"length": 1}` |
| `roc` | `ta.roc(close, length=14)` | `close` | `length`=14 | `value` | `{"length": 14}` |
| `rocp` | `ta.rocp(close, period=10)` | `close` | `period`=10 | `value` | `{"period": 10}` |
| `rocr` | `ta.rocr(close, period=10)` | `close` | `period`=10 | `value` | `{"period": 10}` |
| `rocr100` | `ta.rocr100(close, period=10)` | `close` | `period`=10 | `value` | `{"period": 10}` |
| `rsi` | `ta.rsi(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `rvi` | `ta.rvi(open, high, low, close, period=10)` | `open`, `high`, `low`, `close` | `period`=10 | `out0`, `out1` | `{"period": 10}` |
| `rvol` | `ta.rvol(volume, period=20)` | `volume` | `period`=20 | `value` | `{"period": 20}` |
| `rwi` | `ta.rwi(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `out0`, `out1` | `{"period": 14}` |
| `sma` | `ta.sma(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `starc` | `ta.starc(high, low, close, ma_period=5, atr_period=15)` | `high`, `low`, `close` | `ma_period`=5, `atr_period`=15, `multiplier`=1.33 | `out0`, `out1`, `out2` | `{"ma_period": 5, "atr_period": 15}` |
| `stc` | `ta.stc(close, fast_length=23, slow_length=50)` | `close` | `fast_length`=23, `slow_length`=50, `cycle_length`=10, `d1_length`=3, `d2_length`=3 | `value` | `{"fast_length": 23, "slow_length": 50}` |
| `stdev` | `ta.stdev(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `stochastic` | `ta.stochastic(high, low, close, k_period=14, smooth_k=3)` | `high`, `low`, `close` | `k_period`=14, `smooth_k`=3, `d_period`=3 | `out0`, `out1` | `{"k_period": 14, "smooth_k": 3}` |
| `stochf` | `ta.stochf(high, low, close, fastk_period=5, fastd_period=3)` | `high`, `low`, `close` | `fastk_period`=5, `fastd_period`=3 | `out0`, `out1` | `{"fastk_period": 5, "fastd_period": 3}` |
| `stochrsi` | `ta.stochrsi(close, rsi_period=14, stoch_period=14)` | `close` | `rsi_period`=14, `stoch_period`=14, `k_period`=3, `d_period`=3 | `out0`, `out1` | `{"rsi_period": 14, "stoch_period": 14}` |
| `supertrend` | `ta.supertrend(high, low, close, period=10, multiplier=3.0)` | `high`, `low`, `close` | `period`=10, `multiplier`=3.0 | `out0`, `out1` | `{"period": 10, "multiplier": 3.0}` |
| `t3` | `ta.t3(close, period=21, v_factor=0.7)` | `close` | `period`=21, `v_factor`=0.7 | `value` | `{"period": 21, "v_factor": 0.7}` |
| `tema` | `ta.tema(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `trima` | `ta.trima(close, period=20)` | `close` | `period`=20 | `value` | `{"period": 20}` |
| `trix` | `ta.trix(close, length=18)` | `close` | `length`=18 | `value` | `{"length": 18}` |
| `true_range` | `ta.true_range(high, low, close)` | `high`, `low`, `close` | - | `value` | `{}` |
| `tsf` | `ta.tsf(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `tsi` | `ta.tsi(close, long_period=25, short_period=13)` | `close` | `long_period`=25, `short_period`=13, `signal_period`=13 | `out0`, `out1` | `{"long_period": 25, "short_period": 13}` |
| `typprice` | `ta.typprice(high, low, close)` | `high`, `low`, `close` | - | `value` | `{}` |
| `ultimate_oscillator` | `ta.ultimate_oscillator(high, low, close, period1=7, period2=14)` | `high`, `low`, `close` | `period1`=7, `period2`=14, `period3`=28 | `value` | `{"period1": 7, "period2": 14}` |
| `uo_oscillator` | `ta.uo_oscillator(high, low, close, period1=7, period2=14)` | `high`, `low`, `close` | `period1`=7, `period2`=14, `period3`=28 | `value` | `{"period1": 7, "period2": 14}` |
| `variance` | `ta.variance(close, lookback=20, mode='PR')` | `close` | `lookback`=20, `mode`='PR', `ema_period`=20, `filter_lookback`=20, `ema_length`=14, `return_components`=False | `value` | `{"lookback": 20, "mode": "PR"}` |
| `vidya` | `ta.vidya(close, period=14, alpha=0.2)` | `close` | `period`=14, `alpha`=0.2 | `value` | `{"period": 14, "alpha": 0.2}` |
| `volosc` | `ta.volosc(volume, short_length=5, long_length=10)` | `volume` | `short_length`=5, `long_length`=10, `check_volume_validity`=True | `value` | `{"short_length": 5, "long_length": 10}` |
| `vroc` | `ta.vroc(volume, period=25)` | `volume` | `period`=25 | `value` | `{"period": 25}` |
| `vwap` | `ta.vwap(high, low, close, volume, anchor='Session', source='hlc3')` | `high`, `low`, `close`, `volume` | `anchor`='Session', `source`='hlc3', `stdev_mult_1`=1.0, `stdev_mult_2`=2.0, `stdev_mult_3`=3.0, `percent_mult_1`=0.236, `percent_mult_2`=0.382, `percent_mult_3`=0.618 | `value` | `{"anchor": "Session", "source": "hlc3"}` |
| `vwma` | `ta.vwma(close, volume, period=14)` | `close`, `volume` | `period`=14 | `value` | `{"period": 14}` |
| `wclprice` | `ta.wclprice(high, low, close)` | `high`, `low`, `close` | - | `value` | `{}` |
| `williams_r` | `ta.williams_r(high, low, close, period=14)` | `high`, `low`, `close` | `period`=14 | `value` | `{"period": 14}` |
| `wma` | `ta.wma(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |
| `zlema` | `ta.zlema(close, period=14)` | `close` | `period`=14 | `value` | `{"period": 14}` |

**116 indicators**, all verified to compute.

## Not available from the `indicator` node

| Function | Why |
|---|---|
| `crossover`, `crossunder`, `cross` | Need two independent series. Use two `indicator` nodes plus an `andGate`. |
| `correlation`, `beta` | Compare two symbols. |
| `exrem`, `flip`, `valuewhen` | Need a second boolean series and carry state across bars. |
| `median_bands`, `ulcerindex`, `vi` | The installed build returns no usable value for these. |

## Using an indicator in Flow

```json
{
  "id": "node_2",
  "type": "indicator",
  "position": { "x": 100, "y": 100 },
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "interval": "5m",
    "indicatorName": "rsi",
    "params": { "period": 14 },
    "outputVariable": "r"
  }
}
```

Read the latest value as `{{r.latest.value}}`, the prior bar as
`{{r.previous.value}}`, and a specific bar back as `{{r.at_offset.value}}`
with `offsetBars` set. For a multi-output indicator use `{{r.latest.out0}}`,
`{{r.latest.out1}}`, and so on.
