# Data Fetching

## OpenAlgo (Indian Markets)

### Setup

```python
import os
from dotenv import find_dotenv, load_dotenv
from openalgo import api

load_dotenv(find_dotenv(), override=False)

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)
```

### Historical Data

```python
from datetime import datetime, timedelta

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365)

df = client.history(
    symbol="SBIN",
    exchange="NSE",           # NSE, BSE, NFO, MCX, NSE_INDEX
    interval="D",             # D, 1h, 30m, 15m, 10m, 5m, 3m, 1m
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
)
```

### Data Source: Broker API vs DuckDB

The `history()` method supports a `source` parameter to choose between broker API and local DuckDB/Historify database:

```python
# Default: fetch from broker API (rate-limited ~3 req/s)
df = client.history(
    symbol="SBIN", exchange="NSE", interval="D",
    start_date="2024-01-01", end_date="2025-01-01",
    source="api",
)

# Fetch from OpenAlgo DuckDB/Historify database (no rate limit)
df = client.history(
    symbol="SBIN", exchange="NSE", interval="D",
    start_date="2024-01-01", end_date="2025-01-01",
    source="db",
)

# Custom intervals only available with source="db"
df = client.history(
    symbol="SBIN", exchange="NSE", interval="3m",
    start_date="2025-01-01", end_date="2025-02-01",
    source="db",
)
```

| Source | Description | Rate Limit | Intervals |
|--------|-------------|-----------|-----------|
| `"api"` | Broker API (default) | ~3 req/s | `1m`, `3m`, `5m`, `10m`, `15m`, `30m`, `1h`, `D` |
| `"db"` | DuckDB/Historify local DB | None | All standard + any custom interval (see below) |

#### DuckDB Custom Intervals (source="db" only)

DuckDB stores only `1m` and `D` data physically. All other intervals are computed on-the-fly via SQL aggregation with exchange-aware candle alignment (e.g., NSE candles align to 9:15 AM market open).

**Intraday** (aggregated from 1m data):

| Category | Examples | Format |
|----------|----------|--------|
| Standard minutes | `1m`, `5m`, `15m`, `30m` | `{N}m` |
| Custom minutes | `2m`, `3m`, `4m`, `6m`, `7m`, `10m`, `12m`, `20m`, `25m`, `45m` | `{N}m` |
| Standard hours | `1h` | `{N}h` |
| Custom hours | `2h`, `3h`, `4h`, `6h` | `{N}h` |

**Daily-based** (aggregated from D data):

| Category | Examples | Format |
|----------|----------|--------|
| Daily | `D` | `D` |
| Weekly | `W`, `2W`, `3W` | `{N}W` |
| Monthly | `M`, `2M`, `3M`, `6M` | `{N}M` |
| Quarterly | `Q`, `2Q` | `{N}Q` |
| Yearly | `Y`, `2Y` | `{N}Y` |

**Not supported with source="db"**: seconds intervals (`1s`, `5s`), custom days (`2D`, `3D`)

#### When to Use Each Source

Use `source="db"` for:
- Backtesting and bulk data analysis (no rate limiting)
- Scanner dashboards with many symbols
- Custom interval aggregation (`2m`, `3m`, `4h`, `W`, `M`, `Q`, `Y`)
- Multi-timeframe analysis with non-standard intervals

Use `source="api"` (default) for:
- Real-time or near real-time data
- When DuckDB database is not configured

### Data Normalization (ALWAYS DO THIS)

```python
import pandas as pd

if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)
df = df.sort_index()
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)

close = df["close"]
high = df["high"]
low = df["low"]
open_ = df["open"]
volume = df["volume"]
```

### Available Intervals

```python
response = client.intervals()
# Returns: {"minutes": ["1m", "3m", "5m", "10m", "15m", "30m"],
#           "hours": ["1h"], "days": ["D"], "weeks": [], "months": []}
```

### Real-Time Quotes

```python
# Single symbol
quote = client.quotes(symbol="SBIN", exchange="NSE")
# Returns: {open, high, low, ltp, bid, ask, prev_close, volume}

# Multiple symbols
quotes = client.multiquotes(symbols=[
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"},
])
```

### Market Depth (Level 5)

```python
depth = client.depth(symbol="SBIN", exchange="NSE")
# Returns: {open, high, low, ltp, ltq, prev_close, volume, oi,
#           totalbuyqty, totalsellqty,
#           asks: [{price, quantity}, ...],  # 5 levels
#           bids: [{price, quantity}, ...]}  # 5 levels
```

### Exchange Codes

| Exchange | Code | Example Symbols |
|----------|------|-----------------|
| NSE Equity | `NSE` | SBIN, RELIANCE, INFY, TCS |
| BSE Equity | `BSE` | SBIN, RELIANCE |
| NSE Index | `NSE_INDEX` | NIFTY, BANKNIFTY, FINNIFTY |
| NSE F&O | `NFO` | NIFTY30DEC25FUT, NIFTY30DEC2526000CE |
| MCX | `MCX` | CRUDEOIL, GOLD, SILVER |

---

## yfinance (US/Global Markets)

### Setup

```python
import yfinance as yf
```

No API key needed.

### Historical Data

```python
df = yf.download("AAPL", start="2024-01-01", end="2025-01-01", auto_adjust=True)
df.columns = df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
df.columns = [c.lower() for c in df.columns]
```

### Common US Symbols

| Symbol | Name |
|--------|------|
| AAPL | Apple |
| MSFT | Microsoft |
| GOOGL | Alphabet |
| AMZN | Amazon |
| SPY | S&P 500 ETF |
| QQQ | Nasdaq 100 ETF |
| ^GSPC | S&P 500 Index |

---

## Market Detection Pattern

```python
INDIAN_EXCHANGES = {"NSE", "BSE", "NFO", "MCX", "NSE_INDEX"}

def fetch_data(symbol, exchange="NSE", interval="D", days=365, source="api"):
    if exchange in INDIAN_EXCHANGES:
        # Use OpenAlgo
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        df = client.history(
            symbol=symbol, exchange=exchange, interval=interval,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            source=source,
        )
    else:
        # Use yfinance
        df = yf.download(symbol, period=f"{days}d", auto_adjust=True)
        df.columns = df.columns.droplevel(1) if isinstance(df.columns, pd.MultiIndex) else df.columns
        df.columns = [c.lower() for c in df.columns]

    # Normalize
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    else:
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    return df
```

---

## Option Chain Data

```python
chain = client.optionchain(
    underlying="NIFTY",
    exchange="NSE_INDEX",
    expiry_date="30DEC25",
    strike_count=10          # Optional: number of strikes around ATM
)
# Returns: {underlying, underlying_ltp, atm_strike, expiry_date,
#           chain: [{strike, ce: {symbol, label, ltp, bid, ask, ...},
#                             pe: {symbol, label, ltp, bid, ask, ...}}, ...]}
```

---

## Option Greeks

`client.optiongreeks()` returns delta, gamma, theta, vega, rho plus implied volatility for any option contract. Use it for options-aware indicators and scanners: IV smile/skew charts, delta-neutral filters, theta-decay dashboards, IV percentile analysis.

```python
greeks = client.optiongreeks(
    symbol="NIFTY25NOV2526000CE",   # OpenAlgo option symbol
    exchange="NFO",
    interest_rate=0.00,              # Risk-free rate (annualized)
    underlying_symbol="NIFTY",       # Optional: spot reference
    underlying_exchange="NSE_INDEX",
)
# Returns: {status, symbol, strike, option_type, option_price, spot_price,
#           implied_volatility, days_to_expiry, expiry_date, interest_rate,
#           greeks: {delta, gamma, theta, vega, rho}}

iv = greeks["implied_volatility"]
delta = greeks["greeks"]["delta"]
```

### Expiry Dates

```python
response = client.expiry(symbol="NIFTY", exchange="NFO", instrumenttype="options")
# Returns: {status, data: ["10-JUL-25", "17-JUL-25", ...], message}
```

### Pattern: IV Smile Across the Chain

Combine `optionchain()` + `optiongreeks()` to build IV-based analytics:

```python
chain = client.optionchain(
    underlying="NIFTY", exchange="NSE_INDEX",
    expiry_date="30DEC25", strike_count=10,
)

rows = []
for entry in chain["chain"]:
    for side in ("ce", "pe"):
        leg = entry.get(side)
        if not leg:
            continue
        g = client.optiongreeks(symbol=leg["symbol"], exchange="NFO")
        if g.get("status") == "success":
            rows.append({
                "strike": entry["strike"],
                "type": side.upper(),
                "iv": g["implied_volatility"],
                "delta": g["greeks"]["delta"],
                "theta": g["greeks"]["theta"],
            })

iv_df = pd.DataFrame(rows)   # plot iv vs strike per side for the IV smile
```

Note: `optiongreeks()` is one HTTP call per contract — for full-chain sweeps, batch only the strikes you need (e.g., `strike_count=10`) and cache results in scanners.
