# 09 - REST API Architecture

## Registration

`restx_api/__init__.py` creates `api_v1_bp` with prefix `/api/v1` and registers 57 current method/path pairs across order, account, market-data, option, calendar, analyzer, preference, messaging, and utility namespaces.

The Flask-RESTX `Api` is configured with `doc=False`. Swagger/OpenAPI UI is intentionally disabled and there is no supported `/api/docs` route. The maintained external contract is [`docs/api/README.md`](../../api/README.md).

## Resource Pattern

Most resources follow this sequence:

```text
request JSON/query
  -> Marshmallow schema
  -> service call
  -> jsonify normalized wrapper
```

Schemas are split by domain:

| File | Scope |
|---|---|
| `restx_api/schemas.py` | Orders, options execution, margin, GTT |
| `restx_api/data_schemas.py` | Quotes, history, symbols, calendar, Greeks, instruments |
| `restx_api/account_schema.py` | Account, analyzer, ping, chart, P&L |

Unknown fields are excluded by most schemas. `ChartSchema` explicitly includes unknown fields because chart preferences are extensible.

## Authentication And CSRF

REST resources generally accept `apikey` in JSON for POST or query parameters for GET. Telegram and WhatsApp resources also support `X-API-KEY` on selected calls. The Telegram webhook uses its Telegram secret header.

`app.py` exempts the `/api/v1` blueprint from CSRF because these calls do not use the browser form/session trust boundary. API-key verification remains mandatory unless an endpoint has a separate external authentication contract.

## Rate-Limit Classes

| Class | Default | Examples |
|---|---|---|
| `API_RATE_LIMIT` | 50/second | Market data, account reads, chart, analyzer |
| `ORDER_RATE_LIMIT` | 10/second | Place/modify/cancel and options/GTT writes |
| `SMART_ORDER_RATE_LIMIT` | 10/second | Position-aware smart order |
| Endpoint-specific | Varies | Greeks, Telegram, WhatsApp, broadcast |

All are environment/configuration values; compound limits are supported.

## Mode Routing

- Live mode resolves `broker.<key>` modules through the active API-key session.
- Analyzer mode routes supported order/account operations to the sandbox engine.
- Analyzer GTT place/modify/cancel/orderbook is not implemented and returns 501.
- Semi-auto mode queues eligible execution in Action Center and blocks defined destructive operations.
- `/pnl/symbols` is analyzer-only.

## Validation Details

- Regular order quantity is numeric and positive. Fractional quantity is allowed only for `CRYPTO`; other exchanges are coerced to whole integers or rejected.
- Options execution quantity is a positive integer.
- Options multi-order accepts 1 to 20 legs.
- Multi-option Greeks accepts 1 to 50 symbols.
- Option-chain `strike_count`, when provided, is 1 to 100.
- History accepts `source=api` or `source=db`; `db` reads Historify.
- Instruments is GET and can return JSON or CSV.

## Response Boundaries

OpenAlgo normalizes wrapper status and core fields, but broker-specific payload data is not exhaustively identical for all 34 plugins. Some endpoints intentionally return CSV, plain text, or empty webhook acknowledgements. Clients must use the endpoint contract rather than assuming every response is `{status,data}`.

## Adding A Resource

1. Add or reuse a Marshmallow schema.
2. Put reusable behavior in `services/`, not the resource method.
3. Register the namespace in `restx_api/__init__.py`.
4. Add the method/path to `docs/api/README.md` and its endpoint page.
5. Add the row to `docs/bdd/rest_api_inventory.feature` and behavior scenarios where needed.
6. Add focused tests for validation, auth, mode routing, and response shape.
