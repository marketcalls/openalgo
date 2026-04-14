"""
NIFTY Option Chain - CE/PE Open Interest Histogram (Side by Side)
Author : OpenAlgo GPT
Description: Plots Option Chain OI histogram for NIFTY 27JAN26 expiry
             CE (green) and PE (red) bars SIDE BY SIDE
             Only 100-point strikes (no 50s)
             White background
"""

print("🔁 OpenAlgo Python Bot is running.")

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from openalgo import api

# ───────────────────────── CONFIG ─────────────────────────
API_KEY = "3f75e26648a543a886c9b38332a6942e30e0710bbf0488cf432ef27745de8ae7"
API_HOST = "http://127.0.0.1:5000"

# Option Chain Parameters
UNDERLYING = "NIFTY"
EXCHANGE = "NSE_INDEX"
EXPIRY = "27JAN26"  # 27 January 2026 expiry
STRIKE_COUNT = 40  # Number of strikes around ATM
LOT_SIZE = 75  # NIFTY lot size
STRIKE_FILTER = 100  # Only show strikes divisible by 100

# ─────────────────────── INIT CLIENT ──────────────────────
client = api(api_key=API_KEY, host=API_HOST)


# ───────────────────── FETCH OPTION CHAIN ─────────────────────
def fetch_option_chain():
    """Fetch option chain data from OpenAlgo API"""

    print(f"\n📥 Fetching {UNDERLYING} Option Chain for {EXPIRY} expiry...")

    chain_data = client.optionchain(
        underlying=UNDERLYING, exchange=EXCHANGE, expiry_date=EXPIRY, strike_count=STRIKE_COUNT
    )

    print(f"Option Chain Response Status: {chain_data.get('status', 'N/A')}")

    if chain_data.get("status") != "success":
        raise ValueError(f"Failed to fetch option chain: {chain_data}")

    underlying_ltp = chain_data.get("underlying_ltp", 0)
    atm_strike = chain_data.get("atm_strike", 0)
    chain = chain_data.get("chain", [])

    print(f"✅ Underlying LTP: {underlying_ltp}")
    print(f"✅ ATM Strike: {atm_strike}")
    print(f"✅ Total Strikes (raw): {len(chain)}")

    return chain_data


# ───────────────────── PROCESS CHAIN DATA ─────────────────────
def process_chain_data(chain_data):
    """Process option chain into DataFrame for plotting"""

    chain = chain_data.get("chain", [])
    atm_strike = chain_data.get("atm_strike", 0)
    underlying_ltp = chain_data.get("underlying_ltp", 0)

    rows = []

    for item in chain:
        strike = item.get("strike", 0)

        # Filter: Only 100-point strikes (ignore 50s)
        if int(strike) % STRIKE_FILTER != 0:
            continue

        ce = item.get("ce", {})
        pe = item.get("pe", {})

        # Convert OI to lots
        ce_oi = ce.get("oi", 0)
        pe_oi = pe.get("oi", 0)
        ce_oi_lots = ce_oi // LOT_SIZE if ce_oi else 0
        pe_oi_lots = pe_oi // LOT_SIZE if pe_oi else 0

        rows.append(
            {
                "strike": int(strike),
                "ce_ltp": ce.get("ltp", 0),
                "pe_ltp": pe.get("ltp", 0),
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_oi_lots": ce_oi_lots,
                "pe_oi_lots": pe_oi_lots,
                "ce_volume": ce.get("volume", 0),
                "pe_volume": pe.get("volume", 0),
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values("strike").reset_index(drop=True)

    # Round ATM to nearest 100
    atm_strike_100 = int(round(atm_strike / 100) * 100)

    print(f"✅ Filtered Strikes (100s only): {len(df)}")
    print(f"📊 Strike Range: {df['strike'].min()} to {df['strike'].max()}")
    print(f"📊 Total CE OI (lots): {df['ce_oi_lots'].sum():,}")
    print(f"📊 Total PE OI (lots): {df['pe_oi_lots'].sum():,}")
    print(
        f"📊 PCR (OI): {df['pe_oi'].sum() / df['ce_oi'].sum():.2f}"
        if df["ce_oi"].sum() > 0
        else "   PCR: N/A"
    )

    return df, atm_strike_100, underlying_ltp


# ───────────────────── FORMAT NUMBER ─────────────────────
def format_num(x):
    """Format number as K for thousands"""
    if x >= 1000:
        return f"{x / 1000:.0f}K"
    return str(int(x))


# ───────────────────── PLOT OI HISTOGRAM SIDE BY SIDE ─────────────────────
def plot_oi_side_by_side(df, atm_strike, underlying_ltp, expiry):
    """Create OI histogram with CE and PE bars side by side"""

    fig = go.Figure()

    strikes = df["strike"].tolist()

    # CE OI - Green bars
    fig.add_trace(
        go.Bar(
            x=df["strike"].astype(str),
            y=df["ce_oi_lots"],
            name="Call OI",
            marker=dict(
                color="rgba(34, 197, 94, 0.9)",  # Green
                line=dict(color="rgba(22, 163, 74, 1)", width=1),
            ),
            text=[format_num(x) for x in df["ce_oi_lots"]],
            textposition="outside",
            textfont=dict(size=9, color="rgba(22, 163, 74, 1)"),
            customdata=np.column_stack(
                [
                    df["ce_oi_lots"],
                    df["pe_oi_lots"],
                    df["ce_ltp"],
                    df["pe_ltp"],
                ]
            ),
            hovertemplate=(
                "<b>Strike: %{x}</b><br>"
                "Call OI (lots): <b>%{customdata[0]:,.0f}</b><br>"
                "Put OI (lots): %{customdata[1]:,.0f}<br>"
                "Call Price: ₹%{customdata[2]:.2f}<br>"
                "Put Price: ₹%{customdata[3]:.2f}<br>"
                "<extra></extra>"
            ),
        )
    )

    # PE OI - Red bars
    fig.add_trace(
        go.Bar(
            x=df["strike"].astype(str),
            y=df["pe_oi_lots"],
            name="Put OI",
            marker=dict(
                color="rgba(239, 68, 68, 0.9)",  # Red
                line=dict(color="rgba(220, 38, 38, 1)", width=1),
            ),
            text=[format_num(x) for x in df["pe_oi_lots"]],
            textposition="outside",
            textfont=dict(size=9, color="rgba(220, 38, 38, 1)"),
            customdata=np.column_stack(
                [
                    df["ce_oi_lots"],
                    df["pe_oi_lots"],
                    df["ce_ltp"],
                    df["pe_ltp"],
                ]
            ),
            hovertemplate=(
                "<b>Strike: %{x}</b><br>"
                "Call OI (lots): %{customdata[0]:,.0f}<br>"
                "Put OI (lots): <b>%{customdata[1]:,.0f}</b><br>"
                "Call Price: ₹%{customdata[2]:.2f}<br>"
                "Put Price: ₹%{customdata[3]:.2f}<br>"
                "<extra></extra>"
            ),
        )
    )

    # Find ATM position for vertical line
    strike_list = df["strike"].astype(str).tolist()
    atm_str = str(atm_strike)

    if atm_str in strike_list:
        atm_idx = strike_list.index(atm_str)

        # Add ATM vertical line
        fig.add_shape(
            type="line",
            x0=atm_idx - 0.5,
            x1=atm_idx - 0.5,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",
            line=dict(color="rgba(100, 100, 100, 0.7)", width=2, dash="dash"),
        )

        # ATM annotation
        fig.add_annotation(
            x=atm_idx,
            y=1.02,
            xref="x",
            yref="paper",
            text=f"ATM: {atm_strike}",
            showarrow=False,
            font=dict(size=11, color="black", family="Arial Black"),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="gray",
            borderwidth=1,
            borderpad=3,
        )

    # PCR calculation
    total_ce = df["ce_oi"].sum()
    total_pe = df["pe_oi"].sum()
    pcr = total_pe / total_ce if total_ce > 0 else 0

    # Max OI strikes
    max_ce_strike = df.loc[df["ce_oi_lots"].idxmax(), "strike"]
    max_pe_strike = df.loc[df["pe_oi_lots"].idxmax(), "strike"]
    max_ce_oi = df["ce_oi_lots"].max()
    max_pe_oi = df["pe_oi_lots"].max()

    # Current time
    current_time = datetime.now().strftime("%d %b %Y %H:%M")

    # Layout - WHITE BACKGROUND
    fig.update_layout(
        title=dict(
            text=f"NIFTY {expiry} - current",
            x=0.5,
            font=dict(size=18, color="black", family="Arial"),
        ),
        xaxis=dict(
            title="Strike Price",
            type="category",
            tickangle=-45,
            tickfont=dict(size=9, color="black"),
            showgrid=True,
            gridcolor="rgba(200, 200, 200, 0.5)",
            showline=True,
            linecolor="black",
            linewidth=1,
        ),
        yaxis=dict(
            title=dict(text="Open Interest (Lots)", font=dict(color="black")),
            showgrid=True,
            gridcolor="rgba(200, 200, 200, 0.5)",
            tickformat=",d",
            tickfont=dict(color="black"),
            showline=True,
            linecolor="black",
            linewidth=1,
        ),
        # WHITE BACKGROUND
        template="plotly_white",
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=600,
        width=1500,
        barmode="group",  # Side by side bars
        bargap=0.15,
        bargroupgap=0.05,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.2,
            xanchor="center",
            x=0.5,
            font=dict(color="black"),
        ),
        margin=dict(l=80, r=100, t=80, b=100),
        annotations=[
            # Timestamp
            dict(
                text=f"{current_time}",
                xref="paper",
                yref="paper",
                x=1,
                y=1.06,
                showarrow=False,
                font=dict(size=11, color="gray"),
                bgcolor="rgba(240,240,240,0.8)",
                borderpad=4,
            ),
            # PCR on right side
            dict(
                text=f"PCR: {pcr:.2f}",
                xref="paper",
                yref="paper",
                x=1.04,
                y=0.5,
                showarrow=False,
                font=dict(size=12, color="black", family="Arial Black"),
                textangle=-90,
            ),
            # Max OI info at bottom
            dict(
                text=f"Max CE OI: {max_ce_strike} ({format_num(max_ce_oi)}) | Max PE OI: {max_pe_strike} ({format_num(max_pe_oi)})",
                xref="paper",
                yref="paper",
                x=0.5,
                y=-0.18,
                showarrow=False,
                font=dict(size=10, color="gray"),
            ),
        ],
    )

    return fig


# ───────────────────── PRINT OI TABLE ─────────────────────
def print_oi_table(df, atm_strike):
    """Print top OI strikes"""

    print(f"\n{'=' * 70}")
    print("📊 TOP 10 STRIKES BY OI")
    print(f"{'=' * 70}")

    print("\n🟢 TOP 5 CALL OI (Resistance Levels):")
    top_ce = df.nlargest(5, "ce_oi_lots")[["strike", "ce_oi_lots", "ce_ltp"]]
    for _, row in top_ce.iterrows():
        marker = " ⬅️ ATM" if row["strike"] == atm_strike else ""
        print(
            f"   Strike {int(row['strike'])}: {int(row['ce_oi_lots']):>10,} lots | LTP: ₹{row['ce_ltp']:.2f}{marker}"
        )

    print("\n🔴 TOP 5 PUT OI (Support Levels):")
    top_pe = df.nlargest(5, "pe_oi_lots")[["strike", "pe_oi_lots", "pe_ltp"]]
    for _, row in top_pe.iterrows():
        marker = " ⬅️ ATM" if row["strike"] == atm_strike else ""
        print(
            f"   Strike {int(row['strike'])}: {int(row['pe_oi_lots']):>10,} lots | LTP: ₹{row['pe_ltp']:.2f}{marker}"
        )

    print(f"{'=' * 70}\n")


# ───────────────────── MAIN EXECUTION ─────────────────────
if __name__ == "__main__":
    try:
        # Fetch option chain
        chain_data = fetch_option_chain()

        # Process data (filter 100s only)
        df, atm_strike, underlying_ltp = process_chain_data(chain_data)

        # Print OI table
        print_oi_table(df, atm_strike)

        # Create side-by-side plot
        fig = plot_oi_side_by_side(df, atm_strike, underlying_ltp, EXPIRY)

        # Save and show
        output_file = f"nifty_oi_chain_{EXPIRY}.html"
        fig.write_html(output_file)
        print(f"📈 Chart saved to: {output_file}")

        fig.show()

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
