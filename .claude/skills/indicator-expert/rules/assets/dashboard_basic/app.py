"""
Basic Indicator Dashboard — Single symbol with configurable indicators
Run: python app.py
Open: http://127.0.0.1:8050
"""
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html, Input, Output, callback, State
import dash_bootstrap_components as dbc
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)


def fetch_data(symbol, exchange, interval, days=365):
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    df = client.history(
        symbol=symbol, exchange=exchange, interval=interval,
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
    return df


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("OpenAlgo Indicator Dashboard"), width=8),
    ], className="mb-3 mt-3"),

    dbc.Row([
        dbc.Col([
            dbc.Label("Symbol"),
            dbc.Input(id="symbol-input", value="SBIN", type="text"),
        ], width=2),
        dbc.Col([
            dbc.Label("Exchange"),
            dbc.Select(id="exchange-select", value="NSE",
                       options=[{"label": e, "value": e}
                                for e in ["NSE", "BSE", "NFO", "NSE_INDEX", "MCX"]]),
        ], width=2),
        dbc.Col([
            dbc.Label("Interval"),
            dbc.Select(id="interval-select", value="D",
                       options=[{"label": i, "value": i}
                                for i in ["1m", "5m", "15m", "30m", "1h", "D"]]),
        ], width=2),
        dbc.Col([
            dbc.Label("Overlays"),
            dbc.Checklist(
                id="overlay-select",
                options=[
                    {"label": " EMA(20)", "value": "ema20"},
                    {"label": " EMA(50)", "value": "ema50"},
                    {"label": " Bollinger", "value": "bbands"},
                    {"label": " Supertrend", "value": "supertrend"},
                ],
                value=["ema20"],
                inline=True,
            ),
        ], width=3),
        dbc.Col([
            dbc.Button("Load", id="load-btn", color="primary", className="mt-4"),
        ], width=1),
    ], className="mb-3"),

    dbc.Row([
        dbc.Col([
            dbc.Label("Subplots"),
            dbc.Checklist(
                id="subplot-select",
                options=[
                    {"label": " RSI", "value": "rsi"},
                    {"label": " MACD", "value": "macd"},
                    {"label": " Volume", "value": "volume"},
                    {"label": " Stochastic", "value": "stochastic"},
                    {"label": " ADX", "value": "adx"},
                    {"label": " OBV", "value": "obv"},
                ],
                value=["rsi", "volume"],
                inline=True,
            ),
        ], width=12),
    ], className="mb-3"),

    dbc.Row(id="stats-row", className="mb-3"),
    dbc.Row([dbc.Col(dcc.Graph(id="main-chart"), width=12)]),
    dcc.Interval(id="refresh-interval", interval=60_000, n_intervals=0),
], fluid=True)


@callback(
    Output("main-chart", "figure"),
    Output("stats-row", "children"),
    Input("load-btn", "n_clicks"),
    State("symbol-input", "value"),
    State("exchange-select", "value"),
    State("interval-select", "value"),
    State("overlay-select", "value"),
    State("subplot-select", "value"),
    prevent_initial_call=False,
)
def update_chart(n_clicks, symbol, exchange, interval, overlays, subplots):
    days_map = {"1m": 7, "5m": 30, "15m": 90, "30m": 90, "1h": 180, "D": 365}
    days = days_map.get(interval, 365)

    df = fetch_data(symbol, exchange, interval, days)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    if not overlays:
        overlays = []
    if not subplots:
        subplots = []

    n_rows = 1 + len(subplots)
    heights = [0.5] + [0.5 / max(len(subplots), 1)] * len(subplots) if subplots else [1.0]
    titles = [f"{symbol} ({exchange})"] + [s.upper() for s in subplots]

    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=heights, vertical_spacing=0.03,
        subplot_titles=titles,
    )

    fmt = "%Y-%m-%d" if interval == "D" else "%Y-%m-%d %H:%M"
    x_labels = df.index.strftime(fmt)

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=x_labels, open=df["open"], high=high, low=low, close=close,
        name="Price", showlegend=False,
    ), row=1, col=1)

    # Overlays
    if "ema20" in overlays:
        fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 20),
                                 name="EMA(20)", line=dict(color="cyan", width=1.5)),
                      row=1, col=1)
    if "ema50" in overlays:
        fig.add_trace(go.Scatter(x=x_labels, y=ta.ema(close, 50),
                                 name="EMA(50)", line=dict(color="orange", width=1.5)),
                      row=1, col=1)
    if "bbands" in overlays:
        upper, mid, lower = ta.bbands(close, 20, 2.0)
        fig.add_trace(go.Scatter(x=x_labels, y=upper, name="BB Upper",
                                 line=dict(color="gray", dash="dash", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=lower, name="BB Lower",
                                 line=dict(color="gray", dash="dash", width=1),
                                 fill="tonexty", fillcolor="rgba(128,128,128,0.08)"),
                      row=1, col=1)
    if "supertrend" in overlays:
        st, direction = ta.supertrend(high, low, close, 10, 3.0)
        st_up = pd.Series(st, index=df.index).where(pd.Series(direction, index=df.index) == -1)
        st_down = pd.Series(st, index=df.index).where(pd.Series(direction, index=df.index) == 1)
        fig.add_trace(go.Scatter(x=x_labels, y=st_up, name="ST Up",
                                 line=dict(color="lime", width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=x_labels, y=st_down, name="ST Down",
                                 line=dict(color="red", width=2)), row=1, col=1)

    # Subplots
    for i, sp in enumerate(subplots, start=2):
        if sp == "rsi":
            fig.add_trace(go.Scatter(x=x_labels, y=ta.rsi(close, 14),
                                     name="RSI(14)", line=dict(color="yellow", width=1.5)),
                          row=i, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=i, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=i, col=1)
            fig.update_yaxes(range=[0, 100], row=i, col=1)
        elif sp == "macd":
            m, s, h = ta.macd(close, 12, 26, 9)
            fig.add_trace(go.Scatter(x=x_labels, y=m, name="MACD",
                                     line=dict(color="cyan", width=1)), row=i, col=1)
            fig.add_trace(go.Scatter(x=x_labels, y=s, name="Signal",
                                     line=dict(color="orange", width=1)), row=i, col=1)
            colors = ["green" if v >= 0 else "red" for v in h]
            fig.add_trace(go.Bar(x=x_labels, y=h, name="Hist",
                                 marker_color=colors, opacity=0.6), row=i, col=1)
        elif sp == "volume":
            vc = ["green" if c >= o else "red" for c, o in zip(close, df["open"])]
            fig.add_trace(go.Bar(x=x_labels, y=df["volume"], name="Volume",
                                 marker_color=vc, opacity=0.5), row=i, col=1)
        elif sp == "stochastic":
            k, d = ta.stochastic(high, low, close, k_period=14, smooth_k=3, d_period=3)
            fig.add_trace(go.Scatter(x=x_labels, y=k, name="%K",
                                     line=dict(color="cyan", width=1)), row=i, col=1)
            fig.add_trace(go.Scatter(x=x_labels, y=d, name="%D",
                                     line=dict(color="orange", width=1)), row=i, col=1)
            fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.5, row=i, col=1)
            fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.5, row=i, col=1)
        elif sp == "adx":
            dp, dm, adx = ta.adx(high, low, close, 14)
            fig.add_trace(go.Scatter(x=x_labels, y=dp, name="+DI",
                                     line=dict(color="lime", width=1)), row=i, col=1)
            fig.add_trace(go.Scatter(x=x_labels, y=dm, name="-DI",
                                     line=dict(color="red", width=1)), row=i, col=1)
            fig.add_trace(go.Scatter(x=x_labels, y=adx, name="ADX",
                                     line=dict(color="yellow", width=1.5)), row=i, col=1)
            fig.add_hline(y=25, line_dash="dash", line_color="gray", opacity=0.5, row=i, col=1)
        elif sp == "obv":
            fig.add_trace(go.Scatter(x=x_labels, y=ta.obv(close, df["volume"]),
                                     name="OBV", line=dict(color="cyan", width=1.5)),
                          row=i, col=1)

    fig.update_layout(
        template="plotly_dark", height=250 + 220 * n_rows,
        xaxis_rangeslider_visible=False,
    )
    for r in range(1, n_rows + 1):
        fig.update_xaxes(type="category", row=r, col=1)
        fig.update_yaxes(side="right", row=r, col=1)

    # Stats cards
    try:
        quote = client.quotes(symbol=symbol, exchange=exchange)
        d = quote.get("data", {})
        ltp = d.get("ltp", close.iloc[-1])
        prev = d.get("prev_close", close.iloc[-2] if len(close) > 1 else ltp)
    except Exception:
        ltp = close.iloc[-1]
        prev = close.iloc[-2] if len(close) > 1 else ltp

    change = ltp - prev
    change_pct = (change / prev * 100) if prev != 0 else 0
    rsi_val = ta.rsi(close, 14).iloc[-1] if len(close) > 14 else 0

    cards = [
        ("LTP", f"{ltp:,.2f}", "primary"),
        ("Change", f"{change:+,.2f} ({change_pct:+.2f}%)", "success" if change >= 0 else "danger"),
        ("RSI(14)", f"{rsi_val:.1f}", "warning" if rsi_val > 70 or rsi_val < 30 else "info"),
        ("Volume", f"{df['volume'].iloc[-1]:,.0f}", "secondary"),
        ("EMA(20)", f"{ta.ema(close, 20).iloc[-1]:,.2f}", "info"),
    ]

    stat_cards = [
        dbc.Col(dbc.Card(dbc.CardBody([
            html.P(label, className="text-muted mb-0", style={"fontSize": "0.75rem"}),
            html.H5(value, className="mb-0"),
        ]), color=color, outline=True), width=2)
        for label, value, color in cards
    ]

    return fig, stat_cards


if __name__ == "__main__":
    app.run(debug=True, port=8050)
