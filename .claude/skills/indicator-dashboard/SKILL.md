---
name: indicator-dashboard
description: Build a web dashboard for technical indicator analysis using Plotly Dash or Streamlit. Supports single-symbol, multi-symbol, and multi-timeframe layouts with real-time refresh.
argument-hint: "[type] [symbol]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

Create a web dashboard for interactive technical analysis using Plotly Dash or Streamlit.

## Arguments

Parse `$ARGUMENTS` as: type symbol

- `$0` = dashboard type. Default: single
  - **Dash types**: `single`, `multi-symbol`, `multi-timeframe`, `scanner-dashboard`
  - **Streamlit types**: `streamlit-single`, `streamlit-multi`, `streamlit-scanner`
- `$1` = symbol (e.g., SBIN, RELIANCE). Default: SBIN

If no arguments, ask the user what kind of dashboard they want and whether they prefer Dash or Streamlit.

**Framework choice**: Plotly Dash is the default. Build a Streamlit app ONLY when the user explicitly asks for Streamlit (says "streamlit" or picks a `streamlit-*` type). Never silently switch frameworks.

## Instructions

1. Read the indicator-expert rules, especially:
   - `rules/dashboard-patterns.md` — Dash app patterns
   - `rules/streamlit-patterns.md` — Streamlit app patterns
   - `rules/plotting.md` — Chart patterns
   - `rules/data-fetching.md` — Data loading
2. Create `dashboards/{dashboard_name}/` directory (on-demand)
3. Create `app.py` in `dashboards/{dashboard_name}/`
4. Use the matching template from `rules/assets/`

### Dashboard Requirements

All dashboards must include:
- **Dark theme**: Dash uses `dbc.themes.DARKLY`; Streamlit uses `[theme] base = "dark"` or CSS injection
- **Symbol input**: Text input or dropdown for symbol selection
- **Exchange selector**: NSE, BSE, NFO, NSE_INDEX
- **Interval selector**: 1m, 5m, 15m, 1h, D
- **Indicator selectors**: Checkboxes/multiselect for overlay and subplot indicators
- **Interactive chart**: Plotly chart with `template="plotly_dark"`, `xaxis_type="category"`
- **Stats display**: Key metrics (LTP, Change, Volume, indicator values)
- **Auto-refresh**: Dash uses `dcc.Interval`; Streamlit uses `st.rerun()` with `time.sleep()`
- **Load `.env`** from project root via `find_dotenv()`

### Dash Dashboard Types

#### `single` — Single Symbol Dashboard (Dash)
- One symbol with configurable indicators
- Overlays: EMA, SMA, Bollinger, Supertrend, Ichimoku (checkboxes)
- Subplots: RSI, MACD, Stochastic, Volume, ADX, OBV (checkboxes)
- Stats panel: LTP, day change, volume, selected indicator values
- Template: `rules/assets/dashboard_basic/app.py`

#### `multi-symbol` — Multi-Symbol Watchlist (Dash)
- 4-6 symbols in a grid layout
- Each cell shows candlestick + one overlay indicator
- Bottom row: RSI comparison across all symbols
- Symbol list editable via input

#### `multi-timeframe` — MTF Analysis (Dash)
- 4-panel grid: 5m, 15m, 1h, D for same symbol
- Same indicators computed on each timeframe
- Confluence summary: "3/4 timeframes bullish"
- Template: `rules/assets/dashboard_multi/app.py`

#### `scanner-dashboard` — Live Scanner (Dash)
- Watchlist of 10+ symbols
- Table showing: Symbol, LTP, RSI, EMA trend, Signal
- Color-coded rows (green=bullish, red=bearish)
- Click symbol to show detailed chart
- Auto-refresh every 30 seconds

### Streamlit Dashboard Types

#### `streamlit-single` — Single Symbol Dashboard (Streamlit)
- Sidebar: symbol, exchange, interval, overlay/subplot multiselect
- `st.plotly_chart()` for interactive charts
- `st.metric()` for LTP, Change, RSI, EMA stats
- Auto-refresh via checkbox + `st.rerun()`
- Template: `rules/assets/streamlit_basic/app.py`

#### `streamlit-multi` — MTF Analysis (Streamlit)
- 2x2 grid via `st.columns(2)` for 4 timeframes
- Candlestick + EMA overlay per timeframe
- Confluence summary with `st.success()`/`st.error()`/`st.warning()`
- `st.metric()` cards for each timeframe trend
- Template: `rules/assets/streamlit_multi/app.py`

#### `streamlit-scanner` — Scanner Dashboard (Streamlit)
- Sidebar: scan type selector, run button
- `st.progress()` during scan
- `st.dataframe()` for results table
- `st.download_button()` for CSV export

### Running the Dashboard

After creating the app, provide instructions:

**Dash:**
```bash
cd dashboards/{dashboard_name}
python app.py
# Open http://127.0.0.1:8050 in browser
```

**Streamlit:**
```bash
cd dashboards/{dashboard_name}
streamlit run app.py
# Open http://localhost:8501 in browser
```

## Example Usage

`/indicator-dashboard single SBIN`
`/indicator-dashboard multi-timeframe RELIANCE`
`/indicator-dashboard scanner-dashboard`
`/indicator-dashboard streamlit-single SBIN`
`/indicator-dashboard streamlit-multi RELIANCE`
`/indicator-dashboard streamlit-scanner`
