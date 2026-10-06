---
name: data-fetching
description: Fetching historical market data - OpenAlgo (India), yfinance (US/Global), CCXT (Crypto) with python-dotenv configuration
metadata:
  tags: data, openalgo, yfinance, ccxt, history, download, intervals, exchanges, dotenv, env
---

# Data Fetching

## Environment Setup (All Markets)

Every backtest script must load API keys from the single root `.env` using `python-dotenv` + `find_dotenv()`. Never hardcode API keys.

```python
import os
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from dotenv import find_dotenv, load_dotenv

# Load .env from project root (find_dotenv walks up from script dir)
script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)
```

A `.env.sample` is provided at the project root. Copy it and fill in your keys:

```bash
cp .env.sample .env
```

---

## 1. Indian Markets — OpenAlgo (Primary)

Requires: `OPENALGO_API_KEY` and `OPENALGO_HOST` in `.env`.

```python
from openalgo import api

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
)

end_date = datetime.now().date()
start_date = end_date - timedelta(days=365 * 3)

df = client.history(
    symbol="SBIN",
    exchange="NSE",
    interval="D",
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
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
    source="api",
)

# Fetch from OpenAlgo DuckDB/Historify database (no rate limit)
df = client.history(
    symbol="SBIN", exchange="NSE", interval="D",
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
    source="db",
)

# Custom intervals only available with source="db"
df = client.history(
    symbol="SBIN", exchange="NSE", interval="3m",
    start_date=start_date.strftime("%Y-%m-%d"),
    end_date=end_date.strftime("%Y-%m-%d"),
    source="db",
)
```

| Source | Description | Rate Limit | Intervals |
|--------|-------------|-----------|-----------|
| `"api"` | Broker API (default) | ~3 req/s | `1m`, `3m`, `5m`, `10m`, `15m`, `30m`, `1h`, `D` |
| `"db"` | DuckDB/Historify local DB | None | All standard + any custom interval (see below) |

Use `source="db"` for:
- Backtesting and bulk data analysis (no rate limiting)
- Multi-symbol scans without hitting rate limits
- Custom interval aggregation (`2m`, `3m`, `4h`, `W`, `M`, `Q`, `Y`)

Use `source="api"` (default) for:
- Real-time or near real-time data
- When DuckDB database is not configured

### OpenAlgo Intervals (source="api")

| Interval | Code |
|----------|------|
| 1 minute | `1m` |
| 3 minutes | `3m` |
| 5 minutes | `5m` |
| 10 minutes | `10m` |
| 15 minutes | `15m` |
| 30 minutes | `30m` |
| 1 hour | `1h` |
| Daily | `D` |

### DuckDB Custom Intervals (source="db")

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

### OpenAlgo Exchange Codes

| Exchange | Code | Description |
|----------|------|-------------|
| NSE | `NSE` | National Stock Exchange equities |
| BSE | `BSE` | Bombay Stock Exchange equities |
| NFO | `NFO` | NSE Futures and Options |
| BFO | `BFO` | BSE Futures and Options |
| CDS | `CDS` | NSE Currency Derivatives |
| BCD | `BCD` | BSE Currency Derivatives |
| MCX | `MCX` | Multi Commodity Exchange |
| NSE_INDEX | `NSE_INDEX` | NSE Indices |
| BSE_INDEX | `BSE_INDEX` | BSE Indices |

### OpenAlgo Symbol Format

- **Equity**: `SBIN`, `RELIANCE`, `INFY`, `HDFCBANK`
- **Futures**: `BANKNIFTY24APR24FUT` (BaseSymbol + ExpiryDate + FUT)
- **Options**: `NIFTY28MAR2420800CE` (BaseSymbol + ExpiryDate + StrikePrice + CE/PE)
- **Index**: `NIFTY`, `BANKNIFTY`, `FINNIFTY` (with exchange=NSE_INDEX)

### Indian Market Benchmarks

| Benchmark | Source | Symbol |
|-----------|--------|--------|
| NIFTY 50 (primary) | OpenAlgo | `symbol="NIFTY", exchange="NSE_INDEX"` |
| NIFTY 50 (fallback) | yfinance | `^NSEI` |

---

## 2. US Markets — yfinance (No API Key Needed)

yfinance uses public Yahoo Finance data. No API key or `.env` config required.

```python
import yfinance as yf

# US Stock
df = yf.download("AAPL", start="2022-01-01", end="2025-01-01",
                  interval="1d", auto_adjust=True, multi_level_index=False)
close = df["Close"]

# US ETF
df = yf.download("SPY", start="2022-01-01", end="2025-01-01",
                  interval="1d", auto_adjust=True, multi_level_index=False)
```

### yfinance Ticker Format

| Asset | Ticker | Example |
|-------|--------|---------|
| US Stock | `AAPL`, `MSFT`, `TSLA` | Direct ticker |
| US ETF | `SPY`, `QQQ`, `IWM` | Direct ticker |
| Indian Stock | `RELIANCE.NS`, `SBIN.NS` | Ticker + `.NS` (NSE) or `.BO` (BSE) |
| Crypto | `BTC-USD`, `ETH-USD` | Symbol + `-USD` |
| US Index | `^GSPC` (S&P 500), `^NDX` (NASDAQ 100) | `^` prefix |
| Indian Index | `^NSEI` (NIFTY 50), `^BSESN` (Sensex) | `^` prefix |

### yfinance Intervals

| Interval | Code | Max History |
|----------|------|-------------|
| 1 minute | `1m` | 7 days |
| 2 minutes | `2m` | 60 days |
| 5 minutes | `5m` | 60 days |
| 15 minutes | `15m` | 60 days |
| 30 minutes | `30m` | 60 days |
| 1 hour | `1h` | 730 days |
| 1 day | `1d` | Unlimited |
| 1 week | `1wk` | Unlimited |
| 1 month | `1mo` | Unlimited |

### US Market Benchmarks

| Benchmark | Ticker | Description |
|-----------|--------|-------------|
| S&P 500 (index) | `^GSPC` | Broad US market |
| S&P 500 (ETF) | `SPY` | Tradeable ETF |
| NASDAQ 100 | `^NDX` or `QQQ` | Tech-heavy |
| Dow Jones | `^DJI` or `DIA` | Blue chips |
| Russell 2000 | `^RUT` or `IWM` | Small caps |

### Multi-Asset US Data Fetch

```python
import yfinance as yf
import pandas as pd

tickers = ["AAPL", "MSFT", "GOOGL", "AMZN"]
df = yf.download(tickers, start="2022-01-01", end="2025-01-01",
                 interval="1d", auto_adjust=True, multi_level_index=False)
# For multi-ticker, columns are multi-level: ("Close", "AAPL"), etc.
# With multi_level_index=False on single ticker it flattens
```

---

## 3. Crypto Markets — yfinance or CCXT

### yfinance (Simple — No API Key)

```python
import yfinance as yf

# Bitcoin daily
df = yf.download("BTC-USD", start="2022-01-01", end="2025-01-01",
                  interval="1d", auto_adjust=True, multi_level_index=False)
close = df["Close"]

# Ethereum daily
df = yf.download("ETH-USD", start="2022-01-01", end="2025-01-01",
                  interval="1d", auto_adjust=True, multi_level_index=False)
```

### CCXT (Higher Resolution — Optional API Key)

For intraday crypto data or exchange-specific pairs. Public OHLCV data does NOT require API keys. Only private endpoints (account, orders) need keys.

```python
# pip install ccxt
import ccxt
import pandas as pd

# Public data - no API key needed
exchange = ccxt.binance()

# Fetch OHLCV
ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=1000)
df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
df = df.set_index("timestamp")
close = df["close"]
```

For authenticated CCXT (account data):

```python
# Authenticated — requires CRYPTO_API_KEY and CRYPTO_SECRET_KEY in .env
exchange = ccxt.binance({
    "apiKey": os.getenv("CRYPTO_API_KEY"),
    "secret": os.getenv("CRYPTO_SECRET_KEY"),
})
```

### Crypto Tickers

| Pair | yfinance | CCXT |
|------|----------|----------------|
| BTC/USD | `BTC-USD` | `BTC/USDT` |
| ETH/USD | `ETH-USD` | `ETH/USDT` |
| SOL/USD | `SOL-USD` | `SOL/USDT` |
| BNB/USD | `BNB-USD` | `BNB/USDT` |

### Crypto Benchmarks

| Benchmark | Ticker | Source |
|-----------|--------|--------|
| Bitcoin | `BTC-USD` | yfinance |
| Ethereum | `ETH-USD` | yfinance |

---

## Data Normalization (All Markets)

Always normalize the datetime index after fetching from any source:

```python
# OpenAlgo returns "timestamp" column or datetime index
if "timestamp" in df.columns:
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
else:
    df.index = pd.to_datetime(df.index)

df = df.sort_index()

# Remove timezone info (VectorBT works best with tz-naive)
if df.index.tz is not None:
    df.index = df.index.tz_convert(None)
```

For yfinance, column names are capitalized (`Close`, `Open`, `High`, `Low`, `Volume`). Normalize if needed:

```python
# Lowercase column names to match OpenAlgo convention
df.columns = df.columns.str.lower()
close = df["close"]
```

## Multiple Timeframe Data Fetch

```python
# Daily data (OpenAlgo)
df_daily = client.history(symbol="RELIANCE", exchange="NSE", interval="D",
                          start_date="2024-01-01", end_date="2025-02-25")

# 5-minute intraday data (OpenAlgo)
df_5m = client.history(symbol="RELIANCE", exchange="NSE", interval="5m",
                       start_date="2025-02-01", end_date="2025-02-25")

# Custom intervals via DuckDB (source="db")
df_weekly = client.history(symbol="RELIANCE", exchange="NSE", interval="W",
                           start_date="2024-01-01", end_date="2025-02-25",
                           source="db")
df_3m = client.history(symbol="RELIANCE", exchange="NSE", interval="3m",
                       start_date="2025-02-01", end_date="2025-02-25",
                       source="db")
```

## Multi-Asset Data Fetch (OpenAlgo)

```python
symbols = ["RELIANCE", "HDFCBANK", "INFY", "TCS"]
dfs = {}
for sym in symbols:
    # Use source="db" for bulk fetching (no rate limit)
    dfs[sym] = client.history(symbol=sym, exchange="NSE", interval="D",
                              start_date="2024-01-01", end_date="2025-02-25",
                              source="db")

close_prices = pd.DataFrame({sym: dfs[sym]["close"] for sym in symbols})
```

## Market Selection Guide

| If the user says... | Market | Data Source | Fee Model |
|---------------------|--------|-------------|-----------|
| NSE, BSE, NIFTY, BANKNIFTY, Indian stock names | India | OpenAlgo | [indian-market-costs](./indian-market-costs.md) |
| AAPL, SPY, S&P 500, NASDAQ, US stock names | US | yfinance | [us-market-costs](./us-market-costs.md) |
| BTC, ETH, crypto, USDT | Crypto | yfinance or CCXT | [crypto-market-costs](./crypto-market-costs.md) |
| DuckDB path provided | India | DuckDB direct | [indian-market-costs](./indian-market-costs.md) |

## 3b. DuckDB Direct Loading (Fastest — No API)

For backtesting with local DuckDB databases. No API key or network needed. Supports two formats:

### Custom DuckDB

```python
import duckdb
import pandas as pd

DB_PATH = r"path/to/market_data.duckdb"
con = duckdb.connect(DB_PATH, read_only=True)
df = con.execute("""
    SELECT date, time, open, high, low, close, volume
    FROM ohlcv WHERE symbol = 'SBIN' ORDER BY date, time
""").fetchdf()
con.close()

df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["date", "time"])
close = df["close"]
```

### OpenAlgo Historify DuckDB

```python
import duckdb
import pandas as pd

HISTORIFY_DB = r"path/to/openalgo/db/historify.duckdb"
con = duckdb.connect(HISTORIFY_DB, read_only=True)
df = con.execute("""
    SELECT timestamp, open, high, low, close, volume
    FROM market_data
    WHERE symbol = 'SBIN' AND exchange = 'NSE' AND interval = '1m'
    ORDER BY timestamp
""").fetchdf()
con.close()

df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
df = df.set_index("datetime").sort_index()
df = df.drop(columns=["timestamp"])
close = df["close"]
```

See [duckdb-data](./duckdb-data.md) for full reference including auto-detection, resampling, and multi-symbol loading.

---

## 4. Custom Data Provider (Extensible)

Users can plug in any data source as long as it returns a pandas DataFrame with a DatetimeIndex and OHLCV columns. Follow this pattern:

### Adding a Custom Data Provider

1. **Add API key(s) to `.env`:**

```
# Custom data provider
CUSTOM_API_KEY=your_key_here
CUSTOM_API_URL=https://api.example.com
```

2. **Create a fetch function** that returns a normalized DataFrame:

```python
import os
import requests
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from pathlib import Path

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

def fetch_custom_data(symbol, start_date, end_date, interval="1d"):
    """Fetch data from a custom provider.

    Must return a DataFrame with:
    - DatetimeIndex (tz-naive)
    - Columns: open, high, low, close, volume (lowercase)
    """
    api_key = os.getenv("CUSTOM_API_KEY")
    base_url = os.getenv("CUSTOM_API_URL")

    # --- Replace this block with your provider's API call ---
    response = requests.get(f"{base_url}/history", params={
        "symbol": symbol,
        "from": start_date,
        "to": end_date,
        "interval": interval,
        "apikey": api_key,
    })
    data = response.json()
    df = pd.DataFrame(data)
    # --- End custom block ---

    # Normalize to standard format
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    df.columns = df.columns.str.lower()

    return df
```

3. **Use it in backtest scripts** the same way as any other source:

```python
df = fetch_custom_data("AAPL", "2022-01-01", "2025-01-01")
close = df["close"]
```

### Custom Provider Checklist

- [ ] API keys loaded from `.env` via `python-dotenv` (never hardcoded)
- [ ] Returns DataFrame with DatetimeIndex (tz-naive)
- [ ] Columns lowercase: `open`, `high`, `low`, `close`, `volume`
- [ ] Data sorted by index (`df.sort_index()`)
- [ ] Timezone stripped (`tz_convert(None)`)
- [ ] Add your provider's API key variable to `.env.sample`

### Example: Alpaca Markets

```python
import os
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from pathlib import Path

# pip install alpaca-trade-api
from alpaca_trade_api.rest import REST

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

alpaca = REST(
    key_id=os.getenv("ALPACA_API_KEY"),
    secret_key=os.getenv("ALPACA_SECRET_KEY"),
    base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
)

bars = alpaca.get_bars("AAPL", "1Day", start="2022-01-01", end="2025-01-01").df
bars.columns = bars.columns.str.lower()
bars.index = bars.index.tz_convert(None)
close = bars["close"]
```

### Example: Twelve Data

```python
import os
import pandas as pd
from dotenv import find_dotenv, load_dotenv
from pathlib import Path

# pip install twelvedata
from twelvedata import TDClient

script_dir = Path(__file__).resolve().parent
load_dotenv(find_dotenv(), override=False)

td = TDClient(apikey=os.getenv("TWELVEDATA_API_KEY"))
ts = td.time_series(symbol="AAPL", interval="1day", start_date="2022-01-01",
                    end_date="2025-01-01", outputsize=5000).as_pandas()
ts = ts.sort_index()
ts.columns = ts.columns.str.lower()
close = ts["close"]
```

---

## NEVER Do This

- Never hardcode API keys in scripts — always use `.env` + `python-dotenv`
- Never hardcode dates without making them configurable
- Never skip `sort_index()` — data must be chronologically ordered
- Never ignore timezone handling — mismatch causes silent alignment errors
- Never fetch more intraday data than the source provides (see interval tables above)
- Never use yfinance for Indian market backtests when OpenAlgo is available (OpenAlgo has more accurate data)
