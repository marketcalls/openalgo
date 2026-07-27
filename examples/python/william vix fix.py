"""
RELIANCE 5-Minute Chart with Williams Vix Fix (CM_Williams_Vix_Fix)
Author : OpenAlgo GPT
Description: Plots RELIANCE candlestick with Williams Vix Fix indicator
             Converted from Pine Script v3 to Python using OpenAlgo ta library
"""

print("🔁 OpenAlgo Python Bot is running.")

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from openalgo import api, ta
from plotly.subplots import make_subplots

# ───────────────────────── CONFIG ─────────────────────────
API_KEY = "3f75e26648a543a886c9b38332a6942e30e0710bbf0488cf432ef27745de8ae7"
API_HOST = "http://127.0.0.1:5000"

SYMBOL = "NIFTY"
EXCHANGE = "NSE_INDEX"
INTERVAL = "D"

# Date range controls (last 20 days)
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - pd.Timedelta(days=200)).strftime("%Y-%m-%d")

# ───────────────────────── WILLIAMS VIX FIX PARAMETERS ─────────────────────────
# Pine Script original parameters
WVF_LOOKBACK = 22  # pd = LookBack Period Standard Deviation High
BB_LENGTH = 20  # bbl = Bollinger Band Length
BB_MULT = 2.0  # mult = Bollinger Band Standard Deviation Up
PERCENTILE_LOOKBACK = 50  # lb = Look Back Period Percentile High
PERCENTILE_HIGH = 0.85  # ph = Highest Percentile (0.85 = 85%)
PERCENTILE_LOW = 1.01  # pl = Lowest Percentile

# Display options
SHOW_HIGH_RANGE = True  # hp = Show High Range based on Percentile
SHOW_STD_DEV = True  # sd = Show Standard Deviation Line

# ─────────────────────── INIT CLIENT ──────────────────────
client = api(api_key=API_KEY, host=API_HOST)


# ───────────────────── FETCH HISTORICAL DATA ─────────────────────
def fetch_historical_data():
    """Fetch 5m historical data for RELIANCE"""
    print(f"Fetching {SYMBOL} {INTERVAL} data from {START_DATE} to {END_DATE}...")

    response = client.history(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=INTERVAL,
        start_date=START_DATE,
        end_date=END_DATE,
    )

    # Print the raw response
    print(f"History Response: {response}")

    # OpenAlgo history() returns DataFrame directly (not a dict)
    if isinstance(response, pd.DataFrame):
        df = response.copy()
    else:
        # Fallback if it returns dict
        df = pd.DataFrame(response.get("data", response))

    # Check if DataFrame is empty
    if df.empty:
        raise ValueError("No data received from API")

    # Handle index - if timestamp is already the index
    if df.index.name == "timestamp" or "timestamp" not in df.columns:
        df.index = pd.to_datetime(df.index)
    else:
        df["datetime"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("datetime")

    df = df.sort_index()

    # Standardize column names to lowercase
    df.columns = df.columns.str.lower()

    # Ensure we have OHLC columns
    required_cols = ["open", "high", "low", "close"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    print(f"Fetched {len(df)} candles")
    print(f"Date range: {df.index.min()} to {df.index.max()}")

    return df


# ───────────────────── WILLIAMS VIX FIX CALCULATION ─────────────────────
def calculate_williams_vix_fix(df: pd.DataFrame):
    """
    Calculate Williams Vix Fix indicator

    Formula from Pine Script:
    wvf = ((highest(close, pd) - low) / highest(close, pd)) * 100

    Then apply Bollinger Bands and Percentile Range to determine signals
    """

    close = df["close"]
    low = df["low"]

    # Calculate highest close over lookback period
    highest_close = ta.highest(close, WVF_LOOKBACK)

    # Williams Vix Fix formula
    # wvf = ((highest(close, pd) - low) / highest(close, pd)) * 100
    wvf = ((highest_close - low) / highest_close) * 100
    df["wvf"] = wvf

    # Bollinger Bands on WVF
    # midLine = sma(wvf, bbl)
    # sDev = mult * stdev(wvf, bbl)
    mid_line = ta.sma(wvf, BB_LENGTH)
    std_dev = ta.stdev(wvf, BB_LENGTH)
    s_dev = BB_MULT * std_dev

    df["wvf_midline"] = mid_line
    df["wvf_upper"] = mid_line + s_dev
    df["wvf_lower"] = mid_line - s_dev

    # Percentile Range
    # rangeHigh = (highest(wvf, lb)) * ph
    # rangeLow = (lowest(wvf, lb)) * pl
    range_high = ta.highest(wvf, PERCENTILE_LOOKBACK) * PERCENTILE_HIGH
    range_low = ta.lowest(wvf, PERCENTILE_LOOKBACK) * PERCENTILE_LOW

    df["range_high"] = range_high
    df["range_low"] = range_low

    # Color condition: Green (lime) when WVF >= upperBand OR WVF >= rangeHigh
    # col = wvf >= upperBand or wvf >= rangeHigh ? lime : gray
    df["wvf_signal"] = (wvf >= df["wvf_upper"]) | (wvf >= range_high)

    print(f"Calculated Williams Vix Fix (Lookback: {WVF_LOOKBACK}, BB: {BB_LENGTH}, {BB_MULT})")
    print(f"WVF Range: {wvf.min():.2f} to {wvf.max():.2f}")

    return df


# ───────────────────── PLOT CHART ─────────────────────
def plot_chart(df: pd.DataFrame):
    """Create interactive chart with Candlestick and Williams Vix Fix"""

    # Create x-axis as category strings (Plotly requirement)
    x_category = df.index.strftime("%d-%b<br>%H:%M").tolist()

    # Calculate tick positions (show ~15 labels for readability)
    total_candles = len(x_category)
    tick_step = max(1, total_candles // 15)
    tick_vals = [x_category[i] for i in range(0, total_candles, tick_step)]

    # Create subplots: Candlestick (top 70%), Williams Vix Fix (bottom 30%)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.70, 0.30],
        subplot_titles=[
            f"{SYMBOL} ({EXCHANGE}) - {INTERVAL}",
            f"Williams Vix Fix (pd={WVF_LOOKBACK}, bbl={BB_LENGTH}, mult={BB_MULT})",
        ],
    )

    # ───────── ROW 1: Candlestick ─────────
    fig.add_trace(
        go.Candlestick(
            x=x_category,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=SYMBOL,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # ───────── ROW 2: Williams Vix Fix ─────────

    # Create color array based on signal condition
    colors = ["lime" if sig else "gray" for sig in df["wvf_signal"]]

    # WVF Histogram
    fig.add_trace(
        go.Bar(
            x=x_category, y=df["wvf"], name="Williams Vix Fix", marker_color=colors, showlegend=True
        ),
        row=2,
        col=1,
    )

    # Upper Band (Standard Deviation Line)
    if SHOW_STD_DEV:
        fig.add_trace(
            go.Scatter(
                x=x_category,
                y=df["wvf_upper"],
                name="Upper Band",
                line=dict(color="aqua", width=2),
                showlegend=True,
            ),
            row=2,
            col=1,
        )

    # Range High Percentile
    if SHOW_HIGH_RANGE:
        fig.add_trace(
            go.Scatter(
                x=x_category,
                y=df["range_high"],
                name=f"Range High ({PERCENTILE_HIGH * 100:.0f}%)",
                line=dict(color="orange", width=2, dash="dash"),
                showlegend=True,
            ),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=x_category,
                y=df["range_low"],
                name=f"Range Low ({(PERCENTILE_LOW - 1) * 100:.0f}%)",
                line=dict(color="orange", width=2, dash="dash"),
                showlegend=True,
            ),
            row=2,
            col=1,
        )

    # ───────── LAYOUT ─────────
    fig.update_layout(
        title=dict(
            text=f"{SYMBOL} with CM Williams Vix Fix<br><sup>{START_DATE} to {END_DATE}</sup>",
            x=0.5,
            font=dict(size=18),
        ),
        template="plotly_dark",
        height=900,
        width=1400,
        hovermode="x unified",
        margin=dict(l=60, r=100, t=80, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis2=dict(rangeslider=dict(visible=False)),
    )

    # Update x-axes
    fig.update_xaxes(
        type="category",
        tickmode="array",
        tickvals=tick_vals,
        tickangle=-45,
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        rangeslider=dict(visible=False),
        row=1,
        col=1,
    )

    fig.update_xaxes(
        type="category",
        tickmode="array",
        tickvals=tick_vals,
        tickangle=-45,
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        title="Date / Time",
        row=2,
        col=1,
    )

    # Update y-axes
    fig.update_yaxes(
        title="Price (₹)",
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        tickformat=",.2f",
        row=1,
        col=1,
    )

    fig.update_yaxes(title="WVF", showgrid=True, gridcolor="rgba(128, 128, 128, 0.2)", row=2, col=1)

    return fig


# ───────────────────── MAIN EXECUTION ─────────────────────
if __name__ == "__main__":
    try:
        # Fetch data
        df = fetch_historical_data()

        # Calculate Williams Vix Fix
        df = calculate_williams_vix_fix(df)

        # Create and display chart
        fig = plot_chart(df)

        # Save as HTML file
        output_file = "reliance_williams_vix_fix.html"
        fig.write_html(output_file)
        print(f"\nChart saved to: {output_file}")

        # Show the chart (opens in browser)
        fig.show()

    except Exception as e:
        print(f"Error: {e}")
        raise
