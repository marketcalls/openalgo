# OpenAlgo REST API

The unified broker API (`/api/v1/`). All endpoints authenticate with your API
key in the JSON body and return a consistent `{ "status": ..., "data": ... }`
shape. Endpoints are grouped by category below.

# Categories

* [order-management](order-management/index.md) - Place, modify, cancel, and manage orders (including GTT and options orders).
* [order-information](order-information/index.md) - Query order status and open positions.
* [market-data](market-data/index.md) - Quotes, depth, historical OHLCV, and available intervals.
* [symbol-services](symbol-services/index.md) - Symbol lookup, search, expiry dates, and the instruments master.
* [options-services](options-services/index.md) - Option symbols, option chain, synthetic futures, and Greeks/IV.
* [account-services](account-services/index.md) - Funds, margin, order book, trade book, positions, and holdings.
* [market-calendar](market-calendar/index.md) - Market holidays, timings, and holiday checks.
* [analyzer-services](analyzer-services/index.md) - Sandbox/analyzer mode status and toggle.
* [websocket-streaming](websocket-streaming/index.md) - Real-time LTP, quote, and depth subscriptions.
* [whatsapp-services](whatsapp-services/index.md) - Send-only WhatsApp trade alerts.

# References

* [Rate Limiting](rate-limiting.md) - Per-operation API rate limits and configuration.
