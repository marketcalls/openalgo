---
name: indicator-expert
description: OpenAlgo indicator expert. Use when user asks about technical indicators, charting, plotting indicators, creating custom indicators, building dashboards, real-time feeds, scanning stocks, indicator combinations, or using openalgo.ta. Also triggers for indicator functions (sma, ema, rsi, macd, supertrend, bollinger, atr, adx, ichimoku, stochastic, obv, vwap, crossover, crossunder, exrem).
user-invocable: false
---

# OpenAlgo Indicator Expert Skill

## Environment

- Python 3.12+ (required by openalgo 2.x) with openalgo, pandas, numpy, plotly, dash, streamlit
- Data sources: OpenAlgo (Indian markets via `client.history()`, `client.quotes()`, `client.depth()`), yfinance (US/Global)
- Real-time: OpenAlgo WebSocket (`client.connect()`, `subscribe_ltp`, `subscribe_quote`, `subscribe_depth`)
- Indicators: **openalgo.ta** (ALWAYS — 100+ indicators computed by a compiled Rust core, full speed from the first call)
- Charts: Plotly with `template="plotly_dark"`
- Dashboards: Plotly Dash with `dash-bootstrap-components` (default) OR Streamlit with `st.plotly_chart()` — use Streamlit only when the user explicitly asks for it
- Custom indicators: vectorized NumPy composed from openalgo.ta primitives (Rust core — no JIT, no warmup)
- API keys loaded from single root `.env` via `python-dotenv` + `find_dotenv()` — never hardcode keys
- Scripts go in appropriate directories (charts/, dashboards/, custom_indicators/, scanners/) created on-demand
- Never use icons/emojis in code or logger output

## Critical Rules

1. **ALWAYS use openalgo.ta** for ALL technical indicators. Never reimplement what already exists in the library.
2. **Data normalization**: Always convert DataFrame index to datetime, sort, and strip timezone after fetching.
3. **Signal cleaning**: Always use `ta.exrem()` after generating raw buy/sell signals. Always `.fillna(False)` before exrem.
4. **Plotly dark theme**: All charts use `template="plotly_dark"` with `xaxis type="category"` for candlesticks.
5. **Custom indicators**: Compose from openalgo.ta primitives (`ta.sma`, `ta.stdev`, `ta.bbands`, ...) plus vectorized NumPy. Never reimplement built-ins; no JIT or warmup is needed.
6. **Input flexibility**: openalgo.ta accepts numpy arrays, pandas Series, or lists. Output matches input type.
7. **WebSocket feeds**: Use `client.connect()`, `client.subscribe_ltp()` / `subscribe_quote()` / `subscribe_depth()` for real-time data.
8. **Environment**: Load `.env` from project root via `find_dotenv()` — never hardcode API keys.
9. **Market detection**: If symbol looks Indian (SBIN, RELIANCE, NIFTY), use OpenAlgo. If US (AAPL, MSFT), use yfinance.
10. **Always explain** chart outputs in plain language so traders understand what the indicator shows.

## Data Source Priority

| Market | Data Source | Method | Example Symbols |
|--------|------------|--------|-----------------|
| India (equity) | OpenAlgo | `client.history()` | SBIN, RELIANCE, INFY |
| India (index) | OpenAlgo | `client.history(exchange="NSE_INDEX")` | NIFTY, BANKNIFTY |
| India (F&O) | OpenAlgo | `client.history(exchange="NFO")` | NIFTY30DEC25FUT |
| US/Global | yfinance | `yf.download()` | AAPL, MSFT, SPY |

## OpenAlgo API Methods for Data

| Method | Purpose | Returns |
|--------|---------|---------|
| `client.history(symbol, exchange, interval, start_date, end_date)` | OHLCV candles | DataFrame (timestamp, open, high, low, close, volume) |
| `client.quotes(symbol, exchange)` | Real-time snapshot | Dict (open, high, low, ltp, bid, ask, prev_close, volume) |
| `client.multiquotes(symbols=[...])` | Multi-symbol quotes | List of quote dicts |
| `client.depth(symbol, exchange)` | Market depth (L5) | Dict (bids, asks, ohlc, volume, oi) |
| `client.intervals()` | Available intervals | Dict (minutes, hours, days, weeks, months) |
| `client.optionchain(underlying, exchange, expiry_date, strike_count)` | Option chain around ATM | Dict (underlying_ltp, atm_strike, chain with ce/pe per strike) |
| `client.optiongreeks(symbol, exchange, interest_rate, ...)` | Option greeks + IV | Dict (greeks: delta/gamma/theta/vega/rho, implied_volatility, days_to_expiry) |
| `client.expiry(symbol, exchange, instrumenttype)` | Expiry dates list | Dict (data: list of expiry dates) |
| `client.connect()` | WebSocket connect | None (sets up WS connection) |
| `client.subscribe_ltp(instruments, callback)` | Live LTP stream | Callback with `{symbol, exchange, ltp}` |
| `client.subscribe_quote(instruments, callback)` | Live quote stream | Callback with `{symbol, exchange, ohlc, ltp, volume}` |
| `client.subscribe_depth(instruments, callback)` | Live depth stream | Callback with `{symbol, exchange, bids, asks}` |

## Indicator Library Reference

All indicators accessed via `from openalgo import ta`:

### Trend (20)
`ta.sma`, `ta.ema`, `ta.wma`, `ta.dema`, `ta.tema`, `ta.hma`, `ta.vwma`, `ta.alma`, `ta.kama`, `ta.zlema`, `ta.t3`, `ta.frama`, `ta.supertrend`, `ta.ichimoku`, `ta.chande_kroll_stop`, `ta.trima`, `ta.mcginley`, `ta.vidya`, `ta.alligator`, `ta.ma_envelopes`

### Momentum (9)
`ta.rsi`, `ta.macd`, `ta.stochastic`, `ta.cci`, `ta.williams_r`, `ta.bop`, `ta.elder_ray`, `ta.fisher`, `ta.crsi`

### Volatility (16)
`ta.atr`, `ta.bbands`, `ta.keltner`, `ta.donchian`, `ta.chaikin_volatility`, `ta.natr`, `ta.rvi`, `ta.ultimate_oscillator`, `ta.true_range`, `ta.massindex`, `ta.bb_percent`, `ta.bb_width`, `ta.chandelier_exit`, `ta.historical_volatility`, `ta.ulcer_index`, `ta.starc`

### Volume (15)
`ta.obv`, `ta.obv_smoothed`, `ta.vwap`, `ta.mfi`, `ta.adl`, `ta.cmf`, `ta.emv`, `ta.force_index`, `ta.nvi`, `ta.pvi`, `ta.volosc`, `ta.vroc`, `ta.kvo`, `ta.pvt`, `ta.rvol`

### Oscillators (20+)
`ta.cmo`, `ta.trix`, `ta.uo_oscillator`, `ta.awesome_oscillator`, `ta.accelerator_oscillator`, `ta.ppo`, `ta.po`, `ta.dpo`, `ta.aroon_oscillator`, `ta.stoch_rsi`, `ta.rvi_oscillator`, `ta.cho`, `ta.chop`, `ta.kst`, `ta.tsi`, `ta.vortex`, `ta.gator_oscillator`, `ta.stc`, `ta.coppock`, `ta.roc`

### Statistical (9)
`ta.linreg`, `ta.lrslope`, `ta.correlation`, `ta.beta`, `ta.variance`, `ta.tsf`, `ta.median`, `ta.mode`, `ta.median_bands`

### Hybrid (6+)
`ta.adx`, `ta.dmi`, `ta.aroon`, `ta.pivot_points`, `ta.sar`, `ta.williams_fractals`, `ta.rwi`

### TA-Lib Compatible (18, new in openalgo 2.0)
`ta.mom`, `ta.rocp`, `ta.rocr`, `ta.rocr100`, `ta.apo`, `ta.midpoint`, `ta.midprice`, `ta.avgprice`, `ta.medprice`, `ta.typprice`, `ta.wclprice`, `ta.plus_dm`, `ta.minus_dm`, `ta.dx`, `ta.adxr`, `ta.stochf`, `ta.linregangle`, `ta.linregintercept`

### Utilities
`ta.crossover`, `ta.crossunder`, `ta.cross`, `ta.highest`, `ta.lowest`, `ta.change`, `ta.roc`, `ta.stdev`, `ta.exrem`, `ta.flip`, `ta.valuewhen`, `ta.rising`, `ta.falling`

## Modular Rule Files

Detailed reference for each topic is in `rules/`:

| Rule File | Topic |
|-----------|-------|
| [indicator-catalog](rules/indicator-catalog.md) | Complete 100+ indicator reference with signatures and parameters |
| [data-fetching](rules/data-fetching.md) | OpenAlgo history/quotes/depth, yfinance, data normalization |
| [plotting](rules/plotting.md) | Plotly candlestick, overlay, subplot, multi-panel charts |
| [custom-indicators](rules/custom-indicators.md) | Building custom indicators with vectorized NumPy + ta primitives |
| [websocket-feeds](rules/websocket-feeds.md) | Real-time LTP/Quote/Depth streaming via WebSocket |
| [performance](rules/performance.md) | Rust core performance, O(n) guarantees, benchmarking |
| [dashboard-patterns](rules/dashboard-patterns.md) | Plotly Dash web applications with callbacks |
| [streamlit-patterns](rules/streamlit-patterns.md) | Streamlit web applications with sidebar, metrics, plotly charts |
| [multi-timeframe](rules/multi-timeframe.md) | Multi-timeframe indicator analysis |
| [signal-generation](rules/signal-generation.md) | Signal generation, cleaning, crossover/crossunder |
| [indicator-combinations](rules/indicator-combinations.md) | Combining indicators for confluence analysis |
| [symbol-format](rules/symbol-format.md) | OpenAlgo symbol format, exchange codes, index symbols |

## Chart Templates (in rules/assets/)

| Template | Path | Description |
|----------|------|-------------|
| EMA Chart | `assets/ema_chart/chart.py` | EMA overlay on candlestick |
| RSI Chart | `assets/rsi_chart/chart.py` | RSI with overbought/oversold zones |
| MACD Chart | `assets/macd_chart/chart.py` | MACD line, signal, histogram |
| Supertrend | `assets/supertrend_chart/chart.py` | Supertrend overlay with direction coloring |
| Bollinger | `assets/bollinger_chart/chart.py` | Bollinger Bands with squeeze detection |
| Multi-Indicator | `assets/multi_indicator/chart.py` | Candlestick + EMA + RSI + MACD + Volume |
| Basic Dashboard | `assets/dashboard_basic/app.py` | Single-symbol Plotly Dash app |
| Multi Dashboard | `assets/dashboard_multi/app.py` | Multi-symbol multi-timeframe dashboard |
| Streamlit Basic | `assets/streamlit_basic/app.py` | Single-symbol Streamlit app |
| Streamlit Multi | `assets/streamlit_multi/app.py` | Multi-timeframe Streamlit app |
| Custom Indicator | `assets/custom_indicator/template.py` | NumPy custom indicator template (composes ta primitives) |
| Live Feed | `assets/live_feed/template.py` | WebSocket real-time indicator |
| Scanner | `assets/scanner/template.py` | Multi-symbol indicator scanner |

## Quick Template: Standard Indicator Chart Script

```python
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

# --- Config ---
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "D"

# --- Fetch Data ---
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365)

df = client.history(
    symbol=SYMBOL, exchange=EXCHANGE, interval=INTERVAL,
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)
df = df.sort_index()
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)

close = df["close"]
high = df["high"]
low = df["low"]
volume = df["volume"]

# --- Compute Indicators ---
ema_20 = ta.ema(close, 20)
rsi_14 = ta.rsi(close, 14)

# --- Chart ---
fig = make_subplots(
    rows=2, cols=1, shared_xaxes=True,
    row_heights=[0.7, 0.3], vertical_spacing=0.03,
    subplot_titles=[f"{SYMBOL} Price + EMA(20)", "RSI(14)"],
)

# Candlestick
x_labels = df.index.strftime("%Y-%m-%d")
fig.add_trace(go.Candlestick(
    x=x_labels, open=df["open"], high=high, low=low, close=close,
    name="Price",
), row=1, col=1)

# EMA overlay
fig.add_trace(go.Scatter(
    x=x_labels, y=ema_20, mode="lines",
    name="EMA(20)", line=dict(color="cyan", width=1.5),
), row=1, col=1)

# RSI subplot
fig.add_trace(go.Scatter(
    x=x_labels, y=rsi_14, mode="lines",
    name="RSI(14)", line=dict(color="yellow", width=1.5),
), row=2, col=1)
fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

fig.update_layout(
    template="plotly_dark", title=f"{SYMBOL} Technical Analysis",
    xaxis_rangeslider_visible=False, xaxis_type="category",
    xaxis2_type="category", height=700,
)
fig.show()
```
