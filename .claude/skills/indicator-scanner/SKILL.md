---
name: indicator-scanner
description: Scan multiple symbols with indicator conditions. Find stocks matching RSI oversold, EMA crossovers, Supertrend signals, and custom filter combinations.
argument-hint: "[scan-type] [watchlist]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

Create a multi-symbol indicator scanner that screens stocks by technical conditions.

## Arguments

Parse `$ARGUMENTS` as: scan-type watchlist

- `$0` = scan type (e.g., rsi-oversold, rsi-overbought, ema-crossover, supertrend-buy, supertrend-sell, macd-crossover, adx-trending, custom). Default: rsi-oversold
- `$1` = watchlist (e.g., nifty50, banknifty, custom). Default: nifty50

If no arguments, ask the user what they want to scan for.

## Instructions

1. Read the indicator-expert rules for reference
2. Create `scanners/{scan_type}/` directory (on-demand)
3. Create `{scan_type}_scanner.py`
4. The script must:
   - Load `.env` from project root
   - Define the watchlist (predefined or custom)
   - Fetch data for each symbol via `client.history()`
   - Compute indicator(s) using `openalgo.ta`
   - Check the scan condition
   - Print results as a formatted table
   - Save results to CSV
   - Optionally get real-time LTP via `client.quotes()` for current values

### Scan Logic Pattern

```python
results = []
for symbol in watchlist:
    df = fetch_data(symbol, exchange, interval)
    close = df["close"]

    # Compute indicator
    rsi = ta.rsi(close, 14)
    current_rsi = rsi.iloc[-1]

    # Check condition
    if current_rsi < 30:  # RSI oversold
        results.append({
            "symbol": symbol,
            "ltp": close.iloc[-1],
            "rsi": current_rsi,
            "signal": "OVERSOLD",
        })

# Print table
df_results = pd.DataFrame(results)
print(df_results.to_string(index=False))
df_results.to_csv(script_dir / f"{scan_type}_results.csv", index=False)
```

## Predefined Scan Types

| Scan Type | Condition | Indicator |
|-----------|-----------|-----------|
| `rsi-oversold` | RSI(14) < 30 | RSI |
| `rsi-overbought` | RSI(14) > 70 | RSI |
| `ema-crossover` | EMA(10) crossed above EMA(20) in last 3 bars | EMA |
| `ema-crossunder` | EMA(10) crossed below EMA(20) in last 3 bars | EMA |
| `supertrend-buy` | Supertrend direction changed to -1 (uptrend) | Supertrend |
| `supertrend-sell` | Supertrend direction changed to 1 (downtrend) | Supertrend |
| `macd-crossover` | MACD crossed above Signal in last 3 bars | MACD |
| `adx-trending` | ADX > 25 (strong trend) | ADX |
| `bb-squeeze` | Bollinger Width at 20-bar low (volatility squeeze) | Bollinger |
| `volume-spike` | Volume > 2x 20-day average | Volume |
| `custom` | Ask user for conditions | Any |

## Predefined Watchlists

### NIFTY 50 (nifty50)
```python
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA",
    "TCS", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TECHM",
    "TITAN", "ULTRACEMCO", "UPL", "WIPRO",
]
```

### Bank NIFTY (banknifty)
```python
BANKNIFTY = [
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
    "INDUSINDBK", "BANKBARODA", "FEDERALBNK", "PNB", "IDFCFIRSTB",
    "BANDHANBNK", "AUBANK",
]
```

## Output Format

```
Symbol     LTP      RSI(14)  Signal
------     ---      -------  ------
SBIN       769.60   28.4     OVERSOLD
TATASTEEL  142.30   25.1     OVERSOLD
COALINDIA  385.00   29.7     OVERSOLD

Scan: RSI Oversold (<30) | Watchlist: NIFTY 50 | Date: 2025-02-28
Found 3 / 50 symbols matching condition
Results saved to: scanners/rsi_oversold/rsi_oversold_results.csv
```

## Example Usage

`/indicator-scanner rsi-oversold nifty50`
`/indicator-scanner ema-crossover banknifty`
`/indicator-scanner supertrend-buy nifty50`
`/indicator-scanner volume-spike nifty50`
`/indicator-scanner custom`
