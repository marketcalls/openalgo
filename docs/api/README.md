# OpenAlgo API Documentation

This directory documents the registered OpenAlgo v1 REST API and the separate WebSocket protocol. The source of truth for REST registration is `restx_api/__init__.py`; request validation is defined in `restx_api/schemas.py`, `restx_api/data_schemas.py`, and `restx_api/account_schema.py`.

## Base URLs

```text
REST API:  http://127.0.0.1:5000/api/v1
WebSocket: ws://127.0.0.1:8765
```

Replace the local host with the configured HTTPS/WSS domain in a remote deployment.

## Authentication

Most POST endpoints accept the OpenAlgo API key as `apikey` in a JSON object. GET endpoints accept it as the `apikey` query parameter. Telegram and WhatsApp management endpoints may also accept `X-API-KEY`; the Telegram webhook authenticates with `X-Telegram-Bot-Api-Secret-Token` instead of an OpenAlgo key.

```json
{
  "apikey": "<your_app_apikey>"
}
```

Never put broker credentials or broker access tokens in these requests. The OpenAlgo API key resolves the active broker session server-side.

## Registered REST Inventory

The current v1 surface contains **57 method/path pairs**. A resource with both GET and POST counts as two endpoints.

### Order Management

| Method | Path | Documentation |
|---|---|---|
| POST | `/placeorder` | [Place order](./order-management/placeorder.md) |
| POST | `/placesmartorder` | [Place smart order](./order-management/placesmartorder.md) |
| POST | `/optionsorder` | [Options order](./order-management/optionsorder.md) |
| POST | `/optionsmultiorder` | [Options multi-order](./order-management/optionsmultiorder.md) |
| POST | `/basketorder` | [Basket order](./order-management/basketorder.md) |
| POST | `/splitorder` | [Split order](./order-management/splitorder.md) |
| POST | `/modifyorder` | [Modify order](./order-management/modifyorder.md) |
| POST | `/cancelorder` | [Cancel order](./order-management/cancelorder.md) |
| POST | `/cancelallorder` | [Cancel all orders](./order-management/cancelallorder.md) |
| POST | `/closeposition` | [Close positions](./order-management/closeposition.md) |
| POST | `/placegttorder` | [Place GTT](./order-management/placegttorder.md) |
| POST | `/modifygttorder` | [Modify GTT](./order-management/modifygttorder.md) |
| POST | `/cancelgttorder` | [Cancel GTT](./order-management/cancelgttorder.md) |
| POST | `/gttorderbook` | [GTT order book](./order-management/gttorderbook.md) |

### Order And Account Information

| Method | Path | Documentation |
|---|---|---|
| POST | `/orderstatus` | [Order status](./order-information/orderstatus.md) |
| POST | `/openposition` | [Open position](./order-information/openposition.md) |
| POST | `/funds` | [Funds](./account-services/funds.md) |
| POST | `/margin` | [Margin](./account-services/margin.md) |
| POST | `/orderbook` | [Order book](./account-services/orderbook.md) |
| POST | `/tradebook` | [Trade book](./account-services/tradebook.md) |
| POST | `/positionbook` | [Position book](./account-services/positionbook.md) |
| POST | `/holdings` | [Holdings](./account-services/holdings.md) |

### Market Data And Symbols

| Method | Path | Documentation |
|---|---|---|
| POST | `/quotes` | [Quote](./market-data/quotes.md) |
| POST | `/multiquotes` | [Multiple quotes](./market-data/multiquotes.md) |
| POST | `/depth` | [Market depth](./market-data/depth.md) |
| POST | `/history` | [Historical candles](./market-data/history.md) |
| POST | `/intervals` | [Supported intervals](./market-data/intervals.md) |
| GET | `/ticker/<string:symbol>` | [Ticker-compatible history](./market-data/ticker.md) |
| POST | `/symbol` | [Symbol information](./symbol-services/symbol.md) |
| POST | `/search` | [Symbol search](./symbol-services/search.md) |
| POST | `/expiry` | [Expiry dates](./symbol-services/expiry.md) |
| GET | `/instruments` | [Instrument master](./symbol-services/instruments.md) |

### Options Analytics

| Method | Path | Documentation |
|---|---|---|
| POST | `/optionsymbol` | [Resolve option symbol](./options-services/optionsymbol.md) |
| POST | `/optionchain` | [Option chain](./options-services/optionchain.md) |
| POST | `/syntheticfuture` | [Synthetic future](./options-services/syntheticfuture.md) |
| POST | `/optiongreeks` | [Option Greeks](./options-services/optiongreeks.md) |
| POST | `/multioptiongreeks` | [Batch option Greeks](./options-services/multioptiongreeks.md) |

### Calendar, Analyzer, And Preferences

| Method | Path | Documentation |
|---|---|---|
| POST | `/market/holidays` | [Market holidays](./market-calendar/holidays.md) |
| POST | `/market/timings` | [Market timings](./market-calendar/timings.md) |
| POST | `/analyzer` | [Analyzer status](./analyzer-services/analyzerstatus.md) |
| POST | `/analyzer/toggle` | [Toggle analyzer mode](./analyzer-services/analyzertoggle.md) |
| POST | `/pnl/symbols` | [Sandbox P&L by symbol](./analyzer-services/pnlsymbols.md) |
| GET | `/chart` | [Read chart preferences](./chart-services/chart.md) |
| POST | `/chart` | [Update chart preferences](./chart-services/chart.md) |
| POST | `/ping` | [Authenticated ping](./utility-services/ping.md) |

There is no public `/api/v1/checkholiday` endpoint. Use `/market/timings` for a date; its response identifies holiday/closed sessions through the returned market schedule.

### Messaging

| Method | Path | Documentation |
|---|---|---|
| GET, POST | `/telegram/config` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/telegram/start` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/telegram/stop` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/telegram/webhook` | [Telegram REST surface](./telegram-services/README.md) |
| GET | `/telegram/users` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/telegram/broadcast` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/telegram/notify` | [Telegram REST surface](./telegram-services/README.md) |
| GET | `/telegram/stats` | [Telegram REST surface](./telegram-services/README.md) |
| GET, POST | `/telegram/preferences` | [Telegram REST surface](./telegram-services/README.md) |
| POST | `/whatsapp/notify` | [WhatsApp notification](./whatsapp-services/notify.md) |

The Telegram resource contributes 11 method/path pairs. Its webhook acknowledges validated updates but does not yet dispatch them, and the REST broadcast handler currently returns zero delivery counts. Those limitations are documented on the Telegram page.

## WebSocket Protocol

WebSocket streaming is not mounted below `/api/v1`. Clients connect to the proxy on port `8765`, authenticate, and send action messages.

| Mode | Documentation |
|---|---|
| LTP | [LTP subscription](./websocket-streaming/ltp.md) |
| Quote | [Quote subscription](./websocket-streaming/quote.md) |
| Depth | [Depth subscription](./websocket-streaming/depth.md) |
| Order Updates | [Order-update stream](./websocket-streaming/order-updates.md) |

Supported actions are `authenticate`, `subscribe`, `unsubscribe`, `unsubscribe_all`, `subscribe_orders`, `unsubscribe_orders`, `get_broker_info`, `get_supported_brokers`, and `ping`.

## Order Constants

### Exchanges

`NSE`, `BSE`, `NFO`, `BFO`, `CDS`, `BCD`, `MCX`, `NCDEX`, `NCO`, `NSE_INDEX`, `BSE_INDEX`, `MCX_INDEX`, `GLOBAL_INDEX`, and `CRYPTO` are recognized by the shared validation constants. Broker capability metadata determines which subset is usable for the active broker.

### Products And Price Types

| Kind | Values |
|---|---|
| Product | `MIS`, `CNC`, `NRML` |
| Price type | `MARKET`, `LIMIT`, `SL`, `SL-M` |
| Action | `BUY`, `SELL` (lowercase is normalized by order schemas) |

Regular order, smart-order, basket, split, and modify schemas accept numeric quantities. Fractional quantities are allowed only for `CRYPTO`; non-crypto quantities must be whole numbers. Options order quantities remain positive integers.

## Response And Status Conventions

Most JSON resources return `status: "success"` or `status: "error"`, but broker payloads are normalized only at the wrapper level and some resources intentionally return CSV, plain text, or an empty webhook acknowledgement. Treat each endpoint page as authoritative for its payload.

Common status codes are:

| Code | Meaning |
|---|---|
| 200 | Request handled successfully |
| 400 | Invalid JSON, schema validation failure, unsupported mode, or invalid request state |
| 401 | Missing or invalid authentication on endpoints that use 401 |
| 403 | Invalid API key or operation blocked by mode/policy |
| 404 | Broker module, symbol, order, or linked messaging user not found |
| 429 | Flask-Limiter rejected the request |
| 500 | Unhandled internal or broker error |

## Rate Limits

Defaults from `.sample.env` are `API_RATE_LIMIT="50 per second"`, `ORDER_RATE_LIMIT="10 per second"`, and `SMART_ORDER_RATE_LIMIT="10 per second"`. Some messaging endpoints use their own limiter. All values are deployment configuration and may contain compound semicolon-separated limits. See [rate limiting](./rate-limiting.md).

## Client Libraries

The Python client is available as `openalgo` and is pinned by this application at `2.0.2`. Go and Node.js examples in `examples/` demonstrate direct REST integration; they are not declared here as separately versioned official SDK releases.
