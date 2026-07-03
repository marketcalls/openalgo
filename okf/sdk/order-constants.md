---
type: Reference
title: Order Constants
description: Exchange, product, price-type, and action code constants used by all order APIs
resource: https://github.com/marketcalls/openalgo/blob/main/docs/prompt/order-constants.md
tags:
- constants
- order
- exchange
- reference
timestamp: '2026-07-03T00:00:00+00:00'
---

# Order Constants

Standard code constants accepted by all OpenAlgo order APIs. See the [symbol format](symbol-format.md) reference for how these exchange codes combine with base symbols, expiry, and strike into instrument symbols, and the [Python SDK](python-sdk.md) or the [PlaceOrder](../api/order-management/placeorder.md) endpoint for how they are supplied on a request.

## Exchange

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

## Product Type

* CNC: Cash & Carry for equity
* NRML: Normal for futures and options
* MIS: Intraday Square off

## Price Type

* MARKET: Market Order
* LIMIT: Limit Order
* SL: Stop Loss Limit Order
* SL-M: Stop Loss Market Order

## Action

* BUY: Buy
* SELL: Sell

# Citations
- Official docs: https://docs.openalgo.in
- Source: https://github.com/marketcalls/openalgo/blob/main/docs/prompt/order-constants.md
