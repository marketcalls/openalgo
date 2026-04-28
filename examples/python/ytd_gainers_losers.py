# ---------------------------------------------------
# YTD 2026 Gainers & Losers for NIFTY 50
# Baseline: close on 2025-12-31 (last trading day of 2025)
# Data source: OpenAlgo Historify local DuckDB (source='db')
# ---------------------------------------------------

import pandas as pd
from openalgo import api

client = api(
    api_key="afd010bd748c9129d71901c53c1efb327c822fa5264e31959506d7aede79a336",
    host="http://127.0.0.1:5000",
)

SYMBOLS = [
    "INDIGO", "TRENT", "HINDUNILVR", "HCLTECH", "WIPRO", "INFY", "TATACONSUM",
    "TATASTEEL", "ITC", "ASIANPAINT", "SBILIFE", "LT", "SHRIRAMFIN", "BEL",
    "SBIN", "COALINDIA", "KOTAKBANK", "TCS", "SUNPHARMA", "MAXHEALTH",
    "NESTLEIND", "RELIANCE", "ETERNAL", "APOLLOHOSP", "ICICIBANK", "GRASIM",
    "ULTRACEMCO", "ADANIENT", "AXISBANK", "DRREDDY", "TECHM", "TMPV", "JIOFIN",
    "NTPC", "BAJFINANCE", "BHARTIARTL", "POWERGRID", "HINDALCO", "HDFCBANK",
    "TITAN", "HDFCLIFE", "MARUTI", "BAJAJFINSV", "ADANIPORTS", "CIPLA",
    "JSWSTEEL", "BAJAJ-AUTO", "ONGC", "EICHERMOT", "M&M",
]

BASELINE_DATE = pd.Timestamp("2025-12-31").date()
START_FETCH = "2025-12-30"
END_FETCH = "2026-12-31"

rows = []
missing = []
for sym in SYMBOLS:
    try:
        df = client.history(
            symbol=sym,
            exchange="NSE",
            interval="D",
            start_date=START_FETCH,
            end_date=END_FETCH,
            source="db",
        )
    except Exception as e:
        missing.append((sym, f"fetch error: {e}"))
        continue

    if not isinstance(df, pd.DataFrame) or df.empty:
        missing.append((sym, "no rows"))
        continue

    df = df.sort_index()
    df.index = pd.to_datetime(df.index).date

    if BASELINE_DATE not in df.index:
        missing.append((sym, f"no {BASELINE_DATE} close"))
        continue

    base = df.loc[BASELINE_DATE, "close"]
    last_date = df.index[-1]
    last_close = df.loc[last_date, "close"]
    if base <= 0:
        missing.append((sym, "non-positive base"))
        continue

    pct = ((last_close / base) - 1.0) * 100.0
    rows.append({
        "symbol": sym,
        "base_2025_12_31": round(float(base), 2),
        "last_close": round(float(last_close), 2),
        "last_date": last_date.isoformat(),
        "ytd_pct": round(float(pct), 2),
    })

if not rows:
    raise SystemExit("No data for any symbol. Run Historify bulk download first.")

df_all = pd.DataFrame(rows).sort_values("ytd_pct", ascending=False).reset_index(drop=True)
last_date_str = df_all["last_date"].iloc[0]

print(f"\n=== NIFTY 50 YTD 2026 (2025-12-31 close → {last_date_str}) ===\n")

print("TOP 10 GAINERS")
print(df_all.head(10).to_string(index=False))

print("\nTOP 10 LOSERS")
print(df_all.tail(10).iloc[::-1].to_string(index=False))

if missing:
    print(f"\nSkipped {len(missing)} symbols:")
    for sym, reason in missing:
        print(f"  {sym}: {reason}")
