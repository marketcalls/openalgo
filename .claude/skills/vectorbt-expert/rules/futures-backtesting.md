---
name: futures-backtesting
description: Futures backtesting with lot sizes, value sizing, and contract specifications
metadata:
  tags: futures, lot-size, nifty, banknifty, contracts, value-sizing
---

# Futures Backtesting (Lot Size)

For NIFTY/BANKNIFTY futures, use `min_size` and `size_granularity` set to the lot size, and `size_type="value"` for fixed capital deployment:

```python
lot_size = 65  # NIFTY Futures lot size (effective 31 Dec 2025)
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    init_cash=30_00_000,        # 30 lakh
    size=20_00_000,             # Deploy 20L of 30L per trade
    size_type="value",
    direction="longonly",
    fees=0.0003,                # 0.03% for futures
    min_size=lot_size,          # Minimum = 1 lot
    size_granularity=lot_size,  # Round to lot multiples
    freq="1D" if timeframe == "D" else "1h",
)
```

## Index Futures & Options Lot Sizes (SEBI Revised, Effective 31 Dec 2025)

SEBI mandates contract value between Rs 15-20 lakh. Lot sizes are periodically revised.

| Index | Exchange | Lot Size | OpenAlgo Symbol |
|-------|----------|----------|-----------------|
| Nifty 50 | NFO | 65 | NIFTY |
| Nifty Bank | NFO | 30 | BANKNIFTY |
| Nifty Financial Services | NFO | 60 | FINNIFTY |
| Nifty Midcap Select | NFO | 120 | MIDCPNIFTY |
| Nifty Next 50 | NFO | 25 | NIFTYNXT50 |
| BSE Sensex | BFO | 20 | SENSEX |
| BSE Bankex | BFO | 30 | BANKEX |
| BSE Sensex 50 | BFO | 70 | SENSEX50 |

**Historical lot sizes (for backtesting older periods):**

| Index | Before Jan 2025 | Jan-Jun 2025 | Jun-Dec 2025 | From 31 Dec 2025 |
|-------|-----------------|--------------|--------------|-------------------|
| Nifty 50 | 50 | 75 | 75 | 65 |
| Nifty Bank | 25 | 30 | 35 | 30 |
| Nifty Financial Services | 40 | 65 | 65 | 60 |
| Nifty Midcap Select | 75 | 120 | 140 | 120 |

**Stock Futures:** Lot sizes vary per stock (see exchange LOTSIZE.csv or OpenAlgo instruments API).

## Futures Fee Structure

| Component | Rate |
|-----------|------|
| Brokerage | Flat or 0.01-0.03% |
| STT | 0.0125% on sell side (futures) |
| Exchange Txn | 0.00173% (NSE) |
| GST | 18% on (brokerage + exchange txn) |
| SEBI Fee | 0.0001% |
| Stamp Duty | 0.002% (buy side) |

For a simplified model, use `fees=0.0003` (0.03%) which approximates total round-trip costs for futures.

See [indian-market-costs](./indian-market-costs.md) for the complete fee model.
