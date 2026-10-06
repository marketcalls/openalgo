---
name: us-market-costs
description: Realistic US market transaction cost modeling - commission, SEC fee, FINRA TAF, exchange fees
metadata:
  tags: fees, costs, us-market, sec, finra, commission, stocks, options, futures
---

# US Market Transaction Costs

All fee calculations are based on standard US brokerage pricing with per-share commission and regulatory fees.

## Fee Summary by Segment

| Component | US Stocks (Fixed) | US Stocks (Lite) | US Options | US Futures (E-mini) | US Futures (Micro) |
|-----------|-------------------|------------------|------------|---------------------|--------------------|
| Commission | $0.005/share (min $1) | $0 | $0.65/contract | $0.85/contract | $0.25/contract |
| Exchange Fees | Included in fixed | Included | $0.10–$0.65/contract | $1.38/contract (CME) | ~$0.30/contract |
| Clearing Fees | Included | Included | $0.02/contract (OCC) | Included | Included |
| SEC Fee | ~$8.00/million (sell) | ~$8.00/million (sell) | ~$8.00/million (sell) | N/A | N/A |
| FINRA TAF | $0.000195/share (sell) | $0.000195/share (sell) | $0.00279/contract (sell) | N/A | N/A |

## Simplified Percentage Fees for VectorBT

VectorBT's `fees` parameter is a percentage applied to both buy and sell turnover. We convert the total round-trip cost into an equivalent per-side percentage.

### US Stocks - Per-Share Commission

Total all-in cost for a $10,000 trade (100 shares × $100):
- Commission: $0.005 × 100 = $0.50 → min $1.00
- SEC fee (sell only): $10,000 × 0.000008 = $0.08
- FINRA TAF (sell only): 100 × $0.000195 = $0.02
- Round trip: $1.00 (buy) + $1.00 (sell) + $0.08 + $0.02 = $2.10
- Per side: ~0.01% of trade value

```python
# US Stocks (Per-Share Commission): ~0.01% fees + $1 fixed per order
fees = 0.0001            # 0.01% per side (SEC + FINRA regulatory)
fixed_fees = 1.0         # $1 minimum commission per order

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=100_000,    # $100K USD
    freq="1D",
    min_size=1,
    size_granularity=1,
)
```

### US Stocks - Commission-Free

Commission-free for US exchange-listed stocks and ETFs during regular trading hours.
Only regulatory fees (SEC + FINRA TAF) apply.

```python
# US Stocks (Commission-Free): ~0.001% fees, no fixed fees
fees = 0.00001           # ~0.001% per side (SEC + FINRA only)
fixed_fees = 0           # No commission

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=100_000,
    freq="1D",
    min_size=1,
    size_granularity=1,
)
```

### US Options

Per-contract pricing. Standard: $0.65/contract + exchange + clearing + regulatory.
Total all-in: ~$1.00–$1.50 per contract depending on exchange.

```python
# US Options (Per-Contract Commission): ~0.5% fees + $0.65 fixed per order
# Note: Options fees are high relative to premium price.
# For a $5.00 premium × 100 shares = $500 notional:
#   Commission: $0.65, Exchange: ~$0.30, OCC: $0.02, Regulatory: ~$0.01
#   Total: ~$0.98 per contract = ~0.2% of notional
fees = 0.002             # ~0.2% per side (exchange + clearing + regulatory)
fixed_fees = 0.65        # $0.65 per contract commission

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=50_000,
    freq="1D",
)
```

### US Futures - E-mini (ES, NQ, YM, RTY)

Per-contract pricing. All-in cost for 1 ES contract:
Execution $0.85 + CME exchange $1.38 + Regulatory $0.02 = $2.25

```python
# US Futures E-mini: ~$2.25 all-in per contract per side
# For ES at ~5000 × $50 multiplier = $250,000 notional:
#   $2.25 / $250,000 = ~0.0009% per side
fees = 0.000009          # ~0.0009% per side
fixed_fees = 2.25        # $2.25 all-in per contract per side

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    size=1,               # 1 contract
    size_type="amount",
    init_cash=50_000,
    freq="1D",
)
```

### US Futures - Micro (MES, MNQ, MYM, M2K)

Per-contract pricing. Total all-in: ~$0.55–$0.70 per contract.

```python
# US Micro Futures: ~$0.55 all-in per contract per side
# For MES at ~5000 × $5 multiplier = $25,000 notional:
#   $0.55 / $25,000 = ~0.0022% per side
fees = 0.00002           # ~0.002% per side
fixed_fees = 0.55        # $0.55 all-in per contract per side

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    size=1,
    size_type="amount",
    init_cash=10_000,
    freq="1D",
)
```

## Quick Reference: Default Fee Constants

Use these constants at the top of every US market backtest script:

```python
# --- Fee Constants (US Market Standard) ---
# US Stocks - Per-Share Commission
FEES_US_STOCK_PRO = 0.0001           # 0.01% per side (regulatory)
FIXED_FEES_US_STOCK_PRO = 1.0        # $1.00 minimum per order

# US Stocks - Commission-Free
FEES_US_STOCK_LITE = 0.00001         # ~0.001% per side (regulatory only)
FIXED_FEES_US_STOCK_LITE = 0         # No commission

# US Options - Per-Contract Commission
FEES_US_OPTIONS = 0.002              # ~0.2% per side (exchange + clearing)
FIXED_FEES_US_OPTIONS = 0.65         # $0.65 per contract

# US Futures - E-mini (ES, NQ, YM, RTY)
FEES_US_FUTURES_EMINI = 0.000009     # ~0.0009% per side
FIXED_FEES_US_FUTURES_EMINI = 2.25   # $2.25 all-in per contract

# US Futures - Micro (MES, MNQ, MYM, M2K)
FEES_US_FUTURES_MICRO = 0.00002      # ~0.002% per side
FIXED_FEES_US_FUTURES_MICRO = 0.55   # $0.55 all-in per contract
```

## Popular US Futures Contract Specifications

| Contract | Symbol | Exchange | Multiplier | Tick Size | Tick Value | Margin (~) |
|----------|--------|----------|------------|-----------|------------|------------|
| E-mini S&P 500 | ES | CME | $50 | 0.25 | $12.50 | ~$12,650 |
| E-mini NASDAQ 100 | NQ | CME | $20 | 0.25 | $5.00 | ~$17,600 |
| E-mini Dow | YM | CBOT | $5 | 1.0 | $5.00 | ~$9,500 |
| E-mini Russell 2000 | RTY | CME | $50 | 0.10 | $5.00 | ~$7,150 |
| Micro E-mini S&P | MES | CME | $5 | 0.25 | $1.25 | ~$1,265 |
| Micro E-mini NASDAQ | MNQ | CME | $2 | 0.25 | $0.50 | ~$1,760 |
| Crude Oil | CL | NYMEX | $1,000 | 0.01 | $10.00 | ~$6,600 |
| Gold | GC | COMEX | $100 | 0.10 | $10.00 | ~$11,000 |
| Micro Gold | MGC | COMEX | $10 | 0.10 | $1.00 | ~$1,100 |

## Data Source for US Markets

Use `yfinance` for US market data:

```python
import yfinance as yf

# US Stocks
df = yf.download("AAPL", start="2022-01-01", end="2025-01-01", interval="1d")

# US ETFs
df = yf.download("SPY", start="2022-01-01", end="2025-01-01", interval="1d")

# Benchmark: S&P 500
benchmark = yf.download("^GSPC", start="2022-01-01", end="2025-01-01", interval="1d")
# or use SPY ETF as benchmark
```

## Regulatory Fee Details

### SEC Section 31 Fee (Sell-Side Only)
- Rate: ~$8.00 per million dollars of sell-side principal
- Applies to: All exchange-traded securities (stocks + options)
- Who pays: Sell-side of every trade
- Typical impact: ~0.0008% on sell value

### FINRA Trading Activity Fee (Sell-Side Only)
- Stocks: $0.000195 per share sold (max $9.79 per trade)
- Options: $0.00279 per contract sold
- Who pays: Sell-side of every trade

### OCC Clearing Fee (Options Only)
- Rate: $0.02 per contract (as of Jan 2025)
- Applies to: All options transactions cleared through OCC

## Best Practices

- For US stock backtests with per-share commission, the $1 minimum commission dominates costs for small trades
- For large trades (>200 shares of $100+ stocks), per-share commission becomes significant
- Commission-free brokers are effectively zero-cost for stocks but still have regulatory fees
- US futures costs are extremely low as a percentage of notional - ideal for high-frequency strategies
- Options costs are relatively high as a percentage of premium - factor this into spread strategies
- When in doubt, use per-share commission pricing as a conservative baseline
- Always use `min_size=1, size_granularity=1` for stocks to avoid fractional shares
- Default US benchmark: S&P 500 via `^GSPC` (index) or `SPY` (ETF) from yfinance
