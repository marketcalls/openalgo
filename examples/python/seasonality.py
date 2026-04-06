import pandas as pd
import numpy as np
import plotly.graph_objects as go
from openalgo import api

# ─── Configuration ───────────────────────────────────────────────
API_KEY = "9d5d445ffb2b55af20871a6142e2cedf8c1002e55fce8a93ebe7028b0a6b7cc4"
HOST = "http://127.0.0.1:5000"
SYMBOL = "ICICIBANK"
EXCHANGE = "NSE"
START_YEAR = 2015
COLOR_CUTOFF = 10  # max intensity cutoff (%)

# TradingView color theme
POS_COLOR = (8, 153, 129)    # #089981
NEG_COLOR = (242, 55, 69)    # #F23745
BG_COLOR = "#1e222d"
HEADER_BG = "rgba(128,128,128,0.2)"
TEXT_COLOR = "#d1d4dc"
LINE_COLOR = "rgba(128,128,128,0.3)"

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def calc_cell_color(value, cutoff=COLOR_CUTOFF):
    """Calculate cell background color matching TradingView's gradient logic."""
    if pd.isna(value):
        return "rgba(128,128,128,0.3)"

    base = POS_COLOR if value >= 0 else NEG_COLOR
    # Map absolute value to opacity range [0.10, 0.50] (light to heavy)
    intensity = min(abs(value) / cutoff, 1.0)
    opacity = 0.10 + intensity * 0.40
    return f"rgba({base[0]},{base[1]},{base[2]},{opacity})"


def calc_pos_pct_color(value, cutoff=50):
    """Color for Pos% row: treat (value - 50) as the signed value."""
    if pd.isna(value):
        return "rgba(128,128,128,0.3)"
    shifted = value - 50
    base = POS_COLOR if shifted >= 0 else NEG_COLOR
    intensity = min(abs(shifted) / cutoff, 1.0)
    opacity = 0.10 + intensity * 0.40
    return f"rgba({base[0]},{base[1]},{base[2]},{opacity})"


def fetch_monthly_data(client, symbol, exchange, start_year):
    """Fetch daily data and resample to monthly close prices."""
    start_date = f"{start_year - 1}-12-01"
    end_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    df = client.history(
        symbol=symbol,
        exchange=exchange,
        interval="D",
        start_date=start_date,
        end_date=end_date
    )

    if df is None or df.empty:
        raise ValueError("No data returned from API. Check symbol/exchange/dates.")

    # Resample to monthly — use last close of each month
    monthly = df["close"].resample("ME").last()
    monthly = monthly.dropna()

    # Drop the current incomplete month — only keep fully completed months
    today = pd.Timestamp.now(tz=monthly.index.tz)
    last_complete_month_end = (today.replace(day=1) - pd.Timedelta(days=1)).normalize()
    monthly = monthly[monthly.index <= last_complete_month_end]

    return monthly


def build_seasonality_matrix(monthly_close, start_year):
    """Build year x month matrix of monthly % returns (prev month close to current month close)."""
    # Monthly return: (current_close - prev_close) / abs(prev_close) * 100
    returns = monthly_close.pct_change() * 100

    years = sorted(set(returns.index.year))
    years = [y for y in years if y >= start_year]

    matrix = pd.DataFrame(index=years, columns=range(1, 13), dtype=float)

    for dt, ret in returns.items():
        if dt.year >= start_year:
            matrix.loc[dt.year, dt.month] = ret

    return matrix


def build_heatmap_figure(matrix):
    """Build Plotly figure matching the TradingView seasonality heatmap."""
    years = list(matrix.index)
    n_years = len(years)

    # Calculate metrics
    avgs = [matrix[m].mean() for m in range(1, 13)]
    stdevs = [matrix[m].std(ddof=1) for m in range(1, 13)]
    pos_pcts = []
    for m in range(1, 13):
        col = matrix[m].dropna()
        pos_pcts.append((col >= 0).sum() / len(col) * 100 if len(col) > 0 else float("nan"))

    # Table columns: Year + 12 months
    header = ["Year"] + MONTH_NAMES

    # Total data rows: years + divider + avgs + stdev + pos%
    n_rows = n_years + 4

    # Build cell values and colors column by column (Plotly table format)
    cell_values = [[] for _ in range(13)]
    cell_colors = [[] for _ in range(13)]

    # Year rows
    for year in years:
        cell_values[0].append(str(year))
        cell_colors[0].append(HEADER_BG)
        for m in range(1, 13):
            val = matrix.loc[year, m]
            if pd.isna(val):
                cell_values[m].append("NaN%")
                cell_colors[m].append("rgba(128,128,128,0.3)")
            else:
                cell_values[m].append(f"{val:.2f}%")
                cell_colors[m].append(calc_cell_color(val))

    # Divider row
    for c in range(13):
        cell_values[c].append("")
        cell_colors[c].append(HEADER_BG)

    # Avgs row
    cell_values[0].append("Avgs:")
    cell_colors[0].append(HEADER_BG)
    for m in range(1, 13):
        val = avgs[m - 1]
        cell_values[m].append(f"{val:.2f}%")
        cell_colors[m].append(calc_cell_color(val))

    # StDev row
    cell_values[0].append("StDev:")
    cell_colors[0].append(HEADER_BG)
    for m in range(1, 13):
        val = stdevs[m - 1]
        cell_values[m].append(f"{val:.2f}")
        cell_colors[m].append("rgba(128,128,128,0.2)")

    # Pos% row
    cell_values[0].append("Pos%:")
    cell_colors[0].append(HEADER_BG)
    for m in range(1, 13):
        val = pos_pcts[m - 1]
        cell_values[m].append(f"{val:.0f}%")
        cell_colors[m].append(calc_pos_pct_color(val))

    fig = go.Figure(data=[go.Table(
        columnwidth=[80] + [100] * 12,
        header=dict(
            values=header,
            fill_color=HEADER_BG,
            font=dict(color=TEXT_COLOR, size=15, family="Trebuchet MS, sans-serif"),
            align="center",
            line=dict(color=LINE_COLOR, width=1),
            height=40,
        ),
        cells=dict(
            values=cell_values,
            fill_color=cell_colors,
            font=dict(color=TEXT_COLOR, size=14, family="Trebuchet MS, sans-serif"),
            align="center",
            line=dict(color=LINE_COLOR, width=1),
            height=36,
        ),
    )])

    fig.update_layout(
        title=dict(
            text=f"Seasonality — {SYMBOL} ({EXCHANGE}) Monthly Returns",
            font=dict(color=TEXT_COLOR, size=16, family="Trebuchet MS, sans-serif"),
            x=0.5,
        ),
        paper_bgcolor=BG_COLOR,
        margin=dict(l=10, r=10, t=50, b=10),
        height=max(400, 40 + n_rows * 36 + 60),
    )

    return fig


def main():
    client = api(api_key=API_KEY, host=HOST)

    print(f"Fetching daily data for {SYMBOL} on {EXCHANGE}...")
    monthly_close = fetch_monthly_data(client, SYMBOL, EXCHANGE, START_YEAR)
    print(f"Got {len(monthly_close)} monthly data points")

    matrix = build_seasonality_matrix(monthly_close, START_YEAR)
    print(f"Built seasonality matrix: {matrix.shape[0]} years x {matrix.shape[1]} months")
    print()

    # Print the matrix to console
    display_df = matrix.round(2).copy()
    display_df.columns = MONTH_NAMES
    print(display_df.to_string())
    print()

    # Build and show the Plotly heatmap
    fig = build_heatmap_figure(matrix)
    fig.show()
    print("Seasonality chart opened in browser.")


if __name__ == "__main__":
    main()
