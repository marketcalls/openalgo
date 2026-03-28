# Strategy Survey — D:\test1 Python Strategies
**Date:** 2026-03-22
**Data:** RELIANCE 15m, 5,029 bars
**Lookahead:** 8 bars (~2 hours) for win/loss labeling

---

## 1. Existing Strategies (Previously Tested)

| Strategy | Signals | Win Rate | Notes |
|---|---|---|---|
| trend_signals_tp_sl_ualgo | 183 | 60.1% | Best single strategy; MULTIPLIER=2.6 is key |
| reversal_radar_v2 | 556 | 53.1% | Strong in combos (SHORT side esp.) |
| central_pivot_range | 4,333 | 47.1% | High frequency; useful as confirmation filter |
| twin_range_filter | 3,708 | 48.3% | Trend-following; good as 3rd/4th filter |
| vwap_bb_super_confluence_2 | 601 | 53.2% | Fixed signal_adapter; reversal columns only |
| bahai_reversal_points | 8 | 50.0% | Too few signals; only high-conviction use |

---

## 2. New Strategies — Audit Results

### 2.1 Strategies That Produce Usable Signals

| Strategy | Signals | Long | Short | Win Rate | Long WR | Short WR | Status |
|---|---|---|---|---|---|---|---|
| **sfp_candelacharts** | 161 | 104 | 57 | **58.4%** | 58.7% | 57.9% | ✅ Excellent |
| **outside_reversal** | 117 | 34 | 83 | **54.7%** | 47.1% | **57.8%** | ✅ Good (SHORT-biased) |
| **dark_cloud_piercing_line_tradingfinder** | 74 | 36 | 38 | 51.4% | 38.9% | **63.2%** | ⚠️ SHORT only reliable |
| **n_bar_reversal_luxalgo** | 174 | 91 | 83 | 52.3% | **57.1%** | 47.0% | ✅ LONG-biased |
| three_inside_tradingfinder | 231 | 127 | 104 | 49.4% | 54.3% | 43.3% | ⚠️ LONG ok, SHORT poor |
| bollinger_band_breakout | 745 | 745 | 0 | 50.7% | 50.7% | — | ⚠️ LONG only, marginal |
| candlestick_patterns_identified | 1,017 | 501 | 516 | 50.0% | 49.3% | 50.8% | ❌ No edge |
| previous_candle_inside_outside_mk | 803 | 390 | 413 | 49.8% | 48.5% | 51.1% | ❌ No edge |
| n_bar_reversal_luxalgo_strategy | 4,881 | 2,508 | 2,373 | 51.7% | — | — | ❌ State indicator (every bar) |
| sbs_swing_areas_trades | 4,963 | 2,231 | 2,732 | 49.2% | — | — | ❌ State indicator (every bar) |
| double_top_bottom_ultimate | 5,028 | 2,501 | 2,527 | 47.7% | — | — | ❌ State indicator (every bar) |
| impulse_trend_boswaves | 4,990 | 2,504 | 2,486 | 47.8% | — | — | ❌ State indicator (every bar) |
| hybrid_ml_vwap_bb | 24 | 9 | 15 | 29.2% | 0.0% | 46.7% | ❌ Below random |

### 2.2 Strategies With 0 Signals (via adapter)

| Strategy | Reason |
|---|---|
| cm_hourly_pivots | Outputs pivot levels (price values), not directional signals |
| rsi_divergence | Outputs RSI indicator values, no entry/exit columns |
| flowscope_hapharmonic | Pure bar coloring / volume profile visual — only `Bar_Color` column; no directional signals |
| vwap_bb_confluence | `Upper_Meet`/`Lower_Meet` fire on ALL 5,029 bars (always-on state). `Upper_Confluence` SHORT WR = 37.3% (bad). `Lower_Confluence` LONG WR = 65.8% on 79 signals — potentially useful but needs custom extraction. Marked for future investigation. |

### 2.3 Errors

| Strategy | Error |
|---|---|
| harmonic_strategy | `AttributeError: module has no attribute 'calculate_indicators'` — wrong function name |

### 2.4 State Indicators (fire every bar)

| Strategy | Signals | Win Rate | Reason Excluded |
|---|---|---|---|
| double_top_bottom_ultimate | 5,028 | 47.7% | Trend state — fires on every bar |
| impulse_trend_boswaves | 4,990 | 47.8% | Trend state — fires on every bar |
| sbs_swing_areas_trades | 4,963 | 49.2% | Swing area state — fires on every bar |
| n_bar_reversal_luxalgo_strategy | 4,881 | 51.7% | Strategy variant fires every bar |
| vedhaviyash4_daily_cpr | 4,729 | 46.9% | CPR pivot band state — fires on every bar; duplicate of central_pivot_range |

---

## 3. Signal Adapter Fixes Applied

### 3.1 New Tokens Added to SIGNAL_PRIORITY
| Token | Direction | Rationale |
|---|---|---|
| `"piercing"` | +1 (LONG) | Detects `Strong_Piercing_Line` column from dark_cloud_piercing_line strategy |
| `"dark_cloud"` | -1 (SHORT) | Detects `Strong_Dark_Cloud` column from dark_cloud_piercing_line strategy |

### 3.2 Color Column Exclusion
Added `_is_color_column()` filter to skip columns whose names end in visualization suffixes:
`_colorer`, `_color`, `_color_code`, `_candle_color`, `_bar_color`

**Impact:** Fixed `three_inside_tradingfinder` (5,029 → 231 signals) and `dark_cloud_piercing_line_tradingfinder` (36 SHORT-only → 74 balanced).

---

## 4. Strategies Selected for Extended Confluence Optimizer

| Strategy | Source | Params Used |
|---|---|---|
| trend_signals_tp_sl_ualgo | Existing | Optimized: MULTIPLIER=2.6, ATR_PERIOD=10 |
| reversal_radar_v2 | Existing | Optimized: BLOCK_START=16, BLOCK_END=7 |
| central_pivot_range | Existing | Default |
| twin_range_filter | Existing | Optimized: PER1=27, MULT1=1.28, PER2=55, MULT2=1.6 |
| vwap_bb_super_confluence_2 | Existing | Optimized: bb_len1=30, require_double_touch=False |
| bahai_reversal_points | Existing | Optimized: LENGTH=25, LOOKBACK_LENGTH=6 |
| **sfp_candelacharts** | **NEW** | Default |
| **outside_reversal** | **NEW** | Default |
| **dark_cloud_piercing_line_tradingfinder** | **NEW** | Default |
| **n_bar_reversal_luxalgo** | **NEW** | Default |

**Excluded from optimizer:**
- `double_top_bottom_ultimate`, `impulse_trend_boswaves`, `sbs_swing_areas_trades`, `n_bar_reversal_luxalgo_strategy`, `vedhaviyash4_daily_cpr` — fire on every bar (state indicators, not event signals)
- `hybrid_ml_vwap_bb` — below-random win rate (29.2%)
- `candlestick_patterns_identified`, `previous_candle_inside_outside_mk`, `bollinger_band_breakout`, `three_inside_tradingfinder` — no meaningful edge above 50%
- `cm_hourly_pivots`, `rsi_divergence`, `flowscope_hapharmonic` — 0 signals (no directional columns)
- `harmonic_strategy` — import error (function name mismatch)
- `vwap_bb_confluence` — adapter produces 0 signals; needs custom extraction (future work)

**COMPLETE AUDIT STATUS: ALL 25 Python strategy files from D:\test1\ have been audited. No further untested strategies remain.**

---

## 6. SMC Strategies from D:\test1\opensource_indicators\smart-money-concepts

Three new wrapper strategies built from the SMC (Smart Money Concepts) library.

| Strategy | File | Signals | Win Rate | Long WR | Short WR | Status |
|---|---|---|---|---|---|---|
| **smc_fvg** | `D:\test1\smc_fvg.py` | 985 | **58.2%** | 60.1% | 56.3% | ✅ Excellent |
| **smc_bos** | `D:\test1\smc_bos.py` | 237 | **73.8%** | 70.0% | 77.2% | ✅ Outstanding |
| **smc_ob** | `D:\test1\smc_ob.py` | 22 | **95.5%** | 100.0% | 90.9% | ✅ Exceptional (small sample) |

### Signal Descriptions
- **smc_fvg** (Fair Value Gap): 3-bar price gap where prev high < next low (bullish) or prev low > next high (bearish). Indicates momentum continuation toward filling the gap. High frequency (985/5029 = 20% of bars).
- **smc_bos** (Break of Structure): Price closes above a swing high (bullish BOS) or below a swing low (bearish BOS). Confirms market structure has shifted. swing_length=3 (most sensitive). 237 signals.
- **smc_ob** (Order Blocks): The last opposing candle before a significant structural break — where institutions placed large orders. Very selective (22 signals) but near-perfect win rate.

### Libraries Reviewed (rest excluded)
| Library | Status | Reason |
|---|---|---|
| pyharmonics | ❌ Excluded | Requires live API data — 0 patterns detected on local CSV |
| ZigZag | ❌ Excluded | Compiled Cython (.pyx) — needs build tools, no precompiled Windows binary |
| trendln | ❌ Excluded | Support/resistance line slopes — not event signals |
| finta, ta-library, talipp, ta-py, stockstats, mintalib, pyti | ❌ Excluded | Standard indicators only (RSI/MACD/BB) — no standalone event signals |
| py-market-profile, streaming_indicators | ❌ Excluded | Not applicable to batch backtesting |
| pandas-ta-classic | ❌ Excluded | Generic CDL patterns — no directional edge found |

---

## 5. Key Findings Per Strategy

### sfp_candelacharts (Swing Failure Points)
- Detects swing failure patterns (SFP): price briefly breaks a swing high/low then reverses
- Both LONG (58.7%) and SHORT (57.9%) sides are reliable
- **Best complement to trend_signals** — produces 92% win rate together (25 signals)
- Columns used: `bullish_sfp` (LONG), `bearish_sfp` (SHORT)

### outside_reversal
- Detects outside bar reversals (engulfing candle reversals)
- SHORT side (57.8%) is significantly better than LONG (47.1%)
- Very selective: 117 signals in 5,029 bars
- **Excellent 3rd/4th filter** — 100% win rate combos with trend_signals

### dark_cloud_piercing_line_tradingfinder
- SHORT side (63.2%) is excellent; LONG side (38.9%) is harmful
- When using in combos: direction-aware filtering naturally suppresses harmful LONG signals
- Only use when combined with 2+ other strategies to filter direction

### n_bar_reversal_luxalgo
- LONG side (57.1%) is reliable; SHORT (47.0%) is below average
- 174 signals — good frequency for confirmation
- **Strong complement to trend_signals** — 86.4% win rate together (22 signals)
