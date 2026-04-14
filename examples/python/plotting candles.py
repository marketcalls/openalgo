"""
RELIANCE 5-Minute Candlestick Chart - Last 20 Days
With Bollinger Bands (Top) and RSI (Bottom)
Author : OpenAlgo GPT
Description: Plots RELIANCE 5m candlestick chart using Plotly with category x-axis
"""

print("🔁 OpenAlgo Python Bot is running.")

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from openalgo import api, ta
from plotly.subplots import make_subplots

# ───────────────────────── CONFIG ─────────────────────────
API_KEY = "3f75e26648a543a886c9b38332a6942e30e0710bbf0488cf432ef27745de8ae7"
API_HOST = "http://127.0.0.1:5000"

SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
INTERVAL = "5m"

# Date range controls (last 20 days)
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - pd.Timedelta(days=20)).strftime("%Y-%m-%d")

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


# ───────────────────── INDICATOR SETTINGS ─────────────────────
RSI_PERIOD = 20
BB_PERIOD = 15
BB_STD_DEV = 2.0


# ───────────────────── CALCULATE INDICATORS ─────────────────────
def calculate_indicators(df: pd.DataFrame):
    """Calculate RSI and Bollinger Bands using OpenAlgo ta library"""

    # RSI (20)
    df["rsi"] = ta.rsi(df["close"], period=RSI_PERIOD)

    # Bollinger Bands (15, 2)
    bb_upper, bb_middle, bb_lower = ta.bbands(df["close"], period=BB_PERIOD, std_dev=BB_STD_DEV)
    df["bb_upper"] = bb_upper
    df["bb_middle"] = bb_middle
    df["bb_lower"] = bb_lower

    print(f"Calculated RSI({RSI_PERIOD}) and Bollinger Bands({BB_PERIOD}, {BB_STD_DEV})")

    return df


# ───────────────────── PLOT CANDLESTICK CHART ─────────────────────
def plot_candlestick(df: pd.DataFrame):
    """Create interactive candlestick chart with Bollinger Bands and RSI using Plotly"""

    # Create x-axis as category strings (Plotly requirement from docs)
    x_category = df.index.strftime("%d-%b<br>%H:%M").tolist()

    # Calculate tick positions (show ~15 labels for readability)
    total_candles = len(x_category)
    tick_step = max(1, total_candles // 15)
    tick_vals = [x_category[i] for i in range(0, total_candles, tick_step)]

    # Create subplots: Candlestick with BB (top 75%), RSI (bottom 25%)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
        subplot_titles=[
            f"{SYMBOL} ({EXCHANGE}) - {INTERVAL} with Bollinger Bands ({BB_PERIOD}, {BB_STD_DEV})",
            f"RSI ({RSI_PERIOD})",
        ],
    )

    # ───────── ROW 1: Candlestick + Bollinger Bands ─────────

    # Add candlestick trace
    fig.add_trace(
        go.Candlestick(
            x=x_category,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=SYMBOL,
            increasing_line_color="#26a69a",  # Green for bullish
            decreasing_line_color="#ef5350",  # Red for bearish
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # Bollinger Bands - Upper Band
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=df["bb_upper"],
            name="BB Upper",
            line=dict(color="rgba(173, 216, 230, 0.8)", width=1),
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # Bollinger Bands - Middle Band (SMA)
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=df["bb_middle"],
            name="BB Middle",
            line=dict(color="rgba(255, 165, 0, 0.8)", width=1, dash="dash"),
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # Bollinger Bands - Lower Band
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=df["bb_lower"],
            name="BB Lower",
            line=dict(color="rgba(173, 216, 230, 0.8)", width=1),
            fill="tonexty",  # Fill area between upper and lower bands
            fillcolor="rgba(173, 216, 230, 0.1)",
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # ───────── ROW 2: RSI ─────────

    # RSI Line
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=df["rsi"],
            name=f"RSI ({RSI_PERIOD})",
            line=dict(color="#ab47bc", width=1.5),
            showlegend=True,
        ),
        row=2,
        col=1,
    )

    # RSI Overbought Line (70)
    fig.add_hline(
        y=70,
        line_dash="dash",
        line_color="red",
        line_width=1,
        annotation_text="Overbought (70)",
        annotation_position="right",
        row=2,
        col=1,
    )

    # RSI Oversold Line (30)
    fig.add_hline(
        y=30,
        line_dash="dash",
        line_color="green",
        line_width=1,
        annotation_text="Oversold (30)",
        annotation_position="right",
        row=2,
        col=1,
    )

    # RSI Middle Line (50)
    fig.add_hline(y=50, line_dash="dot", line_color="gray", line_width=1, row=2, col=1)

    # ───────── LAYOUT ─────────
    fig.update_layout(
        title=dict(
            text=f"{SYMBOL} Technical Analysis<br><sup>{START_DATE} to {END_DATE}</sup>",
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

    fig.update_yaxes(
        title="RSI",
        showgrid=True,
        gridcolor="rgba(128, 128, 128, 0.2)",
        range=[0, 100],  # RSI range is 0-100
        row=2,
        col=1,
    )

    return fig


# ───────────────────── MAIN EXECUTION ─────────────────────
if __name__ == "__main__":
    try:
        # Fetch data
        df = fetch_historical_data()

        # Calculate indicators (RSI and Bollinger Bands)
        df = calculate_indicators(df)

        # Create and display chart
        fig = plot_candlestick(df)

        # Save as HTML file
        output_file = "reliance_candlestick_chart.html"
        fig.write_html(output_file)
        print(f"\nChart saved to: {output_file}")

        # Show the chart (opens in browser)
        fig.show()

    except Exception as e:
        print(f"Error: {e}")
        raise
