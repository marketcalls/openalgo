"""
Multi-Timeframe Dashboard — Same symbol across 4 timeframes
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
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
from dotenv import find_dotenv, load_dotenv
from openalgo import api, ta

load_dotenv(find_dotenv(), override=False)

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

TIMEFRAMES = {
    "5m": {"interval": "5m", "days": 7, "fmt": "%H:%M"},
    "15m": {"interval": "15m", "days": 30, "fmt": "%m-%d %H:%M"},
    "1h": {"interval": "1h", "days": 90, "fmt": "%m-%d %H:%M"},
    "D": {"interval": "D", "days": 365, "fmt": "%Y-%m-%d"},
}


def fetch_tf_data(symbol, exchange, interval, days):
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
        dbc.Col(html.H3("Multi-Timeframe Analysis"), width=6),
        dbc.Col([
            dbc.InputGroup([
                dbc.Input(id="symbol-input", value="SBIN", placeholder="Symbol"),
                dbc.Select(id="exchange-select", value="NSE",
                           options=[{"label": e, "value": e}
                                    for e in ["NSE", "BSE", "NFO", "NSE_INDEX"]]),
                dbc.Button("Load", id="load-btn", color="primary"),
            ]),
        ], width=6),
    ], className="mb-3 mt-3"),

    dbc.Row(id="confluence-row", className="mb-3"),
    dbc.Row([dbc.Col(dcc.Graph(id="mtf-chart"), width=12)]),
], fluid=True)


@callback(
    Output("mtf-chart", "figure"),
    Output("confluence-row", "children"),
    Input("load-btn", "n_clicks"),
    State("symbol-input", "value"),
    State("exchange-select", "value"),
    prevent_initial_call=False,
)
def update_mtf(n_clicks, symbol, exchange):
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[f"{symbol} — {tf}" for tf in TIMEFRAMES],
        vertical_spacing=0.08, horizontal_spacing=0.05,
    )

    trends = {}
    for idx, (tf_name, tf_cfg) in enumerate(TIMEFRAMES.items()):
        row = idx // 2 + 1
        col = idx % 2 + 1

        try:
            df = fetch_tf_data(symbol, exchange, tf_cfg["interval"], tf_cfg["days"])
        except Exception:
            continue

        close = df["close"]
        x = df.index.strftime(tf_cfg["fmt"])

        fig.add_trace(go.Candlestick(
            x=x, open=df["open"], high=df["high"], low=df["low"], close=close,
            name=tf_name, showlegend=False,
        ), row=row, col=col)

        ema_20 = ta.ema(close, 20)
        ema_50 = ta.ema(close, min(50, len(close) - 1)) if len(close) > 50 else ema_20

        fig.add_trace(go.Scatter(x=x, y=ema_20, mode="lines",
                                 name=f"EMA20 {tf_name}", line=dict(color="cyan", width=1),
                                 showlegend=False), row=row, col=col)
        fig.add_trace(go.Scatter(x=x, y=ema_50, mode="lines",
                                 name=f"EMA50 {tf_name}", line=dict(color="orange", width=1),
                                 showlegend=False), row=row, col=col)

        fig.update_xaxes(type="category", row=row, col=col)
        fig.update_xaxes(rangeslider_visible=False, row=row, col=col)
        fig.update_yaxes(side="right", row=row, col=col)

        # Determine trend
        if len(close) > 20:
            rsi_val = ta.rsi(close, 14).iloc[-1] if len(close) > 14 else 50
            ema_trend = "bullish" if ema_20.iloc[-1] > ema_50.iloc[-1] else "bearish"
            trends[tf_name] = {"trend": ema_trend, "rsi": rsi_val}

    fig.update_layout(
        template="plotly_dark", height=800,
        title=f"{symbol} Multi-Timeframe Analysis",
        showlegend=False,
    )

    # Confluence cards
    bull_count = sum(1 for v in trends.values() if v["trend"] == "bullish")
    total = len(trends)

    if bull_count == total and total > 0:
        confluence = "STRONG BULLISH — All timeframes aligned"
        color = "success"
    elif bull_count == 0 and total > 0:
        confluence = "STRONG BEARISH — All timeframes aligned"
        color = "danger"
    else:
        confluence = f"MIXED — {bull_count}/{total} bullish"
        color = "warning"

    cards = [dbc.Col(dbc.Alert(confluence, color=color), width=4)]
    for tf, data in trends.items():
        c = "success" if data["trend"] == "bullish" else "danger"
        cards.append(dbc.Col(dbc.Card(dbc.CardBody([
            html.P(tf, className="text-muted mb-0"),
            html.H6(f"{data['trend'].upper()} | RSI: {data['rsi']:.1f}"),
        ]), color=c, outline=True), width=2))

    return fig, cards


if __name__ == "__main__":
    app.run(debug=True, port=8050)
