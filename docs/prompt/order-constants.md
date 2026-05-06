# Order Constants

## Order Constants

### Exchange

* NSE: NSE Equity
* NFO: NSE Futures & Options
* CDS: NSE Currency
* BSE: BSE Equity
* BFO: BSE Futures & Options
* BCD: BSE Currency
* MCX: MCX Commodity
* NCDEX: NCDEX Commodity
* NCO: NSE Commodities (futures + options) — Zerodha only
* NSE_INDEX: NSE Index (quote-only)
* BSE_INDEX: BSE Index (quote-only)
* GLOBAL_INDEX: Global indices like US30, JAPAN225, HANGSENG, GIFTNIFTY (quote-only) — Zerodha only

### Product Type

* CNC: Cash & Carry for equity
* NRML: Normal for futures and options
* MIS: Intraday Square off

### Price Type

* MARKET: Market Order
* LIMIT: Limit Order
* SL: Stop Loss Limit Order
* SL-M: Stop Loss Market Order

### Action

* BUY: Buy
* SELL: Sell

### Order Status

Canonical `order_status` values returned by `/orderbook` and `/orderstatus`:

* open: Order accepted by the broker, awaiting fill (includes partial fills before the close)
* complete: Order fully filled
* rejected: Order refused by the broker (margin, risk, schema, etc.)
* cancelled: Order cancelled by the user, the system, or the exchange

Strategy v2's `/strategy/api/v2/run/<run_id>/orderbook` and
`/strategy/api/v2/strategy/<strategy_id>/orderbook` return the same set.
The `statistics` block on the orderbook envelope counts complete/open/rejected
separately; cancelled orders are NOT counted toward `total_open_orders`.