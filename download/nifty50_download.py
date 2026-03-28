"""
Nifty 50 Full Historical Data Downloader
-----------------------------------------
Downloads ALL available historical data for Nifty 50 stocks across all intervals.
Handles Zerodha's per-call date range limits by chunking requests automatically.

Output: D:/openalgo/nifty50_data/SYMBOL.xlsx
        Tabs: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 1d, 1w

Zerodha limits handled automatically:
  - Max per call: 1m=60d, 3/5/10m=100d, 15/30m=200d, 1h=400d, 1d/1w=2000d
  - Rate limit: 3 req/sec (we use 1 req/2s)
  - 429 error: auto-retry with 12s backoff
  - 2h and 4h NOT supported by Zerodha

Usage:
    cd D:/openalgo
    uv run download/nifty50_download.py
"""

import gc
import logging
import os
import time
from datetime import datetime, date, timedelta

import pandas as pd
from openalgo import api

# ── CONFIG ─────────────────────────────────────────────────────────────────────
API_KEY    = "e152f841a4b1b20114f503111bcb43b4234ea96e36ef8651f3d265c5c16afbdc"
HOST       = "http://127.0.0.1:5000"
EXCHANGE   = "NSE"
OUTPUT_DIR = r"D:\openalgo\nifty50_data"

REQUEST_DELAY       = 2.0   # seconds between API calls (safe under 3 req/sec limit)
RATE_LIMIT_BACKOFF  = 12    # seconds to wait on 429 (Zerodha uses 10s sliding window)

# ── INTERVAL CONFIG ────────────────────────────────────────────────────────────
# chunk_days  = max date range per single Zerodha API call
# history_start = earliest date to fetch from (Zerodha has data from ~Jan 2015 for intraday)
INTERVALS = {
    #  name    chunk   history_start
    "1m":  {"chunk": 60,    "start": "2015-01-01"},
    "3m":  {"chunk": 100,   "start": "2015-01-01"},
    "5m":  {"chunk": 100,   "start": "2015-01-01"},
    "10m": {"chunk": 100,   "start": "2015-01-01"},
    "15m": {"chunk": 200,   "start": "2015-01-01"},
    "30m": {"chunk": 200,   "start": "2015-01-01"},
    "1h":  {"chunk": 400,   "start": "2015-01-01"},
    "1d":  {"chunk": 2000,  "start": "2000-01-01"},
    "1w":  {"chunk": 2000,  "start": "2000-01-01"},
}

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC",
    "INDUSINDBK", "INFY", "JSWSTEEL", "KOTAKBANK", "LT",
    "LTIM", "M&M", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN",
    "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TATAMOTORS",
    "TATASTEEL", "TECHM", "TITAN", "ULTRACEMCO", "WIPRO",
]

# ── SETUP ──────────────────────────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(OUTPUT_DIR, "download.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

client = api(api_key=API_KEY, host=HOST)


# ── DATE CHUNKING ──────────────────────────────────────────────────────────────
def date_chunks(history_start: str, chunk_days: int):
    """Split full history range into chunks respecting Zerodha's per-call limit."""
    start = datetime.strptime(history_start, "%Y-%m-%d").date()
    end   = date.today()
    chunks = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        cursor = chunk_end + timedelta(days=1)
    return chunks


# ── SINGLE CHUNK FETCH ─────────────────────────────────────────────────────────
def fetch_chunk(symbol: str, interval: str, start_date: str, end_date: str):
    for attempt in range(5):
        try:
            response = client.history(
                symbol=symbol,
                exchange=EXCHANGE,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            log.warning(f"    Retry {attempt+1}/5 [{start_date}→{end_date}]: {e}")
            time.sleep(5)
            continue

        if isinstance(response, dict):
            msg = str(response.get("message", "")).lower()
            err = str(response.get("error_type", "")).lower()

            # 429 rate limit — wait out the sliding window
            if "too many" in msg or "rate" in msg or "429" in msg or "throttle" in err:
                log.warning(f"    Rate limited — waiting {RATE_LIMIT_BACKOFF}s ...")
                time.sleep(RATE_LIMIT_BACKOFF)
                continue

            # Connection error — server not running or session expired
            if "connection_error" in err or "connect" in msg:
                log.error(f"    Connection error: {response['message']}")
                log.error("    Is OpenAlgo running? Is Zerodha session active?")
                return None

            if "timestamp" not in response:
                log.warning(f"    No data in range {start_date}→{end_date}: {response.get('message','')}")
                return pd.DataFrame()   # empty but not an error

            df = pd.DataFrame(response)
        else:
            df = response

        if df is None:
            return pd.DataFrame()

        time.sleep(REQUEST_DELAY)
        return df

    log.error(f"    Failed after 5 attempts [{start_date}→{end_date}]")
    return None


# ── FULL INTERVAL FETCH (paginated) ───────────────────────────────────────────
def fetch_interval_full(symbol: str, interval: str, cfg: dict):
    chunks = date_chunks(cfg["start"], cfg["chunk"])
    log.info(f"  [{interval}] {len(chunks)} chunks from {cfg['start']} → today")

    all_frames = []
    for i, (s, e) in enumerate(chunks, 1):
        log.info(f"    chunk {i}/{len(chunks)}: {s} → {e}")
        df = fetch_chunk(symbol, interval, s, e)
        if df is None:
            log.error(f"    Aborting {symbol} [{interval}] — fetch failed")
            return None
        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        log.warning(f"  No data at all for {symbol} [{interval}]")
        return None

    df = pd.concat(all_frames, ignore_index=True)
    df = df.reset_index(drop=True)

    # Normalise columns
    if "timestamp" not in df.columns and df.index.name == "timestamp":
        df = df.reset_index()
    elif "timestamp" not in df.columns:
        df.columns = ["timestamp"] + list(df.columns[1:])

    df["DATE"]   = pd.to_datetime(df["timestamp"]).dt.date
    df["TIME"]   = pd.to_datetime(df["timestamp"]).dt.time
    df["SYMBOL"] = symbol

    cols = ["SYMBOL", "DATE", "TIME", "open", "high", "low", "close", "volume"]
    existing_cols = [c for c in cols if c in df.columns]
    df = df[existing_cols]
    df.columns = [c.upper() for c in existing_cols]

    # Deduplicate (chunks may overlap by 1 day on boundaries)
    df = df.drop_duplicates(subset=["DATE", "TIME"]).reset_index(drop=True)
    log.info(f"  [{interval}] {len(df):,} rows total")
    return df


# ── DOWNLOAD ONE SYMBOL ────────────────────────────────────────────────────────
def download_symbol(symbol: str, mode: str):
    out_path = os.path.join(OUTPUT_DIR, f"{symbol}.xlsx")

    # Load already-completed tabs if resuming
    existing = {}
    if mode == "resume" and os.path.exists(out_path):
        try:
            existing = pd.read_excel(out_path, sheet_name=None, engine="openpyxl")
            log.info(f"  Resuming {symbol} — already done: {list(existing.keys())}")
        except Exception:
            existing = {}

    new_data = dict(existing)

    for interval, cfg in INTERVALS.items():
        if interval in existing:
            log.info(f"  Skipping {symbol} [{interval}] — already downloaded")
            continue

        log.info(f"  === {symbol} [{interval}] ===")
        df = fetch_interval_full(symbol, interval, cfg)
        if df is not None:
            new_data[interval] = df

    if not new_data:
        log.warning(f"  No data for {symbol}")
        return

    log.info(f"  Writing {out_path} ...")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for interval in INTERVALS:
            if interval in new_data:
                new_data[interval].to_excel(writer, sheet_name=interval, index=False)

    log.info(f"  Saved {symbol}.xlsx ({len(new_data)} tabs)")
    gc.collect()


# ── CHECKPOINT ─────────────────────────────────────────────────────────────────
CHECKPOINT = os.path.join(OUTPUT_DIR, "checkpoint.txt")

def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            return f.read().strip()
    return None

def save_checkpoint(symbol: str):
    with open(CHECKPOINT, "w") as f:
        f.write(symbol)


# ── ESTIMATE TIME ──────────────────────────────────────────────────────────────
def estimate_minutes():
    today = date.today()
    total_calls = 0
    for cfg in INTERVALS.values():
        start = datetime.strptime(cfg["start"], "%Y-%m-%d").date()
        days  = (today - start).days
        total_calls += max(1, -(-days // cfg["chunk"]))  # ceiling division
    total_calls *= len(NIFTY50)
    return round(total_calls * REQUEST_DELAY / 60)


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    est = estimate_minutes()
    print("\n" + "="*60)
    print("  Nifty 50 Full Historical Downloader")
    print("="*60)
    print(f"  Output      : {OUTPUT_DIR}")
    print(f"  Stocks      : {len(NIFTY50)}")
    print(f"  Intervals   : {', '.join(INTERVALS)}")
    print(f"  Est. time   : ~{est} minutes ({est//60}h {est%60}m)")
    print(f"  Delay/call  : {REQUEST_DELAY}s  |  429 backoff: {RATE_LIMIT_BACKOFF}s")
    print("="*60)
    print()
    print("  NOTE: OpenAlgo must be running + Zerodha session active")
    print("        http://127.0.0.1:5000")
    print()

    choice = input("  1) Fresh download (all history)\n  2) Resume from checkpoint\n  Choice (1/2): ").strip()
    mode = "resume" if choice == "2" else "fresh"

    symbols = list(NIFTY50)
    if mode == "resume":
        last = load_checkpoint()
        if last and last in symbols:
            idx = symbols.index(last) + 1
            symbols = symbols[idx:]
            log.info(f"Resuming after {last} — {len(symbols)} stocks remaining")
    else:
        if os.path.exists(CHECKPOINT):
            os.remove(CHECKPOINT)

    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        log.info(f"[{i}/{total}] ━━━ {symbol} ━━━")
        try:
            download_symbol(symbol, mode)
            save_checkpoint(symbol)
        except KeyboardInterrupt:
            log.info("Interrupted by user. Run again with option 2 to resume.")
            break
        except Exception as e:
            log.error(f"Unexpected error for {symbol}: {e}")

    print("\n  Done!")
    print(f"  Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
