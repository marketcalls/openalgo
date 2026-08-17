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
2. Create `workspace/indicators/scanners/` (`mkdir -p`)
3. Write the script to `workspace/indicators/scanners/{scan_type}_{watchlist}.py`
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

## Verify before calling it done

A scanner that returns nothing looks identical to a scanner that is broken.
Prove it works before trusting a result:

- [ ] **Seed a known positive.** Pick a symbol you have already confirmed meets the condition (chart it first) and check the scan finds it. An empty result set is only meaningful once you have seen a non-empty one.
- [ ] **Invert the condition.** Flip `rsi < 30` to `rsi > 30` and confirm the result count roughly complements. If both return zero, the data is not loading and the condition is never the problem.
- [ ] **Count the universe actually scanned**, not the universe requested. Log `scanned / requested`. Symbols dropped for missing data, a wrong exchange, or a delisted ticker vanish silently and quietly shrink the result set.
- [ ] **Check the last bar is today's.** Scanning on stale history produces yesterday's signals with no error. Print `df.index[-1]` for one symbol and compare against the current session.
- [ ] **Confirm no NaN leakage.** A symbol with fewer bars than the indicator period yields NaN, and `NaN < 30` is `False` — so short-history symbols are silently excluded rather than flagged. Report them separately.
- [ ] **Exchange is correct per symbol.** Index underlyings use `NSE_INDEX`/`BSE_INDEX`; stocks use `NSE`/`BSE`. Passing the wrong one returns no data rather than an error. See `docs/prompt/symbol-format.md`.

**Lookahead check:** a scan run at 11:00 must not use the completed daily
candle. If the result changes when you re-run the same scan against a
date-truncated dataset, the condition is reading a bar that had not closed.

## Where to write files

Default location is **`workspace/indicators/scanners/`** in the repo root. Create it
immediately before writing — it does not exist on a fresh clone:

```bash
mkdir -p workspace/indicators/scanners
```

Name the file `<indicator>_<symbol>_<interval>.py` so the folder stays
scannable as it grows, e.g. `workspace/indicators/scanners/rsi_oversold_nifty50.py`.

Rendered output goes to `workspace/indicators/output/` under the same stem, keeping the
script and its artifact associated without cluttering the source folder:

```
workspace/indicators/scanners/rsi_oversold_nifty50.py  ->  workspace/indicators/output/rsi_oversold_nifty50.csv
```

**If the user names a different folder, use it** and keep the same layout
beneath it. Note that only `workspace/` is gitignored (except its readme), so
writing elsewhere inside the repo produces tracked files — mention that before
doing it.

Run from the repo root:

```bash
uv run --group analysis python workspace/indicators/scanners/rsi_oversold_nifty50.py
```
