---
name: pitfalls
description: Common backtesting pitfalls and mistakes - lookahead bias, survivorship bias, overfitting, data snooping
metadata:
  tags: pitfalls, lookahead-bias, survivorship-bias, overfitting, data-snooping, curve-fitting, mistakes
---

# Common Backtesting Pitfalls

## 1. Lookahead Bias

**What:** Using future information to make trading decisions.
**How it happens:** Forgetting to shift indicators or using current-bar data for entry signals.

```python
# BAD: Uses today's Donchian channel to decide today's trade
entries = close > upper_band

# GOOD: Uses yesterday's channel (shift by 1)
entries = close > upper_band.shift(1)
```

**Prevention:**
- Always `.shift(1)` indicator levels used for comparison
- Signals generated at bar N should only use data from bars 0 to N-1
- Test: if removing the last bar changes any signal except the last, you have lookahead

## 2. Survivorship Bias

**What:** Only backtesting stocks that exist today, ignoring delisted/failed companies.
**How it happens:** Using current NSE stock list to select backtest universe.

**Prevention:**
- Use index constituents as of each historical date (not current constituents)
- Include delisted stocks in multi-asset backtests where possible
- Be skeptical of strategies tested only on NIFTY 50 stocks (they survived for a reason)

## 3. Overfitting / Curve Fitting

**What:** Optimizing parameters so precisely that they only work on historical data.
**Signs:**
- Optimal parameters are isolated spikes on the heatmap (no broad stable region)
- Small parameter changes cause large performance swings
- In-sample performance is excellent but out-of-sample is poor
- Strategy needs many parameters to work (more than 3-4 is suspicious)

**Prevention:**
- Use walk-forward analysis (see [walk-forward](./walk-forward.md))
- Prefer parameter regions that are broadly profitable (wide green zones on heatmap)
- Test on multiple symbols - a robust strategy works across many stocks
- Keep strategy logic simple - fewer parameters = less room to overfit

## 4. Data Snooping

**What:** Testing many strategies on the same data until one works by chance.
**How it happens:** Testing 100 indicator combinations and picking the best one.

**Prevention:**
- Have a hypothesis BEFORE testing (don't just try random combinations)
- Apply Bonferroni correction: if you test N strategies, divide your confidence level by N
- Validate winning strategies on completely different time periods or instruments
- Reserve a hold-out dataset that you NEVER optimize on

## 5. Unrealistic Transaction Costs

**What:** Ignoring or underestimating fees, slippage, and market impact.
**Impact:** A profitable backtest becomes unprofitable with real costs.

```python
# BAD: No fees
pf = vbt.Portfolio.from_signals(close, entries, exits, init_cash=1_000_000)

# GOOD: Realistic Indian delivery equity fees
pf = vbt.Portfolio.from_signals(
    close, entries, exits,
    fees=0.00111,           # 0.111% per side (STT + statutory)
    fixed_fees=20,          # Rs 20 per order
    slippage=0.0005,        # 0.05% slippage
    init_cash=1_000_000,
    freq="1D",
)
```

See [indian-market-costs](./indian-market-costs.md) for the complete Indian market fee model.

## 6. Ignoring Slippage and Market Impact

**What:** Assuming you always get the exact close price.
**Reality:** Large orders move the market; illiquid stocks have wide bid-ask spreads.

**Prevention:**
- Add `slippage=0.0005` (0.05%) minimum for liquid large-caps
- Add `slippage=0.001` (0.1%) for mid/small-caps
- For futures, `slippage=0.0002` (0.02%) is reasonable for NIFTY/BANKNIFTY
- Volume filter: skip signals on days with abnormally low volume

## 7. Insufficient Trade Count

**What:** Drawing conclusions from too few trades.

| Trade Count | Reliability |
|-------------|-------------|
| < 20 | Statistically meaningless |
| 20-50 | Low confidence |
| 50-100 | Moderate confidence |
| 100-200 | Good confidence |
| > 200 | High confidence |

**Prevention:**
- Require minimum 30+ trades for any statistical conclusion
- Use longer backtest periods or higher-frequency data to get more trades
- Be especially skeptical of "100% win rate with 5 trades"

## 8. Ignoring Regime Changes

**What:** Assuming market conditions stay the same forever.
**Reality:** Strategies that work in trending markets fail in sideways markets and vice versa.

**Prevention:**
- Test across multiple market regimes (2008 crash, 2020 COVID, 2021 bull run)
- Add regime detection filters (ADX for trend strength, VIX for volatility)
- Monitor rolling Sharpe ratio - if it degrades, the regime may have changed

## 9. Not Accounting for Indian Market Rules

**What:** Ignoring India-specific trading rules.

| Rule | Impact |
|------|--------|
| T+1 settlement for equities | Can't sell delivery shares on same day |
| No short selling in CNC/delivery | Short strategies only work intraday or in F&O |
| Circuit limits (5%, 10%, 20%) | Price can be locked; orders won't execute |
| Market hours 9:15-15:30 IST | After-hours signals can't be acted on until next day |
| Expiry day (last Thursday) | Extreme volatility, unusual behavior |
| Pre-open auction 9:00-9:08 | Prices can gap significantly from previous close |

## 10. Selection Bias in Symbol Choice

**What:** Only backtesting on symbols you already know performed well.

**Prevention:**
- Test on randomly selected symbols from the exchange
- Test on the full NIFTY 50 or NIFTY 500 universe
- Include at least some losers/flat performers in your test universe
- The strategy should work on the average stock, not just cherry-picked winners

## Checklist Before Going Live

- [ ] Walk-forward analysis shows positive OOS returns
- [ ] Strategy tested on 3+ different symbols
- [ ] Realistic transaction costs included (market-specific fee model)
- [ ] Slippage included (0.05% minimum)
- [ ] At least 50+ trades in backtest
- [ ] No lookahead bias (all indicators shifted properly)
- [ ] Parameter heatmap shows broad stable region (not isolated spike)
- [ ] Drawdown is acceptable (can you stomach a 20% drawdown?)
- [ ] Strategy logic is explainable (not a random combination of indicators)
- [ ] Paper traded for at least 1 month before real capital
