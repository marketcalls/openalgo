# Dashboard Patterns — Plotly Dash Web Applications

## Basic Dash App Structure

```python
import dash
from dash import dcc, html, Input, Output, callback
import dash_bootstrap_components as dbc

app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("OpenAlgo Indicator Dashboard"), width=12),
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Label("Symbol"),
            dbc.Input(id="symbol-input", value="SBIN", type="text"),
        ], width=3),
        dbc.Col([
            dbc.Label("Exchange"),
            dbc.Select(id="exchange-select", value="NSE",
                       options=[{"label": e, "value": e}
                                for e in ["NSE", "BSE", "NFO", "NSE_INDEX"]]),
        ], width=3),
        dbc.Col([
            dbc.Label("Interval"),
            dbc.Select(id="interval-select", value="D",
                       options=[{"label": i, "value": i}
                                for i in ["1m", "5m", "15m", "1h", "D"]]),
        ], width=3),
        dbc.Col([
            dbc.Button("Update", id="update-btn", color="primary", className="mt-4"),
        ], width=3),
    ], className="mb-3"),
    dbc.Row([
        dbc.Col(dcc.Graph(id="main-chart"), width=12),
    ]),
], fluid=True)


@callback(
    Output("main-chart", "figure"),
    Input("update-btn", "n_clicks"),
    Input("symbol-input", "value"),
    Input("exchange-select", "value"),
    Input("interval-select", "value"),
)
def update_chart(n_clicks, symbol, exchange, interval):
    # Fetch data and compute indicators
    df = fetch_data(symbol, exchange, interval)
    fig = create_chart(df, symbol)
    return fig


if __name__ == "__main__":
    app.run(debug=True, port=8050)
```

---

## Multi-Indicator Dashboard Layout

```python
app.layout = dbc.Container([
    # Header
    dbc.Row([
        dbc.Col(html.H3("Technical Analysis Dashboard"), width=8),
        dbc.Col([
            dbc.InputGroup([
                dbc.Input(id="symbol-input", value="SBIN", placeholder="Symbol"),
                dbc.Button("Load", id="load-btn", color="primary"),
            ]),
        ], width=4),
    ], className="mb-3"),

    # Indicator selectors
    dbc.Row([
        dbc.Col([
            dbc.Label("Overlays"),
            dbc.Checklist(
                id="overlay-select",
                options=[
                    {"label": "EMA(20)", "value": "ema20"},
                    {"label": "EMA(50)", "value": "ema50"},
                    {"label": "Bollinger Bands", "value": "bbands"},
                    {"label": "Supertrend", "value": "supertrend"},
                ],
                value=["ema20"],
                inline=True,
            ),
        ], width=6),
        dbc.Col([
            dbc.Label("Subplots"),
            dbc.Checklist(
                id="subplot-select",
                options=[
                    {"label": "RSI", "value": "rsi"},
                    {"label": "MACD", "value": "macd"},
                    {"label": "Volume", "value": "volume"},
                    {"label": "ADX", "value": "adx"},
                    {"label": "Stochastic", "value": "stochastic"},
                ],
                value=["rsi", "volume"],
                inline=True,
            ),
        ], width=6),
    ], className="mb-3"),

    # Charts
    dbc.Row([
        dbc.Col(dcc.Graph(id="main-chart"), width=12),
    ]),

    # Stats cards
    dbc.Row(id="stats-row", className="mt-3"),

    # Auto-refresh
    dcc.Interval(id="refresh-interval", interval=60_000, n_intervals=0),
], fluid=True)
```

---

## Callback Pattern: Dynamic Subplots

```python
from plotly.subplots import make_subplots
import plotly.graph_objects as go

@callback(
    Output("main-chart", "figure"),
    Input("load-btn", "n_clicks"),
    Input("symbol-input", "value"),
    Input("overlay-select", "value"),
    Input("subplot-select", "value"),
)
def update_chart(n_clicks, symbol, overlays, subplots):
    df = fetch_data(symbol, "NSE", "D")
    close = df["close"]
    high = df["high"]
    low = df["low"]
    x_labels = df.index.strftime("%Y-%m-%d")

    n_rows = 1 + len(subplots)
    row_heights = [0.5] + [0.5 / len(subplots)] * len(subplots) if subplots else [1.0]

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=row_heights, vertical_spacing=0.03,
    )

    # Row 1: Candlestick + overlays
    fig.add_trace(go.Candlestick(
        x=x_labels, open=df["open"], high=high, low=low, close=close,
        name="Price", showlegend=False,
    ), row=1, col=1)

    if "ema20" in overlays:
        fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 20),
                                 name="EMA(20)", line=dict(color="cyan")),
                      row=1, col=1)
    if "bbands" in overlays:
        upper, mid, lower = ta.bbands(close, 20, 2.0)
        fig.add_trace(go.Scatter(x=x_labels, y=upper, name="BB Upper",
                                 line=dict(color="gray", dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=lower, name="BB Lower",
                                 line=dict(color="gray", dash="dash"),
                                 fill="tonexty", fillcolor="rgba(128,128,128,0.1)"),
                      row=1, col=1)

    # Dynamic subplots
    for i, sp in enumerate(subplots, start=2):
        if sp == "rsi":
            fig.add_trace(go.Scatter(x=x_labels, y=ta.rsi(close, 14),
                                     name="RSI(14)", line=dict(color="yellow")),
                          row=i, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", row=i, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", row=i, col=1)
        elif sp == "macd":
            m, s, h = ta.macd(close, 12, 26, 9)
            fig.add_trace(go.Scatter(x=x_labels, y=m, name="MACD",
                                     line=dict(color="cyan")), row=i, col=1)
            fig.add_trace(go.Scatter(x=x_labels, y=s, name="Signal",
                                     line=dict(color="orange")), row=i, col=1)
        elif sp == "volume":
            colors = ["green" if c >= o else "red"
                      for c, o in zip(close, df["open"])]
            fig.add_trace(go.Bar(x=x_labels, y=df["volume"], name="Volume",
                                 marker_color=colors, opacity=0.5), row=i, col=1)

    fig.update_layout(
        template="plotly_dark", height=200 + 250 * n_rows,
        xaxis_rangeslider_visible=False,
    )
    for r in range(1, n_rows + 1):
        fig.update_xaxes(type="category", row=r, col=1)

    return fig
```

---

## Stats Cards Pattern

```python
@callback(
    Output("stats-row", "children"),
    Input("load-btn", "n_clicks"),
    Input("symbol-input", "value"),
)
def update_stats(n_clicks, symbol):
    quote = client.quotes(symbol=symbol, exchange="NSE")
    d = quote.get("data", {})

    cards = [
        ("LTP", f"{d.get('ltp', 0):,.2f}"),
        ("Change", f"{d.get('ltp', 0) - d.get('prev_close', 0):+,.2f}"),
        ("Change %", f"{((d.get('ltp', 0) / d.get('prev_close', 1)) - 1) * 100:+.2f}%"),
        ("Volume", f"{d.get('volume', 0):,}"),
        ("Day Range", f"{d.get('low', 0):,.2f} - {d.get('high', 0):,.2f}"),
    ]

    return [
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P(label, className="text-muted mb-0", style={"fontSize": "0.8rem"}),
            html.H5(value, className="mb-0"),
        ])), width=2)
        for label, value in cards
    ]
```

---

## Auto-Refresh with WebSocket Alternative

For real-time dashboards, either use `dcc.Interval` for polling or integrate WebSocket data:

```python
# Polling approach (simpler)
dcc.Interval(id="refresh-interval", interval=5_000)  # Every 5 seconds

@callback(Output("ltp-display", "children"), Input("refresh-interval", "n_intervals"))
def refresh_ltp(n):
    quote = client.quotes(symbol="SBIN", exchange="NSE")
    return f"LTP: {quote['data']['ltp']}"
```

---

## Running the Dashboard

```bash
python dashboards/my_dashboard/app.py
# Opens at http://127.0.0.1:8050
```

---

## Streamlit Alternative

For Streamlit-based dashboards instead of Dash, see [streamlit-patterns.md](streamlit-patterns.md). Streamlit offers simpler setup (no callbacks), built-in `st.metric()`, `st.dataframe()`, and `st.download_button()`, at the cost of less fine-grained layout control.
