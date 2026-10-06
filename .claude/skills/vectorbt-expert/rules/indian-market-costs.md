---
name: indian-market-costs
description: Realistic Indian market transaction cost modeling - STT, stamp duty, GST, SEBI fees, exchange charges
metadata:
  tags: fees, costs, stt, stamp-duty, gst, sebi, brokerage, transaction-costs, indian-market
---

# Indian Market Transaction Costs

All fee calculations are based on standard Indian brokerage and regulatory charges. These are the standard costs used across all backtesting scripts.

## Fee Summary by Segment

Based on standard charges (Buy=1000, Sell=1000, Qty=500, Turnover=10L per side):

| Component | Intraday Equity | Delivery Equity | F&O Futures | F&O Options |
|-----------|----------------|-----------------|-------------|-------------|
| Brokerage | Rs 20/order | Rs 0 (free) | Rs 20/order | Rs 20/order |
| STT | 0.025% (sell) | 0.1% (both) | 0.02% (sell) | 0.1% (sell) |
| Exchange Txn | 0.00307% | 0.00307% | 0.00183% | 0.03553% |
| GST | 18% on (brokerage + exchange txn) | 18% on exchange txn | 18% on (brokerage + exchange txn) | 18% on (brokerage + exchange txn) |
| SEBI Charges | 0.0001% | 0.0001% | 0.0001% | 0.0001% |
| Stamp Duty | 0.003% (buy) | 0.015% (buy) | 0.002% (buy) | 0.003% (buy) |

## Simplified Percentage Fees for VectorBT

VectorBT's `fees` parameter is a percentage applied to both buy and sell turnover. We convert the total round-trip cost into an equivalent per-side percentage:

### Intraday Equity

Total charges on 10L turnover = Rs 224.61
Plus brokerage: Rs 20 buy + Rs 20 sell = Rs 40

```python
# Intraday Equity: ~0.0225% fees + Rs 20 fixed per order
fees = 0.000225          # 0.0225% per side (statutory charges)
fixed_fees = 20          # Rs 20 brokerage per order (buy + sell)

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=1_000_000,
    freq="5min",
)
```

### Delivery Equity (CNC)

Total charges on 10L turnover = Rs 1112.41
Brokerage: Rs 0 (many brokers offer free delivery).
We add Rs 20/order for conservative modeling.

```python
# Delivery Equity: ~0.111% fees + Rs 20 fixed per order
fees = 0.00111          # 0.111% per side (STT + statutory)
fixed_fees = 20         # Rs 20 per order (conservative estimate)

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=1_000_000,
    freq="1D",
)
```

### F&O Futures

Total charges on 10L turnover = Rs 179.97
Plus brokerage: Rs 20 buy + Rs 20 sell = Rs 40

```python
# F&O Futures: ~0.018% fees + Rs 20 fixed per order
fees = 0.00018          # 0.018% per side (statutory charges)
fixed_fees = 20         # Rs 20 brokerage per order

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=30_00_000,
    freq="1D",
)
```

### F&O Options

Total charges on 10L turnover = Rs 982.63
Plus brokerage: Rs 20 buy + Rs 20 sell = Rs 40

```python
# F&O Options: ~0.098% fees + Rs 20 fixed per order
fees = 0.00098          # 0.098% per side (statutory charges)
fixed_fees = 20         # Rs 20 brokerage per order

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=5_00_000,
    freq="1D",
)
```

## Quick Reference: Default Fee Constants

Use these constants at the top of every backtest script:

```python
# --- Fee Constants (Indian Market Standard) ---
# Intraday Equity
FEES_INTRADAY_EQ = 0.000225       # 0.0225% per side
FIXED_FEES_INTRADAY_EQ = 20       # Rs 20 per order

# Delivery Equity (CNC)
FEES_DELIVERY_EQ = 0.00111        # 0.111% per side
FIXED_FEES_DELIVERY_EQ = 20       # Rs 20 per order

# F&O Futures
FEES_FUTURES = 0.00018            # 0.018% per side
FIXED_FEES_FUTURES = 20           # Rs 20 per order

# F&O Options
FEES_OPTIONS = 0.00098            # 0.098% per side
FIXED_FEES_OPTIONS = 20           # Rs 20 per order
```

## Detailed Breakdown Formulas

For users who need exact per-trade cost calculation:

```python
def calculate_charges_intraday_eq(buy_value, sell_value):
    """Calculate exact charges for intraday equity."""
    turnover = buy_value + sell_value
    brokerage = min(20, 0.0003 * buy_value) + min(20, 0.0003 * sell_value)  # 0.03% or Rs 20, whichever is lower
    stt = 0.00025 * sell_value                    # 0.025% on sell side
    exchange_txn = 0.0000307 * turnover           # 0.00307% on total
    gst = 0.18 * (brokerage + exchange_txn)       # 18% on brokerage + exchange txn
    sebi = 0.000001 * turnover                    # 0.0001% on total
    stamp = 0.00003 * buy_value                   # 0.003% on buy side
    total = brokerage + stt + exchange_txn + gst + sebi + stamp
    return total

def calculate_charges_delivery_eq(buy_value, sell_value):
    """Calculate exact charges for delivery equity."""
    turnover = buy_value + sell_value
    brokerage = 0                                  # Free delivery (common with discount brokers)
    stt = 0.001 * turnover                         # 0.1% on both sides
    exchange_txn = 0.0000307 * turnover            # 0.00307% on total
    gst = 0.18 * (brokerage + exchange_txn)        # 18% on brokerage + exchange txn
    sebi = 0.000001 * turnover                     # 0.0001% on total
    stamp = 0.00015 * buy_value                    # 0.015% on buy side
    total = brokerage + stt + exchange_txn + gst + sebi + stamp
    return total

def calculate_charges_futures(buy_value, sell_value):
    """Calculate exact charges for F&O Futures."""
    turnover = buy_value + sell_value
    brokerage = 20 + 20                            # Rs 20 per order
    stt = 0.0002 * sell_value                      # 0.02% on sell side (futures)
    exchange_txn = 0.0000183 * turnover            # 0.00183% on total
    gst = 0.18 * (brokerage + exchange_txn)        # 18% on brokerage + exchange txn
    sebi = 0.000001 * turnover                     # 0.0001% on total
    stamp = 0.00002 * buy_value                    # 0.002% on buy side
    total = brokerage + stt + exchange_txn + gst + sebi + stamp
    return total

def calculate_charges_options(buy_value, sell_value):
    """Calculate exact charges for F&O Options."""
    turnover = buy_value + sell_value
    brokerage = 20 + 20                            # Rs 20 per order
    stt = 0.001 * sell_value                       # 0.1% on sell side (options)
    exchange_txn = 0.0003553 * turnover            # 0.03553% on total
    gst = 0.18 * (brokerage + exchange_txn)        # 18% on brokerage + exchange txn
    sebi = 0.000001 * turnover                     # 0.0001% on total
    stamp = 0.00003 * buy_value                    # 0.003% on buy side
    total = brokerage + stt + exchange_txn + gst + sebi + stamp
    return total
```

## Best Practices

- Always use `fixed_fees=20` for the per-order brokerage component
- For delivery equity backtests, the STT (0.1% both sides) dominates costs - never ignore it
- For intraday, STT is much lower (0.025% sell only) making frequent trading more viable
- For futures, costs are lowest - ideal for high-frequency strategies
- Options have high STT (0.1% sell) making selling strategies expensive on exit
- When in doubt, use higher fees - it is better to underestimate returns than overestimate
- The `fees` + `fixed_fees` combination in VectorBT accurately models percentage + flat fee structures
