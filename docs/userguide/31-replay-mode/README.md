# 31 - Replay Mode: Multi-Day Paper Trading with Uploaded Market Data

## Introduction

**Replay Mode** lets you run paper-trading sessions using your own uploaded historical
market data instead of live broker prices. You upload NSE bhavcopies or intraday
1-minute CSVs, set a date range and playback speed, press Start — and the sandbox
processes orders and MTM calculations exactly as it would during a live session, but
driven by the stored data.

This is the recommended way to:

- **Backtest strategies** on real historical data without writing custom backtest code
- **Practice order placement** on past dates without a live broker connection
- **Reproduce and debug** past trading decisions with full replay control
- **Train team members** on specific market scenarios (e.g. a volatile expiry day)

Replay Mode is an extension of [Analyzer Mode (Module 15)](../15-analyzer-mode/README.md).
You must have Analyzer Mode enabled for Replay Mode to affect order fills and MTM.

---

## How It All Fits Together

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Replay Mode Architecture                               │
│                                                                              │
│   You upload                You control                Sandbox uses          │
│   NSE ZIP data   →→→  Replay clock (start/pause) →→→  DuckDB prices        │
│   (bhavcopies,         +  date range & speed           for fills & MTM       │
│    1m OHLCV)                                                                 │
│                                                                              │
│   ┌──────────────┐    ┌──────────────────────┐    ┌─────────────────────┐   │
│   │ DuckDB       │    │ Replay Service       │    │ ReplayQuoteProvider │   │
│   │ (historify)  │◄───│ (clock thread)       │◄───│ (sandbox engine)   │   │
│   └──────────────┘    └──────────────────────┘    └─────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Quote source selection logic:**

| Analyzer Mode | Paper Price Source | Source Used           |
|---------------|--------------------|-----------------------|
| OFF           | (any)              | Not applicable — live trading |
| ON            | LIVE (default)     | Live broker prices (WebSocket / REST) |
| ON            | REPLAY             | DuckDB data at current replay timestamp |

---

## Prerequisites

Before using Replay Mode you need:

1. ✅ **Analyzer Mode enabled** — Go to `/analyzer` and turn it on
2. ✅ **NSE bhavcopy or 1-minute data ZIPs** downloaded for your target date range
3. ✅ Browser logged in to OpenAlgo

---

## Step 1 — Navigate to Replay Data Manager

Go to:

```
http://127.0.0.1:5000/sandbox/replay
```

or navigate: **Sandbox → Replay Data Manager** from the sidebar.

```
┌────────────────────────────────────────────────────────────────────┐
│  🗃  Replay Data Manager                                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  📡 Paper Trading Price Source                               │   │
│  │  ○ 📡 Live Quotes     ● 🎞️ Replay Data                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ⬆ Upload Market Data                                              │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐            │
│  │ CM Bhavcopy   │ │ FO Bhavcopy   │ │ Intraday 1-Min│            │
│  │  (Equity)     │ │  (F&O)        │ │               │            │
│  └───────────────┘ └───────────────┘ └───────────────┘            │
│                                                                     │
│  ▶ Replay Controller                                               │
│  Status: STOPPED  │  Start  │  Pause  │  Stop                     │
└────────────────────────────────────────────────────────────────────┘
```

---

## Step 2 — Download NSE Data ZIPs

Replay Mode supports three data types. You need to download the ZIP files from NSE's
public archives.

### CM Bhavcopy (NSE Equity — Daily)

- **URL**: [NSE Equity Bhavcopy Archive](https://www.nseindia.com/all-reports-derivatives#702)
- **File name pattern**: `cm<DD><MON><YYYY>bhav.csv.zip`
  - Example: `cm15APR2024bhav.csv.zip`
- **Content**: Daily OHLCV for all NSE equity instruments
- **Required columns**: `SYMBOL`, `SERIES`, `OPEN`, `HIGH`, `LOW`, `CLOSE`
- **Note**: Only `EQ`, `BE`, and `BZ` series are imported

### FO Bhavcopy (NSE F&O — Daily)

- **URL**: [NSE F&O Bhavcopy Archive](https://www.nseindia.com/all-reports-derivatives#702)
- **File name pattern**: `fo<DD><MON><YYYY>bhav.csv.zip`
  - Example: `fo15APR2024bhav.csv.zip`
- **Content**: Daily OHLCV + OI for futures and options
- **Required columns**: `SYMBOL`, `EXPIRY_DT`, `STRIKE_PR`, `OPTION_TYP`, `OPEN`, `HIGH`, `LOW`, `CLOSE`
- **Note**: Symbols are automatically built in OpenAlgo format (e.g. `NIFTY28MAR24FUT`)

### Intraday 1-Minute OHLCV

- **Source**: Any provider — Zerodha, Fyers, Upstox, or your own data
- **Format**: ZIP containing one or more CSV files with 1-minute candles
- **Required columns**: `timestamp` (epoch seconds or ISO datetime), `symbol`, `open`, `high`, `low`, `close`
- **Optional columns**: `exchange` (defaults to `NSE`), `volume`, `oi`
- **Note**: Column names are matched flexibly and case-insensitively

---

## Step 3 — Upload Your Data

For each data type you want to use:

1. Click **Choose File** in the appropriate upload card
2. Select your `.zip` file
3. Click **Upload & Import**
4. Wait for the green success message

```
┌───────────────────────────────────────────────────────────┐
│  🗃 CM Bhavcopy (Equity)                                    │
│                                                            │
│  NSE Cash Market daily bhavcopy ZIP. Contains             │
│  SYMBOL, OPEN, HIGH, LOW, CLOSE, VOLUME data.             │
│                                                            │
│  [📁 cm15APR2024bhav.csv.zip     ]                        │
│  [        ⬆ Upload & Import        ]                       │
│                                                            │
│  ✅ Import successful — 2,065 rows | 1,532 symbols        │
│     Range: 15 Apr 2024, 15:30 IST                         │
└───────────────────────────────────────────────────────────┘
```

**Upload constraints:**

| Constraint          | Default       | Override (env var)            |
|---------------------|---------------|-------------------------------|
| File type           | `.zip` only   | —                             |
| Maximum file size   | 200 MB        | `REPLAY_MAX_ZIP_SIZE_MB=500`  |
| Files inside ZIP    | `.csv`, `.txt` only | —                        |
| Zip-slip protection | Enforced      | —                             |
| Duplicate data      | Upserted (safe to re-upload) | —               |

**After upload, the response shows:**

| Field            | Meaning                                       |
|------------------|-----------------------------------------------|
| `rows_upserted`  | Total OHLCV candles written to DuckDB         |
| `symbols_count`  | Number of unique symbols imported             |
| `min_timestamp`  | Earliest data timestamp (IST)                 |
| `max_timestamp`  | Latest data timestamp (IST)                   |
| `errors`         | Per-file warnings (expand to see details)     |

---

## Step 4 — Configure the Replay Session

In the **Replay Controller** section:

```
┌──────────────────────────────────────────────────────────────────┐
│  ▶ Replay Controller                                              │
│                                                                  │
│  Status: STOPPED                                                 │
│                                                                  │
│  Start Date/Time: [2024-04-15T09:15]                            │
│  End Date/Time:   [2024-04-19T15:30]                            │
│  Speed:           [60x (1 hr/sec)   ▼]                          │
│                   [  ⚡ Configure   ]                             │
│                                                                  │
│  [▶ Start] [⏸ Pause] [⏹ Stop]   ──────────────────── Seek      │
└──────────────────────────────────────────────────────────────────┘
```

### Speed Reference

| Speed setting   | Market time per real second | When to use                         |
|-----------------|----------------------------|--------------------------------------|
| `1x`            | 1 minute / second          | Step-through debugging, precision    |
| `5x`            | 5 minutes / second         | Watching entry/exit mechanics        |
| `10x`           | 10 minutes / second        | Half-day review                      |
| `30x`           | 30 minutes / second        | Full-day review (fits in ~25 s real) |
| `60x`           | 1 hour / second            | Multi-day, fast review               |
| `300x`          | 5 hours / second           | Multi-week, very fast sweep          |

### Configuration fields

| Field          | Format                   | Example               |
|----------------|--------------------------|------------------------|
| Start Date     | `datetime-local` picker  | `2024-04-15T09:15`    |
| End Date       | `datetime-local` picker  | `2024-04-19T15:30`    |
| Speed          | Dropdown                 | `60x (1 hr/sec)`      |

After filling in the fields, click **Configure**. The controller displays the
configured range and speed below the controls.

---

## Step 5 — Set Price Source to Replay

In the **Paper Trading Price Source** card at the top of the page:

1. Click **🎞️ Replay Data** button
2. The button becomes active (filled style)

```
┌─────────────────────────────────────────────────────────────────┐
│  📡 Paper Trading Price Source                                   │
│                                                                 │
│  Controls which price feed the sandbox uses for order           │
│  fills and MTM.                                                 │
│                                                                 │
│  [ 📡 Live Quotes ]   [● 🎞️ Replay Data ]                      │
└─────────────────────────────────────────────────────────────────┘
```

> ⚠️ **Warning banner**: If you set the price source to Replay but the replay
> clock is not yet running, a warning appears:
>
> ```
> ⚠ Price source is set to Replay but the replay clock is STOPPED.
>   Orders will remain pending until you configure a date range and press Start.
> ```

---

## Step 6 — Enable Analyzer Mode

If not already enabled, navigate to `/analyzer` and turn on **Analyzer Mode**.

The Replay price source only takes effect when Analyzer Mode is ON. Without it,
all orders go to your live broker regardless of the price source setting.

---

## Step 7 — Start the Replay Clock

Click **▶ Start** in the Replay Controller.

```
Status: RUNNING  🕐 15 Apr 2024, 09:15:00 IST
```

When running:
- The clock advances by `speed × 1 minute` every real second
- The status area refreshes every second showing the current replay timestamp
- The price-source card shows: *"Replay running — quotes sourced from DuckDB at 15 Apr 2024, 09:15 IST"*

---

## Step 8 — Place Orders in Sandbox

With Analyzer Mode ON and Replay running, place orders exactly as you would for
live trading. The sandbox will fill them using historical prices from DuckDB.

### Using TradingView webhook

Send your usual webhook payload — no change needed. Orders are routed to sandbox
automatically when Analyzer Mode is on.

### Using the Python SDK

```python
from openalgo import api

client = api(
    api_key="YOUR_API_KEY",
    host="http://127.0.0.1:5000"
)

# This order will fill at the replay price for the current replay timestamp
response = client.place_order(
    symbol="NIFTY28MAR24FUT",
    exchange="NFO",
    action="BUY",
    quantity=50,
    price_type="MARKET",
    product="NRML",
    strategy="ReplayTest"
)
print(response)
# {'status': 'success', 'orderid': 'SB-20240415-001', ...}
```

### Using the REST API directly

```bash
curl -X POST http://127.0.0.1:5000/api/v1/placeorder \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "YOUR_API_KEY",
    "strategy": "ReplayTest",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": "100",
    "pricetype": "MARKET",
    "product": "MIS"
  }'
```

---

## Step 9 — Monitor MTM and Positions

While the replay clock runs, the sandbox MTM updates at each tick using the
closest historical price. Check positions at `/sandbox` or via:

```bash
curl -X POST http://127.0.0.1:5000/api/v1/positionbook \
  -H "Content-Type: application/json" \
  -d '{"apikey": "YOUR_API_KEY"}'
```

---

## Step 10 — Pause, Seek, and Stop

| Action  | Effect                                                                   |
|---------|--------------------------------------------------------------------------|
| **Pause**   | Freeze the clock. Existing positions stay open with last known price |
| **Resume**  | Continue from the paused timestamp                                   |
| **Seek**    | Drag the slider to jump to any timestamp within the configured range |
| **Stop**    | Stop and reset clock to start timestamp. Positions remain open       |

> **Note**: Stopping replay does NOT auto-close positions. You must manually
> close them or use the "Reset Sandbox Account" option on the Analyzer page.

---

## Complete End-to-End Example

### Scenario: Replay NIFTY expiry week (15–19 Apr 2024)

**1. Download data**

```
cm15APR2024bhav.csv.zip  ← NSE equity daily
cm16APR2024bhav.csv.zip
cm17APR2024bhav.csv.zip
cm18APR2024bhav.csv.zip
cm19APR2024bhav.csv.zip

fo15APR2024bhav.csv.zip  ← NSE F&O daily
fo16APR2024bhav.csv.zip
fo17APR2024bhav.csv.zip
fo18APR2024bhav.csv.zip
fo19APR2024bhav.csv.zip
```

**2. Upload all ZIPs** — upload each one through the CM Bhavcopy and FO Bhavcopy
cards on the Replay Data Manager page.

After uploading 5 CM ZIPs you should see:
```
✅ Import successful — 10,325 rows | 1,532 symbols
   Range: 15 Apr 2024, 15:30 IST — 19 Apr 2024, 15:30 IST
```

**3. Configure replay**

```
Start: 2024-04-15T09:15
End:   2024-04-19T15:30
Speed: 60x
```

Click **Configure**.

**4. Set price source → 🎞️ Replay Data**

**5. Enable Analyzer Mode** at `/analyzer`

**6. Click ▶ Start**

**7. Place a trade**

```python
client.place_order(
    symbol="NIFTY25APR2422500CE",
    exchange="NFO",
    action="BUY",
    quantity=50,
    price_type="MARKET",
    product="NRML",
    strategy="ExpiryTest"
)
```

**8. Watch MTM update** as the clock advances through the expiry week.

**9. Close position** when the replay clock reaches your desired exit point:

```python
client.close_position(
    symbol="NIFTY25APR2422500CE",
    exchange="NFO",
    product="NRML"
)
```

---

## Quote Resolution Details

When the sandbox needs a price for a symbol during replay, the **ReplayQuoteProvider**
looks up data in this order:

```
1. 1-Minute candle (interval='1m')
   → Find the candle at or nearest BEFORE the current replay timestamp
   → LTP = candle close price

2. Daily bhavcopy (interval='D')  [fallback if no 1m data]
   → Find the daily close for the same trading date

3. No data found
   → Returns None
   → Order remains PENDING — sandbox logs a warning
   → Order will fill when data becomes available at a later timestamp,
     or can be cancelled manually
```

### What this means in practice

| Data uploaded | Behaviour |
|---------------|-----------|
| Only CM/FO daily bhavcopies | Prices update once per day at market close (15:30 IST). Good enough for strategy-level P&L testing. |
| 1-Minute OHLCV | Prices update every minute tick. Full intraday simulation possible. |
| Both (daily + intraday) | Intraday data takes priority; daily is the fallback for symbols without 1m data. |

---

## API Reference (Quick Summary)

All endpoints require browser session authentication (same cookie used by the UI).

### Upload

```
POST /replay/api/upload
Content-Type: multipart/form-data

file        = <ZIP file>
upload_type = CM_BHAVCOPY | FO_BHAVCOPY | INTRADAY_1M
```

### Replay Control

```
GET  /replay/api/replay/status
POST /replay/api/replay/config   {"start_ts": 1713160200, "end_ts": 1713505800, "speed": 60}
POST /replay/api/replay/start
POST /replay/api/replay/pause
POST /replay/api/replay/seek     {"target_ts": 1713210000}
POST /replay/api/replay/stop
```

### Paper Price Source

```
GET  /settings/paper-price-source
POST /settings/paper-price-source   {"source": "REPLAY"}
```

See [API Reference — Replay Endpoints](../../api/replay/README.md) for full request/response schemas.

---

## Limitations

| Limitation | Details |
|------------|---------|
| No holiday skip | The clock advances continuously. Prices simply become unavailable during non-trading hours. |
| No partial fills | All market orders fill completely at the replay price (same as live sandbox). |
| No slippage model | Fill price = candle close from data. |
| In-memory clock | Replay state resets on server restart. Re-configure after restart. |
| Daily data granularity | Without 1m data, price changes only once per day. Limit orders based on intraday movements will not behave realistically. |
| No synthetic intraday | Intraday candles are not generated from daily data. Upload 1m ZIPs for intraday simulation. |

---

## Troubleshooting

### "Orders remain PENDING and don't fill"

- Check that Analyzer Mode is enabled at `/analyzer`
- Check that Price Source is set to **🎞️ Replay Data** on the Replay page
- Check that the replay clock is **RUNNING** (not stopped or paused)
- Check that you have uploaded data for the symbol and date range you configured

### "No CSV files found in ZIP"

- Make sure the ZIP contains `.csv` or `.txt` files directly (not nested in subfolders)
- Confirm the ZIP is not password-protected

### "File too large"

- Default limit is 200 MB. Set `REPLAY_MAX_ZIP_SIZE_MB=500` in `.env` and restart

### "Missing required columns"

The importer tries several column name variants automatically. If import fails,
open the CSV and check that `SYMBOL`, `OPEN`, `HIGH`, `LOW`, `CLOSE` columns exist
(any case).

### "Import successful but wrong timestamps"

NSE bhavcopy timestamps are set to **15:30 IST** of the trade date. This is
correct for daily data. The date is parsed from the `TIMESTAMP` column in the CSV,
or from the filename if the column is missing.

### "Replay state lost after restart"

Replay state is in-memory. After a server restart:
1. Navigate to `/sandbox/replay`
2. Re-configure start/end/speed
3. Re-set price source to Replay if needed
4. Press Start

Your uploaded DuckDB data is **persisted** on disk — you do not need to re-upload.

---

## Related Modules

| Module | Link |
|--------|------|
| Analyzer Mode (Sandbox Testing) | [Module 15](../15-analyzer-mode/README.md) |
| Historify — Historical Data Management | [Design Doc](../../design/08-historify/README.md) |
| Replay API Reference | [API Docs](../../api/replay/README.md) |
| Paper Price Source API | [API Docs](../../api/settings/paper-price-source.md) |
