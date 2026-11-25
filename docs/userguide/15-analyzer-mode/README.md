# 15 - Analyzer Mode

## Overview

Analyzer Mode routes supported trading and account operations to OpenAlgo's sandbox instead of the live broker. Simulated orders, trades, positions, holdings, funds, and configuration are stored in `db/sandbox.db`.

Market prices still come from the active broker data services, so a broker connection and the relevant market-data entitlement may still be required. Analyzer Mode is an execution sandbox, not an exchange emulator or portfolio backtesting engine.

## Enable and Verify

Use the mode control in the OpenAlgo UI, or call the public endpoints:

```http
POST /api/v1/analyzer
POST /api/v1/analyzer/toggle
```

```json
{
  "apikey": "<your_app_apikey>",
  "mode": true
}
```

The mode is application-wide for the single-user deployment, not per API key. The toggle API is blocked in semi-auto mode; the client must change mode from the authenticated UI in that compliance posture.

Always read the current status before starting an automated test. Turning Analyzer Mode off returns supported order flows to live broker execution.

## Supported Behavior

- Regular, smart, basket, split, options, and multi-options services use sandbox paths where implemented.
- MARKET orders can complete from current prices; LIMIT, SL, and SL-M orders can remain pending until their conditions are met.
- The execution engine uses WebSocket prices when available and can fall back to polling.
- Position book, holdings, funds, order book, trade book, status, modify, cancel, close, and P&L services read or update sandbox state where their analyzer branches exist.
- GTT orders work in analyzer mode: place, modify, cancel and the GTT order book are served by the sandbox. A trigger fires against live LTP and places a sandbox order; the Orderbook page's GTT tab lists active triggers first, followed by triggered and cancelled history.

Broker and exchange behavior is only approximated by the local managers. Broker-specific RMS checks, queue priority, slippage, partial fills, outages, and exchange microstructure can differ from Analyzer results.

## Default Configuration

Open `/sandbox` to inspect and update sandbox settings. Fresh databases use these defaults:

| Setting | Default |
|---|---:|
| Starting capital | INR 10,000,000 |
| Automatic fund reset | Never (disabled) |
| Reset time when enabled | 00:00 IST |
| Pending-order check interval | 5 seconds |
| MTM update interval | 5 seconds |
| NSE/BSE/NFO/BFO MIS square-off | 15:15 IST |
| CDS/BCD MIS square-off | 16:45 IST |
| MCX MIS square-off | 23:30 IST |
| NCDEX MIS square-off | 17:00 IST |
| Equity MIS leverage | 5x |
| Equity CNC leverage | 1x |
| Futures leverage | 10x |
| Option buy leverage | 1x |
| Option sell leverage | 1x |

These are sandbox configuration values, not broker promises. Operators can change them, and broker live-trading rules remain authoritative outside Analyzer Mode.

## Suggested Test Workflow

1. Confirm `POST /api/v1/analyzer` reports `analyze_mode: true`.
2. Place one MARKET order and verify order book, trade book, position book, and funds.
3. Place a LIMIT or stop order away from the market and verify pending execution behavior.
4. Exercise modify, cancel, smart, basket, and split flows that the strategy uses.
5. Verify square-off and reset configuration rather than assuming defaults.
6. Review sandbox P&L, order events, and errors.
7. Before live use, reduce quantity, verify the mode again, and monitor the broker terminal.

## Brokerage And Charges

Every sandbox trade pays brokerage and statutory charges, so sandbox results are
close to what the same trades cost in a live account. The charges are taken from
the available balance when the order fills. P&L is shown before charges, with the
charges beside it.

| Page | What it is for |
|---|---|
| `/sandbox/commissions` | Set your broker's brokerage for each segment, switch charges on or off, and see what trades have cost (Transaction Costs, with a CSV export) |
| `/sandbox/calculator` | Work out what a buy and a sell cost before placing them: brokerage, every statutory line, points to breakeven and net P&L |
| `/sandbox/mypnl` | Today's and lifetime charges beside the P&L, and a charges column per day and per trade |

Brokerage is two numbers per segment: an amount per executed order and a
percentage of the trade value. With both set, the lower of the two is charged on
each order. Set either to 0 to leave it out.

| Segment | Default brokerage |
|---|---|
| Equity delivery | 20 per order or 2.5% of the trade value, whichever is lower |
| Equity intraday | 20 per order or 0.1%, whichever is lower |
| Futures (equity, currency, commodity) | 20 per order or 0.03%, whichever is lower |
| Options (equity, currency, commodity) | 20 per order |
| Crypto | Nothing until you enter your venue's fee |

STT or CTT, exchange transaction charges, SEBI fees, stamp duty and GST are added
at the published rates. They are the same at every broker and cannot be changed.

Not charged: depository (DP) charges on a delivery sell, and STT on an option
that is held to expiry and exercised. Trades made before charges were introduced
are not charged after the fact.

## Resetting Sandbox Data

The Sandbox page provides manual reset controls and optional scheduled fund resets. A reset affects simulated state only, and puts the brokerage plan back to its defaults. The default `reset_day` is `Never`, so no weekly reset occurs unless an operator enables one.

---

**Previous**: [14 - Positions & Holdings](../14-positions-holdings/README.md)

**Next**: [Symbol Format Guide](../symbol-format/README.md)
