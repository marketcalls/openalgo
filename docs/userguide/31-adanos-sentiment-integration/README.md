# 31 - Adanos Sentiment Integration

## Introduction

Adanos is a stock sentiment API that tracks discussion intensity and directional bias across:

- Reddit
- X.com
- Financial news
- Polymarket

For OpenAlgo users, Adanos fits best as an **external confirmation layer**. Instead of replacing your charting, screening, or execution stack, it helps you decide whether a symbol deserves action right now.

Common use cases:

- confirm TradingView breakout alerts before sending them to OpenAlgo
- prioritize ChartInk screener hits by buzz and bullish ratio
- gate Python strategies so they only trade when sentiment confirms the setup
- rank a daily watchlist by social, news, and prediction-market activity

## Why This Is Useful For Traders

Most trading signals answer **"is there a setup?"**

Adanos adds a second question:

**"is there real attention and directional conviction behind this setup?"**

That matters because many alerts are technically correct but poorly timed:

- breakouts without participation fade quickly
- oversold reversals can keep drifting without renewed attention
- multiple candidates may look similar on price, but one symbol can clearly dominate discussion and conviction

Adanos is useful when you want to:

- avoid low-attention trades
- rank multiple candidates fast
- confirm discretionary entries with external sentiment
- combine technical setups with non-price signal strength

## Coverage Notes

Coverage depends on the symbol and market.

Adanos is strongest on names that generate consistent discussion in social media, news, or prediction markets. Before automating live execution, validate the symbols you care about and decide how your workflow should behave when coverage is weak or missing.

Recommended approach:

1. test a few target symbols manually
2. define minimum thresholds for buzz and bullish ratio
3. decide whether to skip, downgrade, or alert on symbols with partial coverage

## Available Metrics

You can pull source-level data from the current Adanos API and compute your own composite rules inside OpenAlgo.

Common fields:

| Field | Meaning |
|-------|---------|
| `buzz_score` | Discussion intensity / activity score |
| `bullish_pct` | Percentage of tracked discussion or markets leaning bullish |
| `mentions` | Number of tracked mentions on Reddit, X.com, or news |
| `trade_count` | Polymarket trade activity |
| `trend` | Recent momentum label such as `rising`, `stable`, or `falling` |

Useful local composites:

- `average_buzz`
- `bullish_avg`
- `conviction`
- `source_alignment`

## Adanos Endpoints

Adanos exposes separate stock endpoints per source. Start with the stock detail endpoints because they already include `buzz_score`, `bullish_pct`, and `trend`.

```bash
curl -H "X-API-Key: YOUR_ADANOS_API_KEY" \
  "https://api.adanos.org/reddit/stocks/v1/stock/INFY?days=7"

curl -H "X-API-Key: YOUR_ADANOS_API_KEY" \
  "https://api.adanos.org/x/stocks/v1/stock/INFY?days=7"

curl -H "X-API-Key: YOUR_ADANOS_API_KEY" \
  "https://api.adanos.org/news/stocks/v1/stock/INFY?days=7"

curl -H "X-API-Key: YOUR_ADANOS_API_KEY" \
  "https://api.adanos.org/polymarket/stocks/v1/stock/INFY?days=7"
```

Useful links:

- API docs: [api.adanos.org/docs](https://api.adanos.org/docs)
- Get API key: [adanos.org/reddit-stock-sentiment#api](https://adanos.org/reddit-stock-sentiment#api)

## Integration Patterns For OpenAlgo

### TradingView + Adanos Confirmation

Flow:

1. TradingView generates an alert
2. A small Python middleware checks Adanos
3. Only qualifying signals are forwarded to OpenAlgo
4. OpenAlgo places the order

Good when you want to:

- reject weak breakouts
- require rising attention before entry
- trade only when sentiment confirms the technical setup

See also: [Module 16 - TradingView Integration](../16-tradingview-integration/README.md)

### ChartInk + Adanos Prioritization

Flow:

1. ChartInk finds symbols matching your screener
2. A Python filter queries Adanos for those symbols
3. Symbols are ranked or filtered by buzz / bullish ratio / trend
4. Only the strongest candidates reach OpenAlgo

Good when you want to:

- reduce noisy screener results
- rank many symbols quickly
- place only the top one or two candidates per scan

See also: [Module 18 - ChartInk Integration](../18-chartink-integration/README.md)

### Python Strategy Sentiment Gate

Flow:

1. Your Python strategy generates a trade candidate
2. The strategy fetches Adanos source signals
3. A local composite rule decides whether to trade
4. OpenAlgo executes only approved orders

Good when you want to:

- keep all logic in Python
- combine price action with external signal quality
- make your trade filters easy to backtest and refine

See also: [Module 20 - Python Strategies](../20-python-strategies/README.md)

## Example Strategy Gate

OpenAlgo example:

- [examples/python/adanos_sentiment_gate.py](../../../examples/python/adanos_sentiment_gate.py)

The example does four things:

1. fetches source-level signals from Adanos
2. computes `average_buzz`, `bullish_avg`, and `source_alignment`
3. decides whether the symbol is tradable
4. sends the order to OpenAlgo only if the sentiment gate passes

## Practical Rules To Start With

Example starting thresholds:

- `average_buzz >= 60`
- `bullish_avg >= 55`
- skip symbols with multiple `falling` sources
- skip symbols with very wide disagreement across sources

These are not universal rules. They are a practical starting point for tuning.

## Best Practices

- Treat Adanos as a confirmation and prioritization layer, not a standalone execution trigger.
- Start with dry-run logging before forwarding orders.
- Log both approved and rejected trades so you can measure the filter's value.
- Make your strategy resilient to partial coverage and API errors.
- Revisit thresholds by symbol group, because large caps and small caps behave differently.

## Summary

OpenAlgo gives you execution, automation, and strategy control. Adanos adds external signal intelligence.

That combination is useful when you want to trade **setups with attention, conviction, and momentum**, not just setups that happen to match a chart condition.
