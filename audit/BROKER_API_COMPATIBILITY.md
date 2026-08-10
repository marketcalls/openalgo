# OpenAlgo Broker API Compatibility Report

> **Generated from the codebase** by
> `scripts/generate_broker_compatibility.py`. Do not edit by hand -
> rerun the script instead. The previous hand-maintained version drifted
> to 29 brokers while the tree carried 35, and never gained a GTT column.
>
> **Brokers**: 35
> **Capabilities checked**: 23

Support is determined the way the application determines it at runtime: by whether the broker module and function exist.

Legend: `Y` supported | `S` stub - defined but raises, returns empty, or answers "not supported" | `-` not implemented

The stub state matters most. A broker whose `get_history` returns an empty frame looks supported to any check that only asks whether the function is defined, and a trader finds out when a backtest quietly returns nothing.

## Order Management

| Broker | Place Order | Smart Order | Modify Order | Cancel Order | Cancel All | Close Position |
|---|---|---|---|---|---|---|
| aliceblue | Y | Y | Y | Y | Y | Y |
| angel | Y | Y | Y | Y | Y | Y |
| arrow | Y | Y | Y | Y | Y | Y |
| compositedge | Y | Y | Y | Y | Y | Y |
| definedge | Y | Y | Y | Y | Y | Y |
| deltaexchange | Y | Y | Y | Y | Y | Y |
| dhan | Y | Y | Y | Y | Y | Y |
| dhan_sandbox | Y | Y | Y | Y | Y | Y |
| firstock | Y | Y | Y | Y | Y | Y |
| fivepaisa | Y | Y | Y | Y | Y | Y |
| fivepaisaxts | Y | Y | Y | Y | Y | Y |
| flattrade | Y | Y | Y | Y | Y | Y |
| fyers | Y | Y | Y | Y | Y | Y |
| groww | Y | Y | Y | Y | Y | Y |
| hdfcsky | Y | Y | Y | Y | Y | Y |
| ibulls | Y | Y | Y | Y | Y | Y |
| iifl | Y | Y | Y | Y | Y | Y |
| iiflcapital | Y | Y | Y | Y | Y | Y |
| indmoney | Y | Y | Y | Y | Y | Y |
| jainamxts | Y | Y | Y | Y | Y | Y |
| kotak | Y | Y | Y | Y | Y | Y |
| motilal | Y | Y | Y | Y | Y | Y |
| mstock | Y | Y | Y | Y | Y | Y |
| nubra | Y | Y | Y | Y | Y | Y |
| paytm | Y | Y | Y | Y | Y | Y |
| pocketful | Y | Y | Y | Y | Y | Y |
| rmoney | Y | Y | Y | Y | Y | Y |
| samco | Y | Y | Y | Y | Y | Y |
| shoonya | Y | Y | Y | Y | Y | Y |
| tradejini | Y | Y | Y | Y | Y | Y |
| tradesmart | Y | Y | Y | Y | Y | Y |
| upstox | Y | Y | Y | Y | Y | Y |
| wisdom | Y | Y | Y | Y | Y | Y |
| zebu | Y | Y | Y | Y | Y | Y |
| zerodha | Y | Y | Y | Y | Y | Y |

## GTT Orders

| Broker | Place GTT | Modify GTT | Cancel GTT | GTT Book |
|---|---|---|---|---|
| aliceblue | - | - | - | - |
| angel | - | - | - | - |
| arrow | - | - | - | - |
| compositedge | - | - | - | - |
| definedge | - | - | - | - |
| deltaexchange | - | - | - | - |
| dhan | Y | Y | Y | Y |
| dhan_sandbox | - | - | - | - |
| firstock | - | - | - | - |
| fivepaisa | - | - | - | - |
| fivepaisaxts | - | - | - | - |
| flattrade | - | - | - | - |
| fyers | - | - | - | - |
| groww | - | - | - | - |
| hdfcsky | - | - | - | - |
| ibulls | - | - | - | - |
| iifl | - | - | - | - |
| iiflcapital | - | - | - | - |
| indmoney | - | - | - | - |
| jainamxts | - | - | - | - |
| kotak | - | - | - | - |
| motilal | - | - | - | - |
| mstock | - | - | - | - |
| nubra | - | - | - | - |
| paytm | - | - | - | - |
| pocketful | - | - | - | - |
| rmoney | - | - | - | - |
| samco | - | - | - | - |
| shoonya | - | - | - | - |
| tradejini | - | - | - | - |
| tradesmart | - | - | - | - |
| upstox | - | - | - | - |
| wisdom | - | - | - | - |
| zebu | - | - | - | - |
| zerodha | Y | Y | Y | Y |

## Account & Portfolio

| Broker | Orderbook | Tradebook | Positionbook | Holdings | Open Position | Funds | Margin |
|---|---|---|---|---|---|---|---|
| aliceblue | Y | Y | Y | Y | Y | Y | S |
| angel | Y | Y | Y | Y | Y | Y | Y |
| arrow | Y | Y | Y | Y | Y | Y | Y |
| compositedge | Y | Y | Y | Y | Y | Y | S |
| definedge | Y | Y | Y | Y | Y | Y | Y |
| deltaexchange | Y | Y | Y | Y | Y | Y | Y |
| dhan | Y | Y | Y | Y | Y | Y | Y |
| dhan_sandbox | Y | Y | Y | Y | Y | Y | Y |
| firstock | Y | Y | Y | Y | Y | Y | Y |
| fivepaisa | Y | Y | Y | Y | Y | Y | S |
| fivepaisaxts | Y | Y | Y | Y | Y | Y | S |
| flattrade | Y | Y | Y | Y | Y | Y | Y |
| fyers | Y | Y | Y | Y | Y | Y | Y |
| groww | Y | Y | Y | Y | Y | Y | Y |
| hdfcsky | Y | Y | Y | Y | Y | Y | Y |
| ibulls | Y | Y | Y | Y | Y | Y | S |
| iifl | Y | Y | Y | Y | Y | Y | S |
| iiflcapital | Y | Y | Y | Y | Y | Y | Y |
| indmoney | Y | Y | Y | Y | Y | Y | Y |
| jainamxts | Y | Y | Y | Y | Y | Y | S |
| kotak | Y | Y | Y | Y | Y | Y | Y |
| motilal | Y | Y | Y | Y | Y | Y | S |
| mstock | Y | Y | Y | Y | Y | Y | Y |
| nubra | Y | Y | Y | Y | Y | Y | Y |
| paytm | Y | Y | Y | Y | Y | Y | S |
| pocketful | Y | Y | Y | Y | Y | Y | S |
| rmoney | Y | Y | Y | Y | Y | Y | Y |
| samco | Y | Y | Y | Y | Y | Y | Y |
| shoonya | Y | Y | Y | Y | Y | Y | Y |
| tradejini | Y | Y | Y | Y | Y | Y | S |
| tradesmart | Y | Y | Y | Y | Y | Y | Y |
| upstox | Y | Y | Y | Y | Y | Y | Y |
| wisdom | Y | Y | Y | Y | Y | Y | S |
| zebu | Y | Y | Y | Y | Y | Y | S |
| zerodha | Y | Y | Y | Y | Y | Y | Y |

## Market Data

| Broker | Quotes | Depth | History | Intervals |
|---|---|---|---|---|
| aliceblue | Y | Y | S | Y |
| angel | Y | Y | S | Y |
| arrow | Y | Y | Y | Y |
| compositedge | Y | Y | Y | Y |
| definedge | Y | Y | S | Y |
| deltaexchange | Y | Y | Y | Y |
| dhan | Y | Y | Y | Y |
| dhan_sandbox | S | Y | Y | Y |
| firstock | Y | Y | Y | Y |
| fivepaisa | Y | Y | Y | Y |
| fivepaisaxts | Y | Y | Y | Y |
| flattrade | Y | Y | Y | Y |
| fyers | Y | Y | S | Y |
| groww | Y | Y | Y | Y |
| hdfcsky | Y | Y | Y | Y |
| ibulls | Y | Y | Y | Y |
| iifl | Y | Y | Y | Y |
| iiflcapital | Y | Y | Y | Y |
| indmoney | Y | Y | Y | Y |
| jainamxts | Y | Y | Y | Y |
| kotak | Y | Y | S | S |
| motilal | Y | Y | S | S |
| mstock | S | S | Y | Y |
| nubra | Y | S | S | Y |
| paytm | Y | Y | S | Y |
| pocketful | Y | Y | S | S |
| rmoney | Y | Y | Y | Y |
| samco | Y | Y | Y | Y |
| shoonya | Y | Y | Y | Y |
| tradejini | Y | Y | Y | Y |
| tradesmart | Y | Y | Y | Y |
| upstox | Y | Y | Y | Y |
| wisdom | Y | Y | Y | Y |
| zebu | Y | Y | Y | Y |
| zerodha | Y | Y | Y | Y |

## WebSocket Streaming

Market data and order/trade updates are separate adapters. Plenty of brokers ship the first without the second, so a single "streaming" column would tell a user their order updates work when they do not.

A `-` under Order/Trade Updates means not implemented **yet**. Coverage for the remaining brokers is planned, so read it as a current state rather than a permanent limitation.

| Broker | Market Data | Order/Trade Updates |
|---|---|---|
| aliceblue | Y | Y |
| angel | Y | Y |
| arrow | Y | Y |
| compositedge | Y | - |
| definedge | Y | Y |
| deltaexchange | S | - |
| dhan | Y | Y |
| dhan_sandbox | Y | - |
| firstock | Y | - |
| fivepaisa | Y | - |
| fivepaisaxts | Y | - |
| flattrade | Y | Y |
| fyers | Y | Y |
| groww | Y | - |
| hdfcsky | Y | - |
| ibulls | Y | - |
| iifl | Y | - |
| iiflcapital | Y | Y |
| indmoney | Y | Y |
| jainamxts | Y | - |
| kotak | Y | Y |
| motilal | Y | - |
| mstock | Y | - |
| nubra | Y | Y |
| paytm | Y | - |
| pocketful | Y | - |
| rmoney | Y | - |
| samco | Y | - |
| shoonya | Y | Y |
| tradejini | Y | - |
| tradesmart | Y | Y |
| upstox | Y | Y |
| wisdom | Y | - |
| zebu | Y | Y |
| zerodha | Y | Y |

## Exchanges and Broker Type

| Broker | Type | Leverage config | Exchanges |
|---|---|---|---|
| aliceblue | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| angel | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX, MCX_INDEX |
| arrow | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| compositedge | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| definedge | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| deltaexchange | crypto | true | CRYPTO |
| dhan | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| dhan_sandbox | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| firstock | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX |
| fivepaisa | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fivepaisaxts | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| flattrade | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fyers | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| groww | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| hdfcsky | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| ibulls | IN_stock | false | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| iifl | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| iiflcapital | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| indmoney | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| jainamxts | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| kotak | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| motilal | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| mstock | IN_stock | false | NSE, BSE, NFO, BFO, CDS, NSE_INDEX, BSE_INDEX |
| nubra | IN_stock | false | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| paytm | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| pocketful | IN_stock | false | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| rmoney | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| samco | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| shoonya | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| tradejini | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| tradesmart | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| upstox | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX, GLOBAL_INDEX |
| wisdom | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| zebu | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX |
| zerodha | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NCO, NSE_INDEX, BSE_INDEX, MCX_INDEX, GLOBAL_INDEX |

## Summary

- **Place Order**: 35/35 brokers
- **Smart Order**: 35/35 brokers
- **Modify Order**: 35/35 brokers
- **Cancel Order**: 35/35 brokers
- **Cancel All**: 35/35 brokers
- **Close Position**: 35/35 brokers
- **Place GTT**: 2/35 brokers
- **Modify GTT**: 2/35 brokers
- **Cancel GTT**: 2/35 brokers
- **GTT Book**: 2/35 brokers
- **Orderbook**: 35/35 brokers
- **Tradebook**: 35/35 brokers
- **Positionbook**: 35/35 brokers
- **Holdings**: 35/35 brokers
- **Open Position**: 35/35 brokers
- **Funds**: 35/35 brokers
- **Margin**: 22/35 brokers, 13 stub
- **Quotes**: 33/35 brokers, 2 stub
- **Depth**: 33/35 brokers, 2 stub
- **History**: 26/35 brokers, 9 stub
- **Intervals**: 32/35 brokers, 3 stub
- **Streaming: Market Data**: 34/35 brokers, 1 stub
- **Streaming: Order/Trade Updates**: 16/35 brokers

_Regenerated 05 August 2026._
