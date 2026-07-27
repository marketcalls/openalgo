"""
RELIANCE 5-Minute EMA Crossover Backtest using VectorBT
Author : OpenAlgo GPT
Description: Backtests 10/20 EMA crossover strategy on RELIANCE 5m data
             Data fetched from OpenAlgo API, backtested with VectorBT
"""

print("🔁 OpenAlgo Python Bot is running.")

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import vectorbt as vbt
from openalgo import api, ta
from plotly.subplots import make_subplots

# ───────────────────────── CONFIG ─────────────────────────
API_KEY = "dfae8e3a1ce08f60754b0d3597553d7c14957542104b431e4b881c089864a35e"
API_HOST = "http://127.0.0.1:5000"

SYMBOL = "SBIN"
EXCHANGE = "NSE"
INTERVAL = "15m"

# Date range controls (last 1 year)
END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")

# EMA Parameters
FAST_EMA = 10
SLOW_EMA = 20

# Backtest Parameters
INITIAL_CAPITAL = 100000  # Rs 1,00,000
POSITION_SIZE = 0.5  # 50% of equity
FEES = 0.0011  # 0.11% trading fees

# ─────────────────────── INIT CLIENT ──────────────────────
client = api(api_key=API_KEY, host=API_HOST)


# ───────────────────── FETCH HISTORICAL DATA ─────────────────────
def fetch_historical_data():
    """Fetch 5m historical data for RELIANCE (1 year)"""
    print(f"\nFetching {SYMBOL} {INTERVAL} data from {START_DATE} to {END_DATE}...")
    print("This may take a moment for 1 year of 5m data...")

    response = client.history(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=INTERVAL,
        start_date=START_DATE,
        end_date=END_DATE,
        source = "db"
    )

    # Print the raw response info
    print(f"History Response received: {type(response)}")

    # OpenAlgo history() returns DataFrame directly
    if isinstance(response, pd.DataFrame):
        df = response.copy()
    else:
        df = pd.DataFrame(response.get("data", response))

    if df.empty:
        raise ValueError("No data received from API")

    # Handle index
    if df.index.name == "timestamp" or "timestamp" not in df.columns:
        df.index = pd.to_datetime(df.index)
    else:
        df["datetime"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("datetime")

    df = df.sort_index()
    df.columns = df.columns.str.lower()

    # Ensure timezone-naive for VectorBT compatibility
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    print(f"✅ Fetched {len(df)} candles")
    print(f"📅 Date range: {df.index.min()} to {df.index.max()}")
    print(f"📊 Columns: {list(df.columns)}")

    return df


# ───────────────────── VECTORBT BACKTEST ─────────────────────
def run_backtest(df: pd.DataFrame):
    """Run VectorBT backtest with EMA crossover strategy"""

    print(f"\n{'=' * 60}")
    print("Running EMA Crossover Backtest")
    print(f"Fast EMA: {FAST_EMA} | Slow EMA: {SLOW_EMA}")
    print(f"Initial Capital: ₹{INITIAL_CAPITAL:,}")
    print(f"Position Size: {POSITION_SIZE * 100}% of equity")
    print(f"Fees: {FEES * 100}%")
    print(f"{'=' * 60}\n")

    close = df["close"]

    # Calculate EMAs using VectorBT's built-in MA indicator
    fast_ema = vbt.MA.run(close, FAST_EMA, short_name="fast", ewm=True)
    slow_ema = vbt.MA.run(close, SLOW_EMA, short_name="slow", ewm=True)

    # Generate crossover signals
    entries = fast_ema.ma_crossed_above(slow_ema)
    exits = fast_ema.ma_crossed_below(slow_ema)

    # Print signal counts
    print(f"📈 Total Entry Signals: {entries.sum()}")
    print(f"📉 Total Exit Signals: {exits.sum()}")

    # Create portfolio
    portfolio = vbt.Portfolio.from_signals(
        close,
        entries,
        exits,
        direction="longonly",
        size=POSITION_SIZE,
        size_type="percent",
        fees=FEES,
        init_cash=INITIAL_CAPITAL,
        freq="5min",
        min_size=1,
        size_granularity=1,
    )

    return portfolio, fast_ema, slow_ema, entries, exits


# ───────────────────── PRINT BACKTEST STATS ─────────────────────
def print_backtest_stats(portfolio):
    """Print detailed backtest statistics"""

    stats = portfolio.stats()

    print(f"\n{'=' * 60}")
    print("📊 BACKTEST STATISTICS")
    print(f"{'=' * 60}")
    print(stats)
    print(f"{'=' * 60}\n")

    return stats


# ───────────────────── GET TRADE DETAILS ─────────────────────
def get_trade_details(portfolio):
    """Get and display trade details"""

    trades = portfolio.trades.records_readable

    print(f"\n{'=' * 60}")
    print("📋 TRADE DETAILS")
    print(f"{'=' * 60}")
    print(f"Total Trades: {len(trades)}")
    print("\nFirst 10 Trades:")
    print(trades.head(10).to_string())
    print("\nLast 10 Trades:")
    print(trades.tail(10).to_string())
    print(f"{'=' * 60}\n")

    return trades


# ───────────────────── PLOT RESULTS ─────────────────────
def plot_results(df, portfolio, fast_ema, slow_ema, entries, exits):
    """Create interactive plots for backtest results"""

    # Create x-axis as category strings
    x_category = df.index.strftime("%d-%b-%y<br>%H:%M").tolist()

    # Calculate tick positions
    total_candles = len(x_category)
    tick_step = max(1, total_candles // 20)
    tick_vals = [x_category[i] for i in range(0, total_candles, tick_step)]

    # Get equity and drawdown data
    equity_data = portfolio.value()
    drawdown_data = portfolio.drawdown() * 100

    # Create subplots
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.5, 0.25, 0.25],
        subplot_titles=[
            f"{SYMBOL} Price with EMA({FAST_EMA}/{SLOW_EMA}) Crossover",
            "Equity Curve",
            "Drawdown %",
        ],
    )

    # ───────── ROW 1: Price with EMAs and Signals ─────────

    # Candlestick
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

    # Fast EMA
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=fast_ema.ma.values.flatten(),
            name=f"EMA {FAST_EMA}",
            line=dict(color="blue", width=1),
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # Slow EMA
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=slow_ema.ma.values.flatten(),
            name=f"EMA {SLOW_EMA}",
            line=dict(color="orange", width=1),
            showlegend=True,
        ),
        row=1,
        col=1,
    )

    # Entry signals (Buy) - Fixed indexing
    entry_mask = entries.values.flatten()
    entry_indices = np.where(entry_mask)[0]
    if len(entry_indices) > 0:
        entry_x = [x_category[i] for i in entry_indices if i < len(x_category)]
        entry_y = [df["low"].iloc[i] * 0.995 for i in entry_indices if i < len(df)]

        fig.add_trace(
            go.Scatter(
                x=entry_x,
                y=entry_y,
                mode="markers",
                name="Buy Signal",
                marker=dict(symbol="triangle-up", size=10, color="lime"),
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # Exit signals (Sell) - Fixed indexing
    exit_mask = exits.values.flatten()
    exit_indices = np.where(exit_mask)[0]
    if len(exit_indices) > 0:
        exit_x = [x_category[i] for i in exit_indices if i < len(x_category)]
        exit_y = [df["high"].iloc[i] * 1.005 for i in exit_indices if i < len(df)]

        fig.add_trace(
            go.Scatter(
                x=exit_x,
                y=exit_y,
                mode="markers",
                name="Sell Signal",
                marker=dict(symbol="triangle-down", size=10, color="red"),
                showlegend=True,
            ),
            row=1,
            col=1,
        )

    # ───────── ROW 2: Equity Curve ─────────
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=equity_data.values,
            name="Equity",
            line=dict(color="#00bcd4", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(0, 188, 212, 0.1)",
            showlegend=True,
        ),
        row=2,
        col=1,
    )

    # Initial capital line
    fig.add_hline(
        y=INITIAL_CAPITAL,
        line_dash="dash",
        line_color="gray",
        annotation_text=f"Initial: ₹{INITIAL_CAPITAL:,}",
        row=2,
        col=1,
    )

    # ───────── ROW 3: Drawdown ─────────
    fig.add_trace(
        go.Scatter(
            x=x_category,
            y=drawdown_data.values,
            name="Drawdown",
            line=dict(color="brown", width=1),
            fill="tozeroy",
            fillcolor="rgba(165, 42, 42, 0.3)",
            showlegend=True,
        ),
        row=3,
        col=1,
    )

    # ───────── LAYOUT ─────────
    fig.update_layout(
        title=dict(
            text=f"{SYMBOL} EMA({FAST_EMA}/{SLOW_EMA}) Crossover Backtest<br>"
            f"<sup>{START_DATE} to {END_DATE} | Initial: ₹{INITIAL_CAPITAL:,} | "
            f"Final: ₹{equity_data.iloc[-1]:,.2f}</sup>",
            x=0.5,
            font=dict(size=16),
        ),
        template="plotly_dark",
        height=1000,
        width=1400,
        hovermode="x unified",
        margin=dict(l=60, r=100, t=100, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Update x-axes
    for row in [1, 2, 3]:
        fig.update_xaxes(
            type="category",
            tickmode="array",
            tickvals=tick_vals,
            tickangle=-45,
            showgrid=True,
            gridcolor="rgba(128, 128, 128, 0.2)",
            rangeslider=dict(visible=False),
            row=row,
            col=1,
        )

    # Update y-axes
    fig.update_yaxes(title="Price (₹)", row=1, col=1)
    fig.update_yaxes(title="Equity (₹)", row=2, col=1)
    fig.update_yaxes(title="Drawdown %", row=3, col=1)

    return fig


# ───────────────────── MAIN EXECUTION ─────────────────────
if __name__ == "__main__":
    try:
        # Step 1: Fetch data from OpenAlgo
        df = fetch_historical_data()

        # Step 2: Run VectorBT backtest
        portfolio, fast_ema, slow_ema, entries, exits = run_backtest(df)

        # Step 3: Print statistics
        stats = print_backtest_stats(portfolio)

        # Step 4: Get trade details
        trades = get_trade_details(portfolio)

        # Step 5: Plot results
        fig = plot_results(df, portfolio, fast_ema, slow_ema, entries, exits)

        # Save as HTML
        output_file = "reliance_ema_backtest.html"
        fig.write_html(output_file)
        print(f"📈 Chart saved to: {output_file}")

        # Show the chart
        fig.show()

        # Also show VectorBT's built-in plot
        print("\n📊 Opening VectorBT Portfolio Plot...")
        portfolio.plot().show()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
