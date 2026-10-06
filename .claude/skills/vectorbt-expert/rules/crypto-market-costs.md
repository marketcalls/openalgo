---
name: crypto-market-costs
description: Realistic crypto market transaction cost modeling - spot, USDT-M futures, COIN-M futures, maker/taker fees, funding rates
metadata:
  tags: fees, costs, crypto, spot, futures, maker, taker, funding-rate, bitcoin, ethereum
---

# Crypto Market Transaction Costs

All fee calculations are based on standard crypto exchange fee tiers (base/regular tier). These defaults represent the most common fee structure across major exchanges.

## Fee Summary by Segment

| Component | Spot (Base) | Spot (BNB Discount) | USDT-M Futures | COIN-M Futures |
|-----------|-------------|---------------------|----------------|----------------|
| Maker Fee | 0.1000% | 0.0750% | 0.0200% | 0.0100% |
| Taker Fee | 0.1000% | 0.0750% | 0.0500% | 0.0500% |
| Funding Rate | N/A | N/A | Variable (~0.01% / 8h) | Variable (~0.01% / 8h) |
| Withdrawal | Varies by coin | Varies by coin | N/A | N/A |

## Simplified Percentage Fees for VectorBT

VectorBT's `fees` parameter is a percentage applied to both buy and sell turnover. Use the taker fee for conservative modeling (market orders).

### Crypto Spot (Base Tier)

Maker and taker both 0.1% at VIP 0. Most backtest fills simulate market orders (taker).

```python
# Crypto Spot (Base Tier): 0.1% taker fee per side
fees = 0.001             # 0.1% per side (taker)
fixed_fees = 0           # No fixed fee on most crypto exchanges

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=10_000,     # $10K USDT
    freq="1D",
    min_size=0,           # Crypto allows fractional units
    size_granularity=0,   # No rounding needed
)
```

### Crypto Spot (BNB Discount)

25% discount when paying fees with BNB. Reduces 0.1% to 0.075%.

```python
# Crypto Spot (Token Discount): 0.075% taker fee per side
fees = 0.00075           # 0.075% per side (taker with BNB)
fixed_fees = 0

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=10_000,
    freq="1D",
    min_size=0,
    size_granularity=0,
)
```

### USDT-Margined Futures

Maker 0.02%, Taker 0.05% at VIP 0. Use taker fee for conservative backtests.

```python
# USDT-M Futures (Taker): 0.05% per side
fees = 0.0005            # 0.05% per side (taker)
fixed_fees = 0

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=10_000,
    freq="1D",
    min_size=0,
    size_granularity=0,
)
```

### USDT-M Futures (Maker Orders)

For strategies using limit orders, the lower maker fee applies.

```python
# USDT-M Futures (Maker): 0.02% per side
fees = 0.0002            # 0.02% per side (maker)
fixed_fees = 0

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=10_000,
    freq="1D",
    min_size=0,
    size_granularity=0,
)
```

### COIN-Margined Futures

Maker 0.01%, Taker 0.05% at VIP 0. Settled in the base cryptocurrency.

```python
# COIN-M Futures (Taker): 0.05% per side
fees = 0.0005            # 0.05% per side (taker)
fixed_fees = 0

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees,
    fixed_fees=fixed_fees,
    init_cash=1.0,        # 1 BTC for BTC-margined
    freq="1D",
    min_size=0,
    size_granularity=0,
)
```

## Quick Reference: Default Fee Constants

Use these constants at the top of every crypto backtest script:

```python
# --- Fee Constants (Crypto Exchange Standard - Base Tier) ---
# Spot Trading
FEES_CRYPTO_SPOT = 0.001             # 0.1% per side (taker)
FEES_CRYPTO_SPOT_BNB = 0.00075      # 0.075% per side (taker with BNB discount)
FEES_CRYPTO_SPOT_MAKER = 0.001      # 0.1% per side (maker)

# USDT-Margined Futures
FEES_CRYPTO_FUTURES_TAKER = 0.0005  # 0.05% per side (taker)
FEES_CRYPTO_FUTURES_MAKER = 0.0002  # 0.02% per side (maker)

# COIN-Margined Futures
FEES_CRYPTO_COINM_TAKER = 0.0005   # 0.05% per side (taker)
FEES_CRYPTO_COINM_MAKER = 0.0001   # 0.01% per side (maker)

# No fixed fees on most crypto exchanges
FIXED_FEES_CRYPTO = 0
```

## Exchange VIP Tier Fee Schedule (Typical)

### Spot Trading

| VIP Level | 30d Volume (USDT) | Maker | Taker | With BNB Maker | With BNB Taker |
|-----------|-------------------|-------|-------|----------------|----------------|
| VIP 0 | < 1M | 0.1000% | 0.1000% | 0.0750% | 0.0750% |
| VIP 1 | >= 1M | 0.0900% | 0.1000% | 0.0675% | 0.0750% |
| VIP 2 | >= 5M | 0.0800% | 0.1000% | 0.0600% | 0.0750% |
| VIP 3 | >= 20M | 0.0420% | 0.0660% | 0.0315% | 0.0495% |
| VIP 4 | >= 100M | 0.0420% | 0.0540% | 0.0315% | 0.0405% |
| VIP 5 | >= 150M | 0.0360% | 0.0480% | 0.0270% | 0.0360% |
| VIP 6 | >= 400M | 0.0300% | 0.0420% | 0.0225% | 0.0315% |
| VIP 7 | >= 800M | 0.0240% | 0.0360% | 0.0180% | 0.0270% |
| VIP 8 | >= 2B | 0.0180% | 0.0300% | 0.0135% | 0.0225% |
| VIP 9 | >= 4B | 0.0120% | 0.0240% | 0.0090% | 0.0180% |

### USDT-M Futures

| VIP Level | 30d Volume (USDT) | Maker | Taker |
|-----------|-------------------|-------|-------|
| VIP 0 | < 5M | 0.0200% | 0.0500% |
| VIP 1 | >= 5M | 0.0160% | 0.0400% |
| VIP 2 | >= 25M | 0.0140% | 0.0350% |
| VIP 3 | >= 100M | 0.0120% | 0.0320% |
| VIP 4 | >= 250M | 0.0100% | 0.0300% |
| VIP 5 | >= 1B | 0.0080% | 0.0270% |
| VIP 6 | >= 5B | 0.0060% | 0.0250% |
| VIP 7 | >= 10B | 0.0040% | 0.0220% |
| VIP 8 | >= 25B | 0.0020% | 0.0200% |
| VIP 9 | >= 50B | 0.0000% | 0.0170% |

## Funding Rate (Futures Only)

Perpetual futures contracts have a **funding rate** exchanged between longs and shorts every 8 hours. This is a hidden cost that significantly impacts longer-duration futures backtests.

### Modeling Funding Rate in VectorBT

Funding rate is NOT modeled by VectorBT's `fees` parameter. For short-term backtests (<1 week), it can be ignored. For longer holding periods, account for it separately:

```python
# Approximate funding rate impact on a futures backtest
FUNDING_RATE = 0.0001      # 0.01% per 8 hours (typical neutral market)
FUNDING_PERIODS_PER_DAY = 3  # Every 8 hours

# For a position held for N days:
# funding_cost = position_value × FUNDING_RATE × FUNDING_PERIODS_PER_DAY × N_days

# Conservative approach: add estimated daily funding to fees
# 0.01% × 3 = 0.03% per day → for daily bars, add to fees
fees_with_funding = 0.0005 + 0.0003  # taker + daily funding estimate

pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=fees_with_funding,  # 0.08% per side (taker + funding)
    fixed_fees=0,
    init_cash=10_000,
    freq="1D",
)
```

### Funding Rate Notes

- **Positive funding rate**: Longs pay shorts (bullish market). Hurts long positions.
- **Negative funding rate**: Shorts pay longs (bearish market). Hurts short positions.
- Typical range: -0.05% to +0.05% per 8h, with 0.01% being the baseline
- In strong trends, funding can reach 0.1%+ per 8h, which is significant
- For backtests with average holding period > 1 day, always consider funding rate impact

## Data Source for Crypto Markets

Use `yfinance` or CCXT for crypto market data:

```python
import yfinance as yf

# Bitcoin (daily)
df = yf.download("BTC-USD", start="2022-01-01", end="2025-01-01", interval="1d")

# Ethereum (daily)
df = yf.download("ETH-USD", start="2022-01-01", end="2025-01-01", interval="1d")

# Benchmark: Bitcoin
benchmark = yf.download("BTC-USD", start="2022-01-01", end="2025-01-01", interval="1d")
```

For higher resolution data or futures data, consider using CCXT:

```python
# pip install ccxt
import ccxt
import pandas as pd

exchange = ccxt.binance()  # or any supported exchange
ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=1000)
df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
df = df.set_index("timestamp")
```

## Crypto-Specific VectorBT Settings

```python
# Crypto allows fractional units - do NOT set min_size=1
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=0.001,              # Crypto spot taker
    fixed_fees=0,
    init_cash=10_000,        # USDT
    size=0.5,                # 50% per trade
    size_type="percent",
    direction="longonly",    # or "both" for spot + short
    freq="1D",
    min_size=0,              # Fractional crypto allowed
    size_granularity=0,      # No rounding
)
```

## Cost Comparison Across Markets

| Market | Segment | Per-Side Fee | Fixed Fee | Round-Trip Cost on $10K |
|--------|---------|-------------|-----------|------------------------|
| India | Delivery Equity | 0.111% | Rs 20 | ~Rs 2,265 (~$27) |
| India | Intraday Equity | 0.0225% | Rs 20 | ~Rs 485 (~$6) |
| India | F&O Futures | 0.018% | Rs 20 | ~Rs 400 (~$5) |
| US (Per-Share) | Stocks | 0.01% | $1.00 | ~$4.10 |
| US (Comm-Free) | Stocks | ~0.001% | $0 | ~$0.20 |
| US | E-mini Futures | ~0.001% | $2.25 | ~$4.52 |
| Crypto | Spot | 0.1% | $0 | ~$20.00 |
| Crypto | Spot (Discounted) | 0.075% | $0 | ~$15.00 |
| Crypto | USDT-M Futures | 0.05% | $0 | ~$10.00 |

## Best Practices

- **Spot trading**: Always use taker fees (0.1%) for conservative backtesting. Most signals result in market orders.
- **Futures**: Model both taker fees AND funding rate for positions held > 1 day
- **Token discount**: Only apply exchange token discounts if you realistically hold them. Use base fees for conservative modeling.
- **Slippage**: Crypto markets can have significant slippage on larger orders. Add `slippage=0.001` (0.1%) for realistic modeling on altcoins or low-liquidity pairs.
- **Fractional units**: Unlike stocks, crypto allows fractional trading. Do NOT set `min_size=1` or `size_granularity=1` for crypto.
- **24/7 markets**: Crypto trades 24/7 - no weekend gaps. Use `freq="1D"` for daily, but note that weekends are trading days.
- **When in doubt**, use spot taker (0.1%) as a safe default for any crypto backtest
- Default crypto benchmark: Bitcoin (`BTC-USD`) from yfinance
