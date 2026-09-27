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
* MCX_INDEX: MCX commodity sectoral indices, e.g. MCXBULLDEX (quote-only)
* CRYPTO: Crypto derivatives — Delta Exchange only
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

### Strategy Module Interpretation

The `/strategy` module uses the platform constants with two narrower rules:

* The configured product is **intent**, not necessarily the literal value sent
  to every venue. `MIS` stays `MIS`; either carry product is sent as `NRML` on
  derivatives exchanges and `CNC` on cash exchanges. The actual product sent is
  persisted on each strategy order row.
* Strategy entries and every exit are `MARKET` only. OpenAlgo supports `LIMIT`,
  `SL` and `SL-M` elsewhere, but a strategy/leg carries no price to send for
  those types, so the module refuses to pretend they are supported.
