# OpenAlgo Broker API Compatibility Report

> **Generated**: February 2026
> **Brokers Audited**: 29
> **API Endpoints Audited**: 38

This document provides a comprehensive audit of which REST API endpoints (`/api/v1/*`) are supported by each broker integration in OpenAlgo. It helps traders understand broker capabilities and helps developers identify feature gaps.

---

## Table of Contents

- [Compatibility Matrix](#compatibility-matrix)
- [API Endpoints Reference](#api-endpoints-reference)
- [Brokers Missing Features](#brokers-missing-features)
- [Detailed Broker Breakdown](#detailed-broker-breakdown)

---

## Compatibility Matrix

Legend: `Y` = Supported | `-` = Not Implemented | `S` = Stub (function exists but not actually implemented)

### Order Management

| Broker | Place Order | Smart Order | Modify Order | Cancel Order | Cancel All | Close Position | Basket Order | Split Order |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 Paisa | Y | Y | Y | Y | Y | Y | Y | Y |
| 5 Paisa (XTS) | Y | Y | Y | Y | Y | Y | Y | Y |
| Alice Blue | Y | Y | Y | Y | Y | Y | Y | Y |
| Angel One | Y | Y | Y | Y | Y | Y | Y | Y |
| CompositEdge | Y | Y | Y | Y | Y | Y | Y | Y |
| Definedge | Y | Y | Y | Y | Y | Y | Y | Y |
| Dhan | Y | Y | Y | Y | Y | Y | Y | Y |
| Dhan (Sandbox) | Y | Y | Y | Y | Y | Y | Y | Y |
| Firstock | Y | Y | Y | Y | Y | Y | Y | Y |
| Flattrade | Y | Y | Y | Y | Y | Y | Y | Y |
| Fyers | Y | Y | Y | Y | Y | Y | Y | Y |
| Groww | Y | Y | Y | Y | Y | Y | Y | Y |
| Ibulls | Y | Y | Y | Y | Y | Y | Y | Y |
| IIFL | Y | Y | Y | Y | Y | Y | Y | Y |
| IndMoney | Y | Y | Y | Y | Y | Y | Y | Y |
| JainamXts | Y | Y | Y | Y | Y | Y | Y | Y |
| Kotak Securities | Y | Y | Y | Y | Y | Y | Y | Y |
| Motilal Oswal | Y | Y | Y | Y | Y | Y | Y | Y |
| mStock | Y | Y | Y | Y | Y | Y | Y | Y |
| Nubra | Y | Y | Y | Y | Y | Y | Y | Y |
| Paytm Money | Y | Y | Y | Y | Y | Y | Y | Y |
| Pocketful | Y | Y | Y | Y | Y | Y | Y | Y |
| Samco | Y | Y | Y | Y | Y | Y | Y | Y |
| Shoonya | Y | Y | Y | Y | Y | Y | Y | Y |
| Tradejini | Y | Y | Y | Y | Y | Y | Y | Y |
| Upstox | Y | Y | Y | Y | Y | Y | Y | Y |
| Wisdom Capital | Y | Y | Y | Y | Y | Y | Y | Y |
| Zebu | Y | Y | Y | Y | Y | Y | Y | Y |
| Zerodha | Y | Y | Y | Y | Y | Y | Y | Y |

> All 29 brokers support all order management endpoints.

### Account & Portfolio

| Broker | Order Book | Order Status | Trade Book | Position Book | Holdings | Open Position | Funds | Margin Calc |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 Paisa | Y | Y | Y | Y | Y | Y | Y | **S** |
| 5 Paisa (XTS) | Y | Y | Y | Y | Y | Y | Y | **S** |
| Alice Blue | Y | Y | Y | Y | Y | Y | Y | **S** |
| Angel One | Y | Y | Y | Y | Y | Y | Y | Y |
| CompositEdge | Y | Y | Y | Y | Y | Y | Y | **S** |
| Definedge | Y | Y | Y | Y | Y | Y | Y | Y |
| Dhan | Y | Y | Y | Y | Y | Y | Y | Y |
| Dhan (Sandbox) | Y | Y | Y | Y | Y | Y | Y | Y |
| Firstock | Y | Y | Y | Y | Y | Y | Y | **S** |
| Flattrade | Y | Y | Y | Y | Y | Y | Y | Y |
| Fyers | Y | Y | Y | Y | Y | Y | Y | Y |
| Groww | Y | Y | Y | Y | Y | Y | Y | Y |
| Ibulls | Y | Y | Y | Y | Y | Y | Y | **S** |
| IIFL | Y | Y | Y | Y | Y | Y | Y | **S** |
| IndMoney | Y | Y | Y | Y | Y | Y | Y | Y |
| JainamXts | Y | Y | Y | Y | Y | Y | Y | **S** |
| Kotak Securities | Y | Y | Y | Y | Y | Y | Y | Y |
| Motilal Oswal | Y | Y | Y | Y | Y | Y | Y | **S** |
| mStock | Y | Y | Y | Y | Y | Y | Y | Y |
| Nubra | Y | Y | Y | Y | Y | Y | Y | Y |
| Paytm Money | Y | Y | Y | Y | Y | Y | Y | **S** |
| Pocketful | Y | Y | Y | Y | Y | Y | Y | **S** |
| Samco | Y | Y | Y | Y | Y | Y | Y | Y |
| Shoonya | Y | Y | Y | Y | Y | Y | Y | Y |
| Tradejini | Y | Y | Y | Y | Y | Y | Y | **S** |
| Upstox | Y | Y | Y | Y | Y | Y | Y | Y |
| Wisdom Capital | Y | Y | Y | Y | Y | Y | Y | **S** |
| Zebu | Y | Y | Y | Y | Y | Y | Y | **S** |
| Zerodha | Y | Y | Y | Y | Y | Y | Y | Y |

> All 29 brokers support order book, trade book, positions, holdings, and funds. Margin calculator has 14 stub implementations (marked **S**) that raise `NotImplementedError`.

### Market Data (Key Differences Found)

| Broker | Quotes | Multi Quotes | Depth | History | Intervals | Streaming |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 Paisa | Y | Y | Y | Y | Y | Y |
| 5 Paisa (XTS) | Y | Y | Y | Y | Y | Y |
| Alice Blue | Y | Y | Y | Y* | Y | Y |
| Angel One | Y | Y | Y | Y | **-** | Y |
| CompositEdge | Y | Y | Y | Y | Y | Y |
| Definedge | Y | Y | Y | Y | **-** | Y |
| Dhan | Y | Y | Y | Y | **-** | Y |
| Dhan (Sandbox) | Y | **-** | Y | Y | **-** | Y |
| Firstock | Y | Y | Y | Y | **-** | Y |
| Flattrade | Y | Y | Y | Y | Y | Y |
| Fyers | Y | Y | Y | Y | **-** | Y |
| Groww | Y | Y | Y | Y | Y | Y |
| Ibulls | Y | Y | Y | Y | Y | Y |
| IIFL | Y | Y | Y | Y | Y | Y |
| IndMoney | Y | Y | Y | Y | Y | Y |
| JainamXts | Y | Y | Y | Y | Y | Y |
| Kotak Securities | Y | Y | Y | **S** | **S** | Y |
| Motilal Oswal | Y | Y | Y | **S** | **S** | Y |
| mStock | Y | Y | Y | Y | **-** | Y |
| Nubra | Y | Y | Y | Y | Y | Y |
| Paytm Money | Y | Y | Y | **S** | **S** | Y |
| Pocketful | Y | Y | Y | **S** | **S** | Y |
| Samco | Y | Y | Y | Y | **-** | Y |
| Shoonya | Y | Y | Y | Y | **-** | Y |
| Tradejini | Y | Y | Y | Y | Y | Y |
| Upstox | Y | Y | Y | Y | **-** | Y |
| Wisdom Capital | Y | Y | Y | Y | Y | Y |
| Zebu | Y | Y | Y | Y | **-** | Y |
| Zerodha | Y | Y | Y | Y | **-** | Y |

> `Y*` = Alice Blue: partial history support (some exchanges not supported)
> **S** = Stub: function exists but returns empty data or raises NotImplementedError

### WebSocket Streaming Depth Levels

Most brokers provide only 5-level market depth via WebSocket. Only Dhan supports 20-level depth, and Fyers supports 50-level depth via TBT.

| Broker | 5-Depth | 20-Depth | 50-Depth | Notes |
|--------|:-:|:-:|:-:|-------|
| 5 Paisa | Y | **-** | **-** | 5 levels all exchanges |
| 5 Paisa (XTS) | Y | **-** | **-** | 5 levels all exchanges |
| Alice Blue | Y | **-** | **-** | 5 levels all exchanges |
| Angel One | Y | **-** | **-** | 5 levels all exchanges |
| CompositEdge | Y | **-** | **-** | 5 levels all exchanges |
| Definedge | Y | **-** | **-** | 5 levels all exchanges |
| Dhan | Y | Y | **-** | 20 depth for NSE/NFO (max 50 instruments); auto-fallback to 5 |
| Dhan (Sandbox) | Y | **-** | **-** | 5 levels (sandbox environment) |
| Firstock | Y | **-** | **-** | 5 levels all exchanges |
| Flattrade | Y | **-** | **-** | 5 levels all exchanges |
| Fyers | Y | **-** | Y | 50 depth via TBT (Tick-by-Tick) WebSocket |
| Groww | Y | **-** | **-** | 5 levels all exchanges |
| Ibulls | Y | **-** | **-** | 5 levels all exchanges |
| IIFL | Y | **-** | **-** | 5 levels all exchanges |
| IndMoney | 1* | **-** | **-** | Best bid/ask only (1 level) |
| JainamXts | Y | **-** | **-** | 5 levels all exchanges |
| Kotak Securities | Y | **-** | **-** | 5 levels all exchanges |
| Motilal Oswal | Y | **-** | **-** | 5 levels all exchanges |
| mStock | Y | **-** | **-** | 5 levels all exchanges |
| Nubra | Y | **-** | **-** | 5 levels all exchanges |
| Paytm Money | Y | **-** | **-** | 5 levels all exchanges |
| Pocketful | Y | **-** | **-** | 5 levels all exchanges |
| Samco | Y | **-** | **-** | 5 levels all exchanges |
| Shoonya | Y | **-** | **-** | 5 levels all exchanges |
| Tradejini | Y | **-** | **-** | 5 levels all exchanges |
| Upstox | Y | **-** | **-** | 5 levels all exchanges |
| Wisdom Capital | Y | **-** | **-** | 5 levels all exchanges |
| Zebu | Y | **-** | **-** | 5 levels all exchanges |
| Zerodha | Y | **-** | **-** | 5 levels all exchanges |

> `1*` = IndMoney provides only best bid/ask (1 level depth), not full 5-level depth
> Dhan is the only broker supporting **20-level depth** (NSE/NFO only, max 50 instruments per connection, auto-fallback to 5-depth).
> Fyers is the only broker supporting **50-level depth** via a separate **TBT (Tick-by-Tick) WebSocket** connection.

### Options & Analytics

| Broker | Option Chain | Option Symbol | Options Order | Multi-Leg Options | Synthetic Future | Option Greeks | Multi Greeks |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 5 Paisa | Y | Y | Y | Y | Y | Y | Y |
| 5 Paisa (XTS) | Y | Y | Y | Y | Y | Y | Y |
| Alice Blue | Y | Y | Y | Y | Y | Y | Y |
| Angel One | Y | Y | Y | Y | Y | Y | Y |
| CompositEdge | Y | Y | Y | Y | Y | Y | Y |
| Definedge | Y | Y | Y | Y | Y | Y | Y |
| Dhan | Y | Y | Y | Y | Y | Y | Y |
| Dhan (Sandbox) | Y | Y | Y | Y | Y | Y | Y |
| Firstock | Y | Y | Y | Y | Y | Y | Y |
| Flattrade | Y | Y | Y | Y | Y | Y | Y |
| Fyers | Y | Y | Y | Y | Y | Y | Y |
| Groww | Y | Y | Y | Y | Y | Y | Y |
| Ibulls | Y | Y | Y | Y | Y | Y | Y |
| IIFL | Y | Y | Y | Y | Y | Y | Y |
| IndMoney | Y | Y | Y | Y | Y | Y | Y |
| JainamXts | Y | Y | Y | Y | Y | Y | Y |
| Kotak Securities | Y | Y | Y | Y | Y | Y | Y |
| Motilal Oswal | Y | Y | Y | Y | Y | Y | Y |
| mStock | Y | Y | Y | Y | Y | Y | Y |
| Nubra | Y | Y | Y | Y | Y | Y | Y |
| Paytm Money | Y | Y | Y | Y | Y | Y | Y |
| Pocketful | Y | Y | Y | Y | Y | Y | Y |
| Samco | Y | Y | Y | Y | Y | Y | Y |
| Shoonya | Y | Y | Y | Y | Y | Y | Y |
| Tradejini | Y | Y | Y | Y | Y | Y | Y |
| Upstox | Y | Y | Y | Y | Y | Y | Y |
| Wisdom Capital | Y | Y | Y | Y | Y | Y | Y |
| Zebu | Y | Y | Y | Y | Y | Y | Y |
| Zerodha | Y | Y | Y | Y | Y | Y | Y |

> Options & analytics endpoints use `get_quotes` + master contract DB + Black-76 model. All 29 brokers support these since they all implement `get_quotes`.

### Utility & Platform Endpoints

| Endpoint | Broker Dependent? | Supported |
|----------|:-:|:-:|
| Ping | No (API key check) | All 29 |
| Symbol Lookup | No (master contract DB) | All 29 |
| Search | No (master contract DB) | All 29 |
| Instruments | No (master contract DB) | All 29 |
| Expiry Dates | No (master contract DB) | All 29 |
| Chart Preferences | No (local DB) | All 29 |
| Market Timings | No (static calendar) | All 29 |
| Market Holidays | No (static calendar) | All 29 |
| Analyzer Toggle | No (sandbox DB) | All 29 |
| PnL Symbols | No (sandbox DB) | All 29 |
| Telegram Bot | No (telegram service) | All 29 |

> These endpoints don't depend on broker-specific implementations and work across all brokers.

---

## API Endpoints Reference

### Order Management Endpoints

| Endpoint | Method | Broker Function | Description |
|----------|--------|-----------------|-------------|
| `/api/v1/placeorder` | POST | `place_order_api` | Place a new order |
| `/api/v1/placesmartorder` | POST | `place_smartorder_api` | Place a smart order with delay |
| `/api/v1/modifyorder` | POST | `modify_order` | Modify an existing order |
| `/api/v1/cancelorder` | POST | `cancel_order` | Cancel an order by ID |
| `/api/v1/cancelallorder` | POST | `cancel_all_orders_api` | Cancel all open orders |
| `/api/v1/closeposition` | POST | `close_all_positions` | Close all open positions |
| `/api/v1/basketorder` | POST | `place_order_api` (per order) | Place multiple orders in batch |
| `/api/v1/splitorder` | POST | `place_order_api` (per split) | Split large order into smaller ones |

### Account & Portfolio Endpoints

| Endpoint | Method | Broker Function | Description |
|----------|--------|-----------------|-------------|
| `/api/v1/orderbook` | POST | `get_order_book` | Get all orders |
| `/api/v1/orderstatus` | POST | `get_order_book` (filtered) | Get specific order status |
| `/api/v1/tradebook` | POST | `get_trade_book` | Get executed trades |
| `/api/v1/positionbook` | POST | `get_positions` | Get open positions |
| `/api/v1/holdings` | POST | `get_holdings` | Get long-term holdings |
| `/api/v1/openposition` | POST | `get_open_position` | Get specific position quantity |
| `/api/v1/funds` | POST | `get_margin_data` | Get account balance and margins |
| `/api/v1/margin` | POST | `calculate_margin_api` | Calculate margin for positions |

### Market Data Endpoints

| Endpoint | Method | Broker Function | Description |
|----------|--------|-----------------|-------------|
| `/api/v1/quotes` | POST | `BrokerData.get_quotes` | Real-time quote for a symbol |
| `/api/v1/multiquotes` | POST | `BrokerData.get_multiquotes` | Quotes for multiple symbols |
| `/api/v1/depth` | POST | `BrokerData.get_depth` | Market depth (order book) |
| `/api/v1/history` | POST | `BrokerData.get_history` | Historical OHLC data |
| `/api/v1/ticker/<symbol>` | GET | `BrokerData.get_history` | Historical data (text/JSON) |
| `/api/v1/intervals` | POST | `BrokerData.get_intervals` | Supported chart intervals |

### Symbol & Instrument Endpoints

| Endpoint | Method | Broker Function | Description |
|----------|--------|-----------------|-------------|
| `/api/v1/symbol` | POST | Master contract DB | Get symbol information |
| `/api/v1/search` | POST | Master contract DB | Search symbols |
| `/api/v1/instruments` | GET | Master contract DB | Download all instruments |
| `/api/v1/expiry` | POST | Master contract DB | Get F&O expiry dates |

### Options & Analytics Endpoints

| Endpoint | Method | Broker Function | Description |
|----------|--------|-----------------|-------------|
| `/api/v1/optionchain` | POST | `get_quotes` (for strikes) | Option chain with live quotes |
| `/api/v1/optionsymbol` | POST | Master contract DB | Resolve option symbol from offset |
| `/api/v1/optionsorder` | POST | `place_order_api` | Place option order by offset |
| `/api/v1/optionsmultiorder` | POST | `place_order_api` (multi-leg) | Multi-leg option strategies |
| `/api/v1/syntheticfuture` | POST | `get_quotes` (ATM CE+PE) | Calculate synthetic future price |
| `/api/v1/optiongreeks` | POST | `get_quotes` + Black-76 | Calculate option Greeks & IV |
| `/api/v1/multioptiongreeks` | POST | `get_quotes` + Black-76 | Batch Greeks for multiple options |

### Utility Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/ping` | POST | API connectivity check |
| `/api/v1/chart` | GET/POST | Chart preferences (TradingView) |
| `/api/v1/market/timings` | POST | Market open/close times |
| `/api/v1/market/holidays` | POST | Market holidays calendar |
| `/api/v1/analyzer` | GET/POST | Analyzer (paper trading) mode |
| `/api/v1/pnl/symbols` | POST | P&L breakdown by symbol |
| `/api/v1/telegram/*` | Various | Telegram bot integration |

---

## Brokers Missing Features

### Stub Implementations (Function Exists but Not Working)

Some brokers have API functions defined but the implementation is a stub — they raise `NotImplementedError`, return empty DataFrames, or return error messages. These are **not functional** despite the function being present in code.

#### Historical Data Stubs (4 brokers)

| Broker | Implementation | Details |
|--------|----------------|---------|
| Kotak Securities | Returns empty DataFrame | "Kotak Neo does not support historical data" |
| Motilal Oswal | Returns empty DataFrame | "Historical data not provided by Motilal Oswal" |
| Paytm Money | Raises NotImplementedError | "Paytm does not support historical data API" |
| Pocketful | Returns stub response | "Pocketful does not support historical data API" |

#### Intervals Stubs (4 brokers)

These brokers have `get_intervals`/`get_supported_intervals` defined but it returns empty data:

| Broker | Implementation | Details |
|--------|----------------|---------|
| Kotak Securities | Returns empty list | "Kotak Neo does not support historical data intervals" |
| Motilal Oswal | Returns empty list | "Historical data intervals not provided by Motilal Oswal" |
| Paytm Money | Raises NotImplementedError | "Paytm does not support historical data API" |
| Pocketful | Returns stub response | Not implemented |

#### Margin Calculator Stubs (14 brokers)

These brokers have `calculate_margin_api` defined but it raises `NotImplementedError`:

| Broker | Implementation |
|--------|----------------|
| 5 Paisa | Raises NotImplementedError |
| 5 Paisa (XTS) | Raises NotImplementedError |
| Alice Blue | Raises NotImplementedError |
| CompositEdge | Raises NotImplementedError |
| Firstock | Raises NotImplementedError |
| Ibulls | Raises NotImplementedError |
| IIFL | Raises NotImplementedError |
| JainamXts | Raises NotImplementedError |
| Motilal Oswal | Raises NotImplementedError |
| Paytm Money | Raises NotImplementedError |
| Pocketful | Raises NotImplementedError |
| Tradejini | Raises NotImplementedError |
| Wisdom Capital | Raises NotImplementedError |
| Zebu | Raises NotImplementedError |

#### Partial Implementation

| Broker | Feature | Details |
|--------|---------|---------|
| Alice Blue | History | "AliceBlue does not support historical data for {exchange} exchange yet" — works for some exchanges but not all |

### Missing Functions (Not Defined at All)

#### Missing `get_intervals` (12 brokers)

The following brokers do not have the `get_intervals` method defined at all:

| Broker | Status |
|--------|--------|
| Angel One | Missing |
| Definedge | Missing |
| Dhan | Missing |
| Dhan (Sandbox) | Missing |
| Firstock | Missing |
| Fyers | Missing |
| mStock | Missing |
| Samco | Missing |
| Shoonya | Missing |
| Upstox | Missing |
| Zebu | Missing |
| Zerodha | Missing |

#### Missing `get_multiquotes` (1 broker)

| Broker | Status |
|--------|--------|
| Dhan (Sandbox) | Missing |

> **Note**: Dhan (Sandbox) is a paper trading environment.

---

## Detailed Broker Breakdown

Each broker implements its API through three core files in `broker/<name>/api/`:

| File | Purpose | Functions |
|------|---------|-----------|
| `order_api.py` | Order management | `place_order_api`, `place_smartorder_api`, `modify_order`, `cancel_order`, `cancel_all_orders_api`, `close_all_positions`, `get_order_book`, `get_trade_book`, `get_positions`, `get_holdings`, `get_open_position` |
| `data.py` | Market data (BrokerData class) | `get_quotes`, `get_multiquotes`, `get_depth`, `get_history`, `get_intervals` |
| `funds.py` | Account funds | `get_margin_data` |
| `margin_api.py` | Margin calculation | `calculate_margin_api` |

### Authentication Types

| Auth Type | Brokers |
|-----------|---------|
| **OAuth** | CompositEdge, Dhan, Flattrade, Fyers, Paytm Money, Pocketful, Upstox, Zerodha |
| **TOTP/Form** | 5 Paisa, 5 Paisa (XTS), Alice Blue, Angel One, Dhan (Sandbox), Definedge, Firstock, Groww, Ibulls, IIFL, IndMoney, JainamXts, Kotak Securities, Motilal Oswal, mStock, Nubra, Samco, Shoonya, Tradejini, Wisdom Capital, Zebu |

### Per-Broker Feature Summary

#### 5 Paisa (`fivepaisa`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_supported_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### 5 Paisa XTS (`fivepaisaxts`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Alice Blue (`aliceblue`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history (partial — some exchanges not supported), get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Angel One (`angel`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### CompositEdge (`compositedge`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Definedge (`definedge`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Dhan (`dhan`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes
- **WS Depth**: 5 + 20 levels (NSE/NFO; max 50 instruments for 20-depth; auto-fallback to 5)

#### Dhan Sandbox (`dhan_sandbox`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_depth, get_history
- **Missing**: get_multiquotes, get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Firstock (`firstock`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history (chunked support)
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Flattrade (`flattrade`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Fyers (`fyers`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes (HSM + TBT WebSocket)
- **WS Depth**: 5 + **50 levels** (via TBT Tick-by-Tick WebSocket)

#### Groww (`groww`)
- **Auth**: TOTP
- **Order API**: All 11 functions + direct order variants
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes (NATS WebSocket)

#### Ibulls (`ibulls`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### IIFL (`iifl`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### IndMoney (`indmoney`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes
- **WS Depth**: 1 level only (best bid/ask)

#### JainamXts (`jainamxts`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_market_depth
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Kotak Securities (`kotak`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth
- **History**: **stub** — returns empty DataFrame ("Kotak Neo does not support historical data")
- **Intervals**: **stub** — returns empty list ("Kotak Neo does not support historical data intervals")
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (+ calculate_single_margin)
- **Streaming**: Yes

#### Motilal Oswal (`motilal`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth
- **History**: **stub** — returns empty DataFrame ("Historical data not provided by Motilal Oswal")
- **Intervals**: **stub** — returns empty list ("Historical data intervals not provided by Motilal Oswal")
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes (custom WebSocket)

#### mStock by Mirae Asset (`mstock`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Nubra (`nubra`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals, get_oi_history
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Paytm Money (`paytm`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_market_depth
- **History**: **stub** — raises NotImplementedError ("Paytm does not support historical data API")
- **Intervals**: **stub** — raises NotImplementedError ("Paytm does not support historical data API")
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Pocketful (`pocketful`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_market_depth
- **History**: **stub** — returns error response ("Pocketful does not support historical data API")
- **Intervals**: **stub** — returns empty data
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes (custom WebSocket)

#### Samco (`samco`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Shoonya (`shoonya`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Tradejini (`tradejini`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes (custom WebSocket)

#### Upstox (`upstox`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data (+ calculate_total_collateral)
- **Margin**: calculate_margin_api
- **Streaming**: Yes

#### Wisdom Capital (`wisdom`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Zebu (`zebu`)
- **Auth**: TOTP
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api (**stub** — raises NotImplementedError)
- **Streaming**: Yes

#### Zerodha (`zerodha`)
- **Auth**: OAuth
- **Order API**: All 11 functions
- **Data API**: get_quotes, get_multiquotes, get_depth, get_history, get_market_depth
- **Missing**: get_intervals
- **Funds**: get_margin_data
- **Margin**: calculate_margin_api
- **Streaming**: Yes

---

## Summary Statistics

| Metric | Count |
|--------|-------|
| Total Brokers | 29 |
| Total API Endpoints | 38 |
| Brokers with Full Order Support | 29/29 (100%) |
| Brokers with Full Account Support | 29/29 (100%) |
| Brokers with Quotes | 29/29 (100%) |
| Brokers with Multi Quotes | 28/29 (97%) |
| Brokers with Market Depth | 29/29 (100%) |
| Brokers with **Working** Historical Data | 24/29 (83%) |
| Brokers with **Working** Intervals API | 14/29 (48%) |
| Brokers with Streaming | 29/29 (100%) |
| Brokers with **Working** Margin Calculator | 15/29 (52%) |
| Brokers with **5-Depth** WebSocket | 28/29 (97%) |
| Brokers with **20-Depth** WebSocket | 1/29 (Dhan only) |
| Brokers with **50-Depth** WebSocket | 1/29 (Fyers only) |

### Feature Gap Summary

| Feature | Status | Brokers Affected | Impact |
|---------|--------|-----------------|--------|
| History | **Stub** | Kotak, Motilal, Paytm, Pocketful | `/api/v1/history` returns empty/error |
| History | **Partial** | Alice Blue | Works for some exchanges only |
| Intervals | **Missing** | Angel One, Definedge, Dhan, Dhan Sandbox, Firstock, Fyers, mStock, Samco, Shoonya, Upstox, Zebu, Zerodha | `/api/v1/intervals` endpoint unavailable |
| Intervals | **Stub** | Kotak, Motilal, Paytm, Pocketful | `/api/v1/intervals` returns empty data |
| Margin Calc | **Stub** | 5 Paisa, 5 Paisa XTS, Alice Blue, CompositEdge, Firstock, Ibulls, IIFL, JainamXts, Motilal, Paytm, Pocketful, Tradejini, Wisdom, Zebu | `/api/v1/margin` raises NotImplementedError |
| Multi Quotes | **Missing** | Dhan Sandbox | `/api/v1/multiquotes` endpoint unavailable |
| WS Depth | **1 level only** | IndMoney | Best bid/ask only, no full 5-level depth |
| WS 20-Depth | **Dhan only** | 28 brokers | Only Dhan supports 20-level depth (NSE/NFO) |
| WS 50-Depth | **Fyers only** | 28 brokers | Only Fyers supports 50-level TBT depth |
