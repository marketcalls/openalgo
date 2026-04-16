# Replay Mode — Multi-Day Paper Trading with Uploaded Market Data

## Overview

Replay Mode allows you to run **paper trading sessions** using historical market
data that you upload, instead of live broker prices. This is useful for:

- Backtesting strategies over specific date ranges
- Practising with real market data without needing a broker connection
- Multi-day replay across equity and F&O instruments

Replay Mode works within the existing **Sandbox / Analyzer** framework. When
enabled, the sandbox execution engine and position manager use uploaded data from
DuckDB (Historify) for order fills and MTM calculations.

---

## Supported Upload Formats

You upload market data as **ZIP files** through the Replay Data Manager UI at
`/sandbox/replay`. Three upload types are supported:

### 1. CM Bhavcopy (NSE Equity Daily)

**Upload type:** `CM_BHAVCOPY`

NSE Cash Market bhavcopy ZIP. Download from
[NSE Archives](https://www.nseindia.com/all-reports-derivatives#702).

**Expected CSV columns:**

| Column | Required | Notes |
|--------|----------|-------|
| `SYMBOL` | Yes | Equity symbol (e.g., `SBIN`, `INFY`) |
| `SERIES` | No | Filtered to EQ/BE/BZ if present |
| `OPEN` | Yes | Open price |
| `HIGH` | Yes | High price |
| `LOW` | Yes | Low price |
| `CLOSE` | Yes | Close price |
| `TOTTRDQTY` | No | Total traded quantity (volume) |
| `TIMESTAMP` | No | Trade date (e.g., `01-Jan-2024`). Extracted from filename if missing |

Stored as: `interval='D'`, `exchange='NSE'`

### 2. FO Bhavcopy (NSE F&O Daily)

**Upload type:** `FO_BHAVCOPY`

NSE F&O bhavcopy ZIP.

**Expected CSV columns:**

| Column | Required | Notes |
|--------|----------|-------|
| `SYMBOL` | Yes | Underlying symbol (e.g., `NIFTY`, `BANKNIFTY`) |
| `EXPIRY_DT` | No | Expiry date for building full symbol name |
| `STRIKE_PR` | No | Strike price for options |
| `OPTION_TYP` | No | `CE`, `PE`, or `XX` for futures |
| `INSTRUMENT` | No | `FUTIDX`, `FUTSTK`, `OPTIDX`, `OPTSTK` |
| `OPEN` | Yes | Open price |
| `HIGH` | Yes | High price |
| `LOW` | Yes | Low price |
| `CLOSE` | Yes | Close price |
| `CONTRACTS` | No | Volume (contracts traded) |
| `OPEN_INT` | No | Open interest |
| `TIMESTAMP` | No | Trade date |

Stored as: `interval='D'`, `exchange='NFO'`

Symbols are automatically constructed in OpenAlgo format
(e.g., `NIFTY28MAR24FUT`, `NIFTY28MAR2420800CE`).

### 3. Intraday 1-Minute OHLCV

**Upload type:** `INTRADAY_1M`

ZIP containing CSV files with 1-minute candlestick data.

**Recommended CSV columns:**

| Column | Required | Notes |
|--------|----------|-------|
| `timestamp` | Yes | Epoch seconds or ISO datetime string |
| `symbol` | Yes | Symbol name |
| `exchange` | No | `NSE` or `NFO` (defaults to `NSE`) |
| `open` | Yes | Open price |
| `high` | Yes | High price |
| `low` | Yes | Low price |
| `close` | Yes | Close price |
| `volume` | No | Volume (defaults to 0) |
| `oi` | No | Open interest (defaults to 0) |

Stored as: `interval='1m'`

Column names are matched flexibly (case-insensitive, with common alternative
names like `ticker`, `datetime`, `vol`, etc.).

---

## Upload Constraints

- Only `.zip` files accepted
- Maximum file size: **200 MB** (configurable via `REPLAY_MAX_ZIP_SIZE_MB` env var)
- Only `.csv` and `.txt` files inside the ZIP are processed
- Zip-slip protection (path traversal prevention) is enforced
- Data is upserted (insert or update) into DuckDB — uploading the same data
  again is safe

---

## How Replay Works

### Quote Resolution

When replay mode is active, the sandbox uses the **ReplayQuoteProvider** instead
of live broker quotes. Quote resolution follows this priority:

1. **1-minute data** (`interval='1m'`): Finds the candle at or nearest before
   the current replay timestamp. LTP = candle close price.
2. **Daily data** (`interval='D'`): If no 1m data is available, uses the daily
   bhavcopy close price for the same trading date.
3. **No data**: Returns `None`. The sandbox execution engine will skip the order
   and log a warning. Orders will remain pending until data becomes available at
   a later replay timestamp, or can be cancelled.

### Replay Clock

The replay clock advances automatically when running:
- **Speed = 1x**: Advances 1 minute per real second
- **Speed = 60x**: Advances 1 hour per real second
- **Speed = 300x**: Advances 5 hours per real second

The clock can be paused, resumed, or seeked to any timestamp within the
configured range.

### Multi-Day Replay

Configure a date range spanning multiple days. The replay clock will advance
through all trading minutes in the range. Note that there is no filtering for
market holidays or non-trading hours — the clock advances continuously, and
quotes are simply unavailable during non-trading periods (the quote provider
returns the last available candle).

### Mode Selection

The quote provider is selected automatically:
- **Analyzer mode ON + Replay running** → ReplayQuoteProvider (DuckDB data)
- **Otherwise** → LiveQuoteProvider (WebSocket / broker API)

---

## API Endpoints

All endpoints require session authentication.

### Upload

```
POST /replay/api/upload
Content-Type: multipart/form-data

Fields:
  file: <ZIP file>
  upload_type: CM_BHAVCOPY | FO_BHAVCOPY | INTRADAY_1M
```

### Replay Control

```
GET  /replay/api/replay/status        # Get current replay state
POST /replay/api/replay/config        # Configure: {start_ts, end_ts, speed, universe_mode}
POST /replay/api/replay/start         # Start or resume
POST /replay/api/replay/pause         # Pause
POST /replay/api/replay/stop          # Stop and reset
POST /replay/api/replay/seek          # Seek: {target_ts}
```

---

## Limitations

- Replay data quality depends on uploaded data accuracy
- No synthetic intraday generation from daily data — if you want intraday
  replay, upload 1-minute data
- The replay clock does not skip weekends or holidays automatically
- Replay state is stored in-memory and resets on server restart
