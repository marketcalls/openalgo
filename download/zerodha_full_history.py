"""
Zerodha Full Historical Data Downloader (Direct Kite Connect)
--------------------------------------------------------------
Downloads ALL available Zerodha historical data for Nifty 50.
Uses pykiteconnect directly — no OpenAlgo server needed.

Output: D:/openalgo/nifty50_data/SYMBOL.xlsx
        Tabs: 1m, 3m, 5m, 10m, 15m, 30m, 1h, 1d, 1w

Data depth:
  Intraday (1m-1h) : from Jan 2015
  Daily (1d/1w)    : from Jan 2000

Usage:
    cd D:/openalgo
    uv run download/zerodha_full_history.py
"""

import gc
import logging
import os
import time
from datetime import datetime, date, timedelta

import pandas as pd
from kiteconnect import KiteConnect

# ── YOUR ZERODHA CREDENTIALS ───────────────────────────────────────────────────
API_KEY    = "pudcjq8t2bgo3qjg"       # your Kite Connect API key
API_SECRET = "qpchcz7wltpg5e5iec79rlkvxvwlq2bo"   # your Kite Connect API secret

OUTPUT_DIR = r"D:\openalgo\nifty50_data"

# ── INTERVAL CONFIG ────────────────────────────────────────────────────────────
# Zerodha interval names + max days per call + earliest data available
INTERVALS = {
    "1m":  {"kite": "minute",    "chunk": 60,   "start": "2015-01-01"},
    "3m":  {"kite": "3minute",   "chunk": 100,  "start": "2015-01-01"},
    "5m":  {"kite": "5minute",   "chunk": 100,  "start": "2015-01-01"},
    "10m": {"kite": "10minute",  "chunk": 100,  "start": "2015-01-01"},
    "15m": {"kite": "15minute",  "chunk": 200,  "start": "2015-01-01"},
    "30m": {"kite": "30minute",  "chunk": 200,  "start": "2015-01-01"},
    "1h":  {"kite": "60minute",  "chunk": 400,  "start": "2015-01-01"},
    "1d":  {"kite": "day",       "chunk": 2000, "start": "2000-01-01"},
    "1w":  {"kite": "week",      "chunk": 2000, "start": "2000-01-01"},  # not natively supported - fallback to day
}

REQUEST_DELAY      = 0.4   # seconds between calls (Zerodha allows 3/sec, we use 2.5/sec)
RATE_LIMIT_BACKOFF = 12    # seconds to wait on 429

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
        logging.FileHandler(os.path.join(OUTPUT_DIR, "zerodha_download.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── ZERODHA LOGIN ──────────────────────────────────────────────────────────────
def login() -> KiteConnect:
    kite = KiteConnect(api_key=API_KEY)
    print("\n" + "="*60)
    print("  ZERODHA LOGIN")
    print("="*60)
    print(f"\n  Open this URL in your browser to login:")
    print(f"\n  {kite.login_url()}")
    print()
    request_token = input("  Paste the request_token from the redirect URL: ").strip()
    data = kite.generate_session(request_token, api_secret=API_SECRET)
    kite.set_access_token(data["access_token"])
    log.info(f"Logged in as: {data['user_name']} ({data['user_id']})")
    return kite


# ── INSTRUMENT LOOKUP ──────────────────────────────────────────────────────────
def build_instrument_map(kite: KiteConnect) -> dict:
    """Build symbol -> instrument_token map for NSE."""
    log.info("Fetching instrument list from Zerodha ...")
    instruments = kite.instruments("NSE")
    token_map = {
        inst["tradingsymbol"]: inst["instrument_token"]
        for inst in instruments
        if inst["segment"] == "NSE"
    }
    log.info(f"Loaded {len(token_map)} NSE instruments")
    return token_map


# ── DATE CHUNKING ──────────────────────────────────────────────────────────────
def date_chunks(history_start: str, chunk_days: int):
    start  = datetime.strptime(history_start, "%Y-%m-%d").date()
    end    = date.today()
    chunks = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((
            datetime.combine(cursor,    datetime.min.time()),
            datetime.combine(chunk_end, datetime.max.time().replace(microsecond=0)),
        ))
        cursor = chunk_end + timedelta(days=1)
    return chunks


# ── SINGLE CHUNK FETCH ─────────────────────────────────────────────────────────
def fetch_chunk(kite: KiteConnect, token: int, kite_interval: str,
                from_dt: datetime, to_dt: datetime) -> pd.DataFrame:
    for attempt in range(5):
        try:
            data = kite.historical_data(
                instrument_token=token,
                from_date=from_dt,
                to_date=to_dt,
                interval=kite_interval,
                continuous=False,
                oi=False,
            )
            if not data:
                return pd.DataFrame()
            df = pd.DataFrame(data)
            time.sleep(REQUEST_DELAY)
            return df

        except Exception as e:
            err = str(e).lower()
            if "too many" in err or "429" in err or "rate" in err:
                log.warning(f"    Rate limited — waiting {RATE_LIMIT_BACKOFF}s ...")
                time.sleep(RATE_LIMIT_BACKOFF)
            else:
                log.warning(f"    Retry {attempt+1}/5: {e}")
                time.sleep(3)

    log.error(f"    Failed after 5 attempts: {from_dt} → {to_dt}")
    return None


# ── FULL INTERVAL FETCH (paginated) ───────────────────────────────────────────
def fetch_interval_full(kite: KiteConnect, symbol: str, token: int,
                        interval: str, cfg: dict) -> pd.DataFrame:
    chunks = date_chunks(cfg["start"], cfg["chunk"])
    log.info(f"  [{interval}] {len(chunks)} chunks from {cfg['start']} → today")

    frames = []
    for i, (s, e) in enumerate(chunks, 1):
        log.info(f"    chunk {i}/{len(chunks)}: {s.date()} → {e.date()}")
        df = fetch_chunk(kite, token, cfg["kite"], s, e)
        if df is None:
            log.error(f"    Aborting {symbol} [{interval}]")
            return None
        if not df.empty:
            frames.append(df)

    if not frames:
        log.warning(f"  No data: {symbol} [{interval}]")
        return None

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["date"]).reset_index(drop=True)
    df["DATE"]   = pd.to_datetime(df["date"]).dt.date
    df["TIME"]   = pd.to_datetime(df["date"]).dt.time
    df["SYMBOL"] = symbol
    df = df[["SYMBOL", "DATE", "TIME", "open", "high", "low", "close", "volume"]]
    df.columns   = ["SYMBOL", "DATE", "TIME", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]
    log.info(f"  [{interval}] {len(df):,} rows total")
    return df


# ── DOWNLOAD ONE SYMBOL ────────────────────────────────────────────────────────
def download_symbol(kite: KiteConnect, symbol: str, token: int, mode: str):
    out_path = os.path.join(OUTPUT_DIR, f"{symbol}.xlsx")

    existing = {}
    if mode == "resume" and os.path.exists(out_path):
        try:
            existing = pd.read_excel(out_path, sheet_name=None, engine="openpyxl")
            log.info(f"  Already done: {list(existing.keys())}")
        except Exception:
            existing = {}

    new_data = dict(existing)

    for interval, cfg in INTERVALS.items():
        if interval in existing:
            log.info(f"  Skipping [{interval}] — already downloaded")
            continue
        log.info(f"  === {symbol} [{interval}] ===")
        df = fetch_interval_full(kite, symbol, token, interval, cfg)
        if df is not None:
            new_data[interval] = df

    if not new_data:
        log.warning(f"  No data for {symbol}")
        return

    log.info(f"  Writing {symbol}.xlsx ...")
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for interval in INTERVALS:
            if interval in new_data:
                new_data[interval].to_excel(writer, sheet_name=interval, index=False)

    log.info(f"  Saved {symbol}.xlsx ({len(new_data)} tabs)")
    gc.collect()


# ── CHECKPOINT ─────────────────────────────────────────────────────────────────
CHECKPOINT = os.path.join(OUTPUT_DIR, "kite_checkpoint.txt")

def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            return f.read().strip()
    return None

def save_checkpoint(symbol: str):
    with open(CHECKPOINT, "w") as f:
        f.write(symbol)


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    kite     = login()
    inst_map = build_instrument_map(kite)

    # Verify all symbols exist
    missing = [s for s in NIFTY50 if s not in inst_map]
    if missing:
        log.warning(f"Symbols not found in NSE instruments: {missing}")

    symbols = [s for s in NIFTY50 if s in inst_map]

    print("\n" + "="*60)
    print("  Nifty 50 Full History — Direct Kite Connect")
    print("="*60)
    print(f"  Stocks    : {len(symbols)}")
    print(f"  Intervals : {', '.join(INTERVALS)}")
    print(f"  Intraday  : Jan 2015 → today")
    print(f"  Daily/Wkly: Jan 2000 → today")
    print("="*60 + "\n")

    choice = input("  1) Fresh download\n  2) Resume from checkpoint\n  Choice (1/2): ").strip()
    mode   = "resume" if choice == "2" else "fresh"

    if mode == "fresh" and os.path.exists(CHECKPOINT):
        os.remove(CHECKPOINT)
    elif mode == "resume":
        last = load_checkpoint()
        if last and last in symbols:
            idx     = symbols.index(last) + 1
            symbols = symbols[idx:]
            log.info(f"Resuming after {last} — {len(symbols)} stocks left")

    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        token = inst_map[symbol]
        log.info(f"[{i}/{total}] ━━━ {symbol} (token={token}) ━━━")
        try:
            download_symbol(kite, symbol, token, mode)
            save_checkpoint(symbol)
        except KeyboardInterrupt:
            log.info("Interrupted. Run again with option 2 to resume.")
            break
        except Exception as e:
            log.error(f"Error for {symbol}: {e}")

    print(f"\n  Done! Files saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
