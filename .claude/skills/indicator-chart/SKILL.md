---
name: indicator-chart
description: Chart any technical indicator on a symbol using Plotly. Creates interactive dark-themed charts with candlestick, overlays, and subplots. Supports all 100+ openalgo.ta indicators.
argument-hint: "[indicator] [symbol] [exchange] [interval]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Create an interactive Plotly chart for a technical indicator on a symbol.

## Arguments

Parse `$ARGUMENTS` as: indicator symbol exchange interval

- `$0` = indicator name (e.g., ema, rsi, macd, supertrend, bbands, adx, stochastic, ichimoku, obv, vwap). Default: ema
- `$1` = symbol (e.g., SBIN, RELIANCE, NIFTY, AAPL). Default: SBIN
- `$2` = exchange (e.g., NSE, BSE, NFO, NSE_INDEX). Default: NSE. For US symbols use: YFINANCE
- `$3` = interval (e.g., D, 1h, 5m). Default: D

If no arguments, ask the user which indicator and symbol they want.

## Instructions

1. Read the indicator-expert skill rules for reference patterns
2. Create `workspace/indicators/charts/` if it doesn't exist (`mkdir -p`)
3. Write the script to `workspace/indicators/charts/{indicator}_{symbol}_{interval}.py`
4. Use the matching template from `rules/assets/{indicator}_chart/chart.py` as starting point (if available)
5. The script must:
   - Load `.env` from project root using `find_dotenv()`
   - Fetch data via OpenAlgo `client.history()` (or yfinance for US symbols)
   - **Normalize data**: convert index to datetime, sort, strip timezone
   - Compute the indicator using `openalgo.ta`
   - Create a Plotly chart with `template="plotly_dark"` and `xaxis_type="category"`
   - **Overlay indicators** (EMA, Bollinger, Supertrend, Ichimoku) go on the candlestick panel
   - **Subplot indicators** (RSI, MACD, Stochastic, ADX, Volume, OBV) go below in separate panels
   - Use `make_subplots` for multi-panel layouts
   - Add horizontal reference lines where appropriate (RSI 30/70, Stochastic 20/80)
   - Print a plain-language explanation of the current indicator reading
   - Save the rendered HTML to `workspace/indicators/output/` under the same stem as the script
   - Show chart with `fig.show()`
6. Never use icons/emojis in code or output

## Indicator Chart Types

### Overlay Indicators (on candlestick panel)
| Indicator | Chart Type |
|-----------|-----------|
| ema, sma, wma, dema, tema, hma | Line overlay |
| bbands | Fill-between bands + midline |
| supertrend | Color-coded line (green=up, red=down) |
| ichimoku | 5 lines + cloud fill |
| keltner, donchian | Fill-between channels |
| sar | Dot markers above/below price |
| ma-envelopes | Upper/lower band lines |

### Subplot Indicators (separate panel below)
| Indicator | Chart Type |
|-----------|-----------|
| rsi | Line + horizontal 30/70 zones |
| macd | Line + signal + histogram bars |
| stochastic | K% + D% lines + 20/80 zones |
| adx | DI+, DI-, ADX lines + 25 threshold |
| cci | Line + horizontal +100/-100 zones |
| williams_r | Line + -20/-80 zones |
| obv | Line (cumulative) |
| mfi | Line + 20/80 zones |
| volume | Bar chart (green/red by price direction) |
| atr | Line (volatility) |

### Multi-Indicator Charts
If user asks for "multi" or multiple indicators, create a comprehensive multi-panel chart with:
- Row 1: Candlestick + EMA overlays
- Row 2: RSI(14)
- Row 3: MACD(12,26,9)
- Row 4: Volume bars

## Signal Markers

If the indicator generates clear buy/sell signals (e.g., crossover, supertrend direction change), add triangle markers:
- Buy: green triangle-up markers
- Sell: red triangle-down markers

## Data Periods

| Interval | Default Lookback |
|----------|-----------------|
| D | 1 year (365 days) |
| 1h | 6 months (180 days) |
| 15m, 30m | 3 months (90 days) |
| 5m | 1 month (30 days) |
| 1m | 7 days |

## Plain-Language Explanation

After creating the chart, print a brief explanation:

```
SBIN — RSI(14) Analysis
Current RSI: 42.3
Interpretation: Neutral zone (between 30-70). Neither overbought nor oversold.
Trend: RSI has been declining from 65 over the past 5 bars, suggesting weakening momentum.
```

## Example Usage

`/indicator-chart ema SBIN NSE D`
`/indicator-chart rsi RELIANCE NSE D`
`/indicator-chart macd AAPL YFINANCE D`
`/indicator-chart supertrend NIFTY NSE_INDEX D`
`/indicator-chart multi SBIN NSE D`
`/indicator-chart bbands INFY NSE 1h`

## Verify before calling it done

A chart that renders is not a chart that is correct. Check all five:

- [ ] **Bar count matches the request.** `len(df)` against the interval and date range. A silently short series usually means the broker's history endpoint capped the range, or the symbol has no data on that exchange.
- [ ] **Warmup behaviour matches the indicator.** This is per-indicator in `openalgo.ta`, not universal — verified against 2.0.3: `sma(close, 20)` gives 19 leading NaNs and `rsi(close, 14)` gives 14, but **`ema` gives zero** because it seeds from the first value and recurses. Do not "fix" an EMA that has no NaNs. What matters is that the count is *stable* for that indicator; a sudden change means the input gained gaps.
- [ ] **Indicator length equals input length.** `len(result) == len(close)`. A shorter array means it was computed on a slice and will misalign against the price axis.
- [ ] **Spot-check one value against an independent source.** Read the last close and the last indicator value off the chart and compare with the broker's own chart or a hand calculation. Plotting the wrong column is invisible unless you check a number.
- [ ] **The overlay sits on the right axis.** Price-scale indicators (EMA, Bollinger, Supertrend, VWAP) belong on the candlestick axis; bounded oscillators (RSI, MACD, Stochastic) belong in a subplot. An RSI drawn on the price axis renders as a flat line at the bottom.

**Timestamps:** daily candles should land at IST midnight, intraday at the true
bar time. A daily candle showing 18:30 the previous day means the epoch was not
shifted; 05:30 means it was shifted twice.

## Where to write files

Default location is **`workspace/indicators/charts/`** in the repo root. Create it
immediately before writing — it does not exist on a fresh clone:

```bash
mkdir -p workspace/indicators/charts
```

Name the file `<indicator>_<symbol>_<interval>.py` so the folder stays
scannable as it grows, e.g. `workspace/indicators/charts/ema_SBIN_D.py`.

Rendered output goes to `workspace/indicators/output/` under the same stem, keeping the
script and its artifact associated without cluttering the source folder:

```
workspace/indicators/charts/ema_SBIN_D.py  ->  workspace/indicators/output/ema_SBIN_D.html
```

**If the user names a different folder, use it** and keep the same layout
beneath it. Note that only `workspace/` is gitignored (except its readme), so
writing elsewhere inside the repo produces tracked files — mention that before
doing it.

Run from the repo root:

```bash
uv run --group analysis python workspace/indicators/charts/ema_SBIN_D.py
```
