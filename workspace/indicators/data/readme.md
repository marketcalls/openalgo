# data/

Cached OHLCV pulled from the broker.

Cache deliberately: history endpoints are rate-limited and a repeated backtest
should not re-fetch. Include symbol, exchange, interval and date range in the
filename so a stale cache is obvious.

Never committed — market data does not belong in git.
