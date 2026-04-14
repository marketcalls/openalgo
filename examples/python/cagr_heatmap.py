# ---------------------------------------------------
# Python Code to Compute Rolling CAGR Heatmap for NIFTY 50
# Recommended to use Daily Historical Data more than 5 Years
# Minor variations in Rolling Returns might occur due to data source differences
# Coded by Rajandran R - Creator of OpenAlgo (https://openalgo.in)
# Author - www.marketcalls.in
# ---------------------------------------------------
# NOTE: This code requires OpenAlgo to be running locally or on a server.
# Get your API key from your self-hosted OpenAlgo platform.
# OpenAlgo GitHub: https://github.com/marketcalls/openalgo
# ---------------------------------------------------

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
from openalgo import api

# ---------------------------------------------------
# Initialize OpenAlgo Client
# ---------------------------------------------------
client = api(api_key="your_api_key_here", host="http://127.0.0.1:5000")

print("🔁 OpenAlgo Python Bot is running.")

# ---------------------------------------------------
# NIFTY 50 SYMBOLS
# ---------------------------------------------------
symbols = [
    "INDIGO",
    "TRENT",
    "HINDUNILVR",
    "HCLTECH",
    "WIPRO",
    "INFY",
    "TATACONSUM",
    "TATASTEEL",
    "ITC",
    "ASIANPAINT",
    "SBILIFE",
    "LT",
    "SHRIRAMFIN",
    "BEL",
    "SBIN",
    "COALINDIA",
    "KOTAKBANK",
    "TCS",
    "SUNPHARMA",
    "MAXHEALTH",
    "NESTLEIND",
    "RELIANCE",
    "ETERNAL",
    "APOLLOHOSP",
    "ICICIBANK",
    "GRASIM",
    "ULTRACEMCO",
    "ADANIENT",
    "AXISBANK",
    "DRREDDY",
    "TECHM",
    "TMPV",
    "JIOFIN",
    "NTPC",
    "BAJFINANCE",
    "BHARTIARTL",
    "POWERGRID",
    "HINDALCO",
    "HDFCBANK",
    "TITAN",
    "HDFCLIFE",
    "MARUTI",
    "BAJAJFINSV",
    "ADANIPORTS",
    "CIPLA",
    "JSWSTEEL",
    "BAJAJ-AUTO",
    "ONGC",
    "EICHERMOT",
    "M&M",
]

TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------
# CAGR Calculation (matching TradingView logic)
# ---------------------------------------------------
def calc_cagr(start_price, end_price, years):
    if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0 or end_price <= 0:
        return np.nan
    return ((end_price / start_price) ** (1 / years) - 1) * 100


def get_price_by_trading_days(df, bars_back):
    """Get price exactly N trading bars back (like TradingView)"""
    if len(df) <= bars_back:
        return np.nan
    return df["close"].iloc[-(bars_back + 1)]


# ---------------------------------------------------
# Fetch Historical Data & Calculate CAGRs
# ---------------------------------------------------
results = []

for symbol in symbols:
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 6)  # Extra buffer

        df = client.history(
            symbol=symbol,
            exchange="NSE",
            interval="D",
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
        )

        if not isinstance(df, pd.DataFrame) or df.empty:
            print(f"{symbol}: No data received")
            results.append([symbol, np.nan, np.nan, np.nan])
            continue

        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        price_now = df["close"].iloc[-1]
        total_bars = len(df)

        if total_bars < TRADING_DAYS_PER_YEAR:
            print(f"{symbol}: Insufficient data ({total_bars} bars)")
            results.append([symbol, np.nan, np.nan, np.nan])
            continue

        # Get prices using trading days (like TradingView)
        bars_1y = TRADING_DAYS_PER_YEAR
        bars_3y = TRADING_DAYS_PER_YEAR * 3
        bars_5y = TRADING_DAYS_PER_YEAR * 5

        price_1y = get_price_by_trading_days(df, bars_1y)
        price_3y = get_price_by_trading_days(df, bars_3y)
        price_5y = get_price_by_trading_days(df, bars_5y)

        # Calculate returns
        abs_1y = ((price_now / price_1y) - 1) * 100 if not pd.isna(price_1y) else np.nan
        cagr_3y = calc_cagr(price_3y, price_now, 3)
        cagr_5y = calc_cagr(price_5y, price_now, 5)

        # Display status
        abs_1y_str = f"{abs_1y:7.2f}%" if not pd.isna(abs_1y) else "N/A"
        cagr_3y_str = f"{cagr_3y:7.2f}%" if not pd.isna(cagr_3y) else "N/A"
        cagr_5y_str = f"{cagr_5y:7.2f}%" if not pd.isna(cagr_5y) else "N/A"
        print(
            f"{symbol:12s} | 1Y: {abs_1y_str:>8s} | 3Y: {cagr_3y_str:>8s} | 5Y: {cagr_5y_str:>8s}"
        )

        results.append([symbol, abs_1y, cagr_3y, cagr_5y])

    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        results.append([symbol, np.nan, np.nan, np.nan])

# ---------------------------------------------------
# Create DataFrame
# ---------------------------------------------------
df_cagr = pd.DataFrame(results, columns=["Symbol", "1Y", "3Y", "5Y"])


# ---------------------------------------------------
# Function to Create Heatmap
# ---------------------------------------------------
def create_heatmap(df, period, label):
    df_period = df[["Symbol", period]].copy()

    # Sort by value, putting NaN at the bottom
    df_period = df_period.sort_values(period, ascending=False, na_position="last").reset_index(
        drop=True
    )

    if df_period.empty:
        print(f"⚠️ No data for {label}")
        return

    cols = 10
    df_period["row"] = df_period.index // cols
    df_period["col"] = df_period.index % cols

    # Create display text: "SYMBOL\nValue%" or "SYMBOL\nN/A"
    df_period["display_text"] = df_period.apply(
        lambda row: f"{row['Symbol']}<br>{row[period]:.2f}%"
        if pd.notna(row[period])
        else f"{row['Symbol']}<br>N/A",
        axis=1,
    )

    pivot_values = df_period.pivot(index="row", columns="col", values=period)
    pivot_labels = df_period.pivot(index="row", columns="col", values="display_text")

    fig = px.imshow(pivot_values, color_continuous_scale="RdYlGn", aspect="auto")

    fig.update_traces(
        text=pivot_labels.values, texttemplate="%{text}", hovertemplate="%{text}<extra></extra>"
    )

    fig.update_layout(
        title=f"NIFTY 50 {label} Heatmap (%)",
        xaxis=dict(showticklabels=False, title=""),
        yaxis=dict(showticklabels=False, autorange="reversed", title=""),
        template="plotly_dark",
        height=600,
        width=1200,
    )

    filename = f"nifty50_{period.lower()}_heatmap.png"
    fig.write_image(filename, width=1200, height=600, scale=2)
    print(f"✅ {label} Heatmap saved as {filename}")


# ---------------------------------------------------
# Generate Heatmaps
# ---------------------------------------------------
create_heatmap(df_cagr, "1Y", "1-Year Absolute Return")
create_heatmap(df_cagr, "3Y", "3-Year CAGR")
create_heatmap(df_cagr, "5Y", "5-Year CAGR")

print("\n✅ All heatmaps generated successfully!")
