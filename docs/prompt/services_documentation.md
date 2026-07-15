# OpenAlgo Internal Service Layer Reference

## Purpose and scope

This document is prompt-ready reference material for building OpenAlgo features
that import and call the internal Python modules in `services/`. The service
folder is the primary scope and source contract. REST and blueprint mappings are
included only to identify existing callers and integration patterns.

This is not an SDK guide. Internal feature code should import service functions,
classes, and singleton accessors directly instead of making HTTP calls back into
the same OpenAlgo process. The document does not replace request schemas in
[`docs/api`](../api/README.md) when a service also has a public endpoint.

The current service layer contains 71 Python modules under `services/`. Some
services back REST endpoints, while others run internal workflows, schedulers,
streaming, analytics, alerts, or risk management. Do not assume that every
service:

- has a public REST endpoint;
- accepts the same arguments as the OpenAlgo SDK;
- supports both API-key and direct broker authentication; or
- returns the standard three-item service tuple.

The Flask-RESTX API is mounted at `/api/v1`. Interactive Swagger documentation
is intentionally disabled by `doc=False` in `restx_api/__init__.py`.

## Sources of truth

Use these sources in this order when implementation and documentation differ:

1. The target function in `services/*.py`.
2. Its caller and request model in `restx_api/*.py` or `blueprints/*.py`.
3. Broker capability code in `broker/<broker>/api/`.
4. The endpoint documentation in [`docs/api`](../api/README.md).
5. This prompt reference.

Related references:

- [Service-layer design](../design/27-service-layer/README.md)
- [EventBus design](../design/53-event-bus/README.md)
- [Order constants](order-constants.md)
- [Symbol format](symbol-format.md)
- [Flow import format](flow-import-format.md)

## Architecture

```text
REST or blueprint layer
        |
        v
services/ business logic
        |
        +-- database/ persistence and API-key lookup
        +-- broker/<broker>/api/ live broker adapters
        +-- sandbox/ simulated execution
        +-- EventBus asynchronous side effects
        +-- WebSocket/ZMQ market-data infrastructure
```

The HTTP layer validates and transforms requests. The service layer owns
business rules, authentication resolution, analyzer routing, dynamic broker
dispatch, and normalized responses. Broker modules own broker-specific request
and response translation.

## Common contracts

### Standard return tuple

Most REST-backed service entry points return:

```python
success, response, status_code = service_function(...)
```

- `success`: `bool`
- `response`: response dictionary containing `status` and either data or an
  error `message`
- `status_code`: integer HTTP status

Do not apply this contract blindly. Important exceptions include:

- `get_instruments(...)`, which returns `(success, payload, status_code,
  headers)` to support JSON and CSV downloads;
- alert and bot methods, which commonly return booleans or service-specific
  reports;
- scheduler, streaming, cache, analytics, and orchestration services, which
  use domain-specific return values.

### Authentication modes

Many broker-facing services accept either:

```python
api_key="<openalgo-api-key>"
```

or direct internal credentials:

```python
auth_token="<broker-auth-token>", broker="<broker-plugin-name>"
```

API-key calls resolve the user, broker, auth token, and where required the feed
token from the database. Direct calls must provide the credential set expected
by the function. Database-only services such as search, expiry, instruments,
chart preferences, and market-calendar lookup do not share the full dual-auth
contract.

### Order modes

- `auto`: eligible orders execute immediately.
- `semi_auto`: queueable order types may be stored for Action Center approval.
- analyzer/sandbox mode: supported operations route to `sandbox_service.py`
  instead of a live broker.

Action Center's approved-order executor currently dispatches `placeorder`,
`smartorder`, `basketorder`, `splitorder`, `optionsorder`,
`optionsmultiorder`, and `placegttorder`. Multi-order results are tracked from
their child order IDs. GTT results are tracked by `trigger_id`; the existing
broker capability gate returns `501` when the active broker has no GTT module.
Only Dhan and Zerodha currently provide `broker/<broker>/api/gtt_api.py`.

The pending database row is authoritative. `queue_order(...)` returns success
after the row commits even if the best-effort Socket.IO notification fails; the
notification error is logged without creating a false 500 response.

Order services publish typed EventBus events for asynchronous logging,
Socket.IO updates, and configured alert delivery. A successful return does not
mean every asynchronous subscriber has completed.

### Internal integration rules

1. Import from `services.<module>`, not from `restx_api` or a Flask blueprint.
2. Call the top-level facade, not a `*_with_auth` helper, unless the feature
   deliberately owns already-resolved broker credentials and the helper is the
   established caller contract.
3. Pass the OpenAlgo API key when the facade needs user, broker, analyzer, or
   Action Center context. Do not substitute a Flask session username.
4. Use the existing singleton accessor for market data, Flow monitoring,
   schedulers, WebSocket clients, and scalping risk monitoring.
5. Do not create a new thread pool for order side effects. Publish through the
   existing EventBus or call the established alert service.
6. Treat `(success, response, status_code)` as a service result, not as a Flask
   response. Convert it at the blueprint or resource boundary.
7. Never log API keys, auth tokens, feed tokens, or attachment paths.
8. Verify sandbox and semi-auto routing before adding a new execution service.
9. Add tests at the service boundary so features can be tested without HTTP.

## Core internal service facades

These are the main stateless or request-scoped functions used by OpenAlgo
features. Import the function from the listed `services` module. The REST path
column identifies an existing caller when one exists; it does not mean internal
code should make an HTTP request. The active API currently contains 57
method/path pairs.

### Orders and GTT

| REST path | Service entry point | File |
|---|---|---|
| `POST /api/v1/placeorder` | `place_order(...)` | `services/place_order_service.py` |
| `POST /api/v1/placesmartorder` | `place_smart_order(...)` | `services/place_smart_order_service.py` |
| `POST /api/v1/optionsorder` | `place_options_order(...)` | `services/place_options_order_service.py` |
| `POST /api/v1/optionsmultiorder` | `place_options_multiorder(...)` | `services/options_multiorder_service.py` |
| `POST /api/v1/basketorder` | `place_basket_order(...)` | `services/basket_order_service.py` |
| `POST /api/v1/splitorder` | `split_order(...)` | `services/split_order_service.py` |
| `POST /api/v1/modifyorder` | `modify_order(...)` | `services/modify_order_service.py` |
| `POST /api/v1/cancelorder` | `cancel_order(...)` | `services/cancel_order_service.py` |
| `POST /api/v1/cancelallorder` | `cancel_all_orders(...)` | `services/cancel_all_order_service.py` |
| `POST /api/v1/closeposition` | `close_position(...)` | `services/close_position_service.py` |
| `POST /api/v1/placegttorder` | `place_gtt_order(...)` | `services/place_gtt_order_service.py` |
| `POST /api/v1/modifygttorder` | `modify_gtt_order(...)` | `services/modify_gtt_order_service.py` |
| `POST /api/v1/cancelgttorder` | `cancel_gtt_order(...)` | `services/cancel_gtt_order_service.py` |
| `POST /api/v1/gttorderbook` | `get_gtt_orderbook(...)` | `services/gtt_orderbook_service.py` |

GTT support is broker-dependent. The GTT services return `501` when a broker
does not provide the required `gtt_api` capability.

### Order and account information

| REST path | Service entry point | File |
|---|---|---|
| `POST /api/v1/orderstatus` | `get_order_status(...)` | `services/orderstatus_service.py` |
| `POST /api/v1/openposition` | `get_open_position(...)` | `services/openposition_service.py` |
| `POST /api/v1/orderbook` | `get_orderbook(...)` | `services/orderbook_service.py` |
| `POST /api/v1/tradebook` | `get_tradebook(...)` | `services/tradebook_service.py` |
| `POST /api/v1/positionbook` | `get_positionbook(...)` | `services/positionbook_service.py` |
| `POST /api/v1/holdings` | `get_holdings(...)` | `services/holdings_service.py` |
| `POST /api/v1/funds` | `get_funds(...)` | `services/funds_service.py` |
| `POST /api/v1/margin` | `calculate_margin(...)` | `services/margin_service.py` |
| `POST /api/v1/ping` | `get_ping(...)` | `services/ping_service.py` |

### Market data and symbols

| REST path | Service entry point | File |
|---|---|---|
| `POST /api/v1/quotes` | `get_quotes(...)` | `services/quotes_service.py` |
| `POST /api/v1/multiquotes` | `get_multiquotes(...)` | `services/quotes_service.py` |
| `POST /api/v1/depth` | `get_depth(...)` | `services/depth_service.py` |
| `POST /api/v1/history` | `get_history(...)` | `services/history_service.py` |
| `POST /api/v1/intervals` | `get_intervals(...)` | `services/intervals_service.py` |
| `POST /api/v1/symbol` | `get_symbol_info(...)` | `services/symbol_service.py` |
| `POST /api/v1/search` | `search_symbols(...)` | `services/search_service.py` |
| `POST /api/v1/expiry` | `get_expiry_dates(...)` | `services/expiry_service.py` |
| `GET /api/v1/instruments` | `get_instruments(...)` | `services/instruments_service.py` |

`get_quotes`, `get_multiquotes`, `get_depth`, and `get_history` support an
internal `feed_token` argument. `get_history` accepts `source="api"` for broker
history or `source="db"` for DuckDB/Historify history.

### Options analytics

| REST path | Service entry point | File |
|---|---|---|
| `POST /api/v1/optionsymbol` | `get_option_symbol(...)` | `services/option_symbol_service.py` |
| `POST /api/v1/optionchain` | `get_option_chain(...)` | `services/option_chain_service.py` |
| `POST /api/v1/optiongreeks` | `get_option_greeks(...)` | `services/option_greeks_service.py` |
| `POST /api/v1/multioptiongreeks` | `get_multi_option_greeks(...)` | `services/option_greeks_service.py` |
| `POST /api/v1/syntheticfuture` | `calculate_synthetic_future(...)` | `services/synthetic_future_service.py` |

### Calendar, analyzer, and chart preferences

| REST path | Service entry point | File |
|---|---|---|
| `POST /api/v1/market/holidays` | `get_holidays(...)` | `services/market_calendar_service.py` |
| `POST /api/v1/market/timings` | `get_timings(...)` | `services/market_calendar_service.py` |
| `POST /api/v1/analyzer` | `get_analyzer_status(...)` | `services/analyzer_service.py` |
| `POST /api/v1/analyzer/toggle` | `toggle_analyzer_mode(...)` | `services/analyzer_service.py` |
| `GET /api/v1/chart` | `get_chart_preferences(...)` | `services/chart_service.py` |
| `POST /api/v1/chart` | `update_chart_preferences(...)` | `services/chart_service.py` |

`check_holiday(date_str, exchange=None)` remains an internal helper in
`market_calendar_service.py`; there is no `/api/v1/checkholiday` REST endpoint.

### REST resources without a conventional facade

| REST surface | Implementation |
|---|---|
| `POST /api/v1/pnl/symbols` | Uses `sandbox_get_pnl_symbols(...)`; available only for analyzer data. |
| `GET /api/v1/ticker/<symbol>` | Implemented directly in `restx_api/ticker.py`. |
| `/api/v1/telegram/*` | Uses `TelegramBotService` and `TelegramAlertService`. |
| `POST /api/v1/whatsapp/notify` | Uses `WhatsAppBotService` and `WhatsAppAlertService`. |

The Telegram namespace has 11 method/path pairs covering config, start, stop,
webhook, users, broadcast, notify, stats, and preferences. WhatsApp exposes only
the send-only `notify` API publicly; device pairing and lifecycle management are
session-authenticated web operations.

## Exact callable signatures

These signatures are copied from the current service definitions. Internal
`*_with_auth` helpers are deliberately omitted.

### Order execution

```python
place_order(order_data, api_key=None, auth_token=None, broker=None,
            emit_event=True, prefetched_quote=None)
place_smart_order(order_data, api_key=None, auth_token=None, broker=None)
place_options_order(options_data, api_key=None, auth_token=None, broker=None)
place_options_multiorder(multiorder_data, api_key=None, auth_token=None, broker=None)
place_basket_order(basket_data, api_key=None, auth_token=None, broker=None)
split_order(split_data, api_key=None, auth_token=None, broker=None)
modify_order(order_data, api_key=None, auth_token=None, broker=None)
cancel_order(orderid, api_key=None, auth_token=None, broker=None)
cancel_all_orders(order_data=None, api_key=None, auth_token=None, broker=None)
close_position(position_data=None, api_key=None, auth_token=None, broker=None)
```

### GTT

```python
place_gtt_order(order_data, api_key=None, auth_token=None, broker=None)
modify_gtt_order(order_data, api_key=None, auth_token=None, broker=None)
cancel_gtt_order(trigger_id, api_key=None, auth_token=None, broker=None,
                 strategy=None)
get_gtt_orderbook(api_key=None, auth_token=None, broker=None)
```

### Order and account queries

```python
get_order_status(status_data, api_key=None, auth_token=None, broker=None)
get_open_position(position_data, api_key=None, auth_token=None, broker=None)
get_orderbook(api_key=None, auth_token=None, broker=None)
get_tradebook(api_key=None, auth_token=None, broker=None)
get_positionbook(api_key=None, auth_token=None, broker=None)
get_holdings(api_key=None, auth_token=None, broker=None)
get_funds(api_key=None, auth_token=None, broker=None)
calculate_margin(margin_data, api_key=None, auth_token=None, broker=None)
get_ping(api_key=None, auth_token=None, broker=None)
```

### Market data and symbols

```python
get_quotes(symbol, exchange, api_key=None, auth_token=None, feed_token=None,
           broker=None)
get_multiquotes(symbols, api_key=None, auth_token=None, feed_token=None,
                broker=None)
get_depth(symbol, exchange, api_key=None, auth_token=None, feed_token=None,
          broker=None, user_id=None)
get_history(symbol, exchange, interval, start_date, end_date, api_key=None,
            auth_token=None, feed_token=None, broker=None, source="api")
get_intervals(api_key=None, auth_token=None, broker=None)
get_symbol_info(symbol, exchange, api_key=None, auth_token=None, broker=None)
search_symbols(query, exchange=None, api_key=None)
get_expiry_dates(symbol, exchange, instrumenttype, api_key=None)
get_instruments(exchange=None, api_key=None, format="json")
```

### Options, calendar, analyzer, and preferences

```python
get_option_symbol(underlying, exchange, expiry_date, strike_int, offset,
                  option_type, api_key, underlying_ltp=None)
get_option_chain(underlying, exchange, expiry_date, strike_count, api_key,
                 with_quotes=True)
get_option_greeks(option_symbol, exchange, interest_rate=None,
                  forward_price=None, underlying_symbol=None,
                  underlying_exchange=None, expiry_time=None, api_key=None)
get_multi_option_greeks(symbols, interest_rate=None, expiry_time=None,
                        api_key=None)
calculate_synthetic_future(underlying, exchange, expiry_date, api_key)
get_holidays(year=None)
get_timings(date_str)
check_holiday(date_str, exchange=None)  # internal only; no REST route
get_analyzer_status(analyzer_data, api_key=None, auth_token=None, broker=None)
toggle_analyzer_mode(analyzer_data, api_key=None, auth_token=None, broker=None)
get_chart_preferences(api_key)
update_chart_preferences(api_key, data)
```

## Payload rules

Do not duplicate request schemas from memory. Read the corresponding
`restx_api` model before constructing a payload. Common order fields include:

| Field | Meaning |
|---|---|
| `strategy` | Caller-defined strategy label. |
| `symbol` | OpenAlgo trading symbol. |
| `exchange` | Canonical exchange code from `utils/constants.py`. |
| `action` | `BUY` or `SELL`. |
| `pricetype` | `MARKET`, `LIMIT`, `SL`, or `SL-M`. |
| `product` | Product supported by the selected exchange and broker. |
| `quantity` | Positive order quantity. |
| `price` | Required by price types which need a limit price. |
| `trigger_price` | Required by stop-loss price types and by modify-order validation. |
| `disclosed_quantity` | Included in order and modify-order validation where required. |

Options, multi-leg, GTT, basket, split, and margin calls have additional nested
schemas. Use their `restx_api` models and `docs/api` pages rather than extending
the generic table above.

## Internal orchestration and stateful services

The following modules expose internal application APIs rather than simple REST
facades. Prefer their documented module-level functions, singleton accessors,
and lifecycle methods. Do not instantiate another scheduler, market-data cache,
or risk monitor when an accessor already owns the process-wide instance.

### Execution, approval, and sandbox

| Files | Responsibility |
|---|---|
| `order_router_service.py` | Decides whether an eligible API-key order queues in semi-auto mode. |
| `action_center_service.py` | Parses pending orders and calculates Action Center views/statistics. |
| `pending_order_execution_service.py` | Dispatches approved pending orders. |
| `sandbox_service.py` | Simulated orders, books, funds, P&L symbols, and square-off controls. |
| `broker_keepalive_service.py` | Starts broker-session keepalive behavior where configured. |
| `order_update_service.py` | Lifecycle of the always-on per-broker-session order-update adapter (broker order-WS / polling ingestion → `OrderUpdateEvent` → socketio + websocket_proxy relay). |

Primary internal entry points:

```python
parse_pending_order(pending_order)
calculate_action_center_stats(orders_list)
get_action_center_data(user_id, status_filter=None)

should_route_to_pending(api_key, api_type=None)
queue_order(api_key, order_data, api_type)
execute_approved_order(pending_order_id)

is_sandbox_mode()
sandbox_place_order(order_data, api_key, original_data, prefetched_quote=None)
sandbox_modify_order(order_data, api_key, original_data)
sandbox_cancel_order(order_data, api_key, original_data)
sandbox_get_orderbook(api_key, original_data)
sandbox_get_order_status(order_data, api_key, original_data)
sandbox_get_positions(api_key, original_data)
sandbox_get_holdings(api_key, original_data)
sandbox_get_tradebook(api_key, original_data)
sandbox_get_funds(api_key, original_data)
sandbox_close_position(position_data, api_key, original_data)
sandbox_place_smart_order(order_data, api_key, original_data)
sandbox_cancel_all_orders(order_data, api_key, original_data)
sandbox_reload_squareoff_schedule()
sandbox_get_squareoff_status()
sandbox_get_pnl_symbols(api_key, original_data)

start_broker_keepalive()

start_order_update_adapter(user_id, broker)
stop_order_update_adapter(user_id)
start_order_update_adapters_on_boot()
stop_all_order_update_adapters()
get_order_update_status()
```

`order_update_service` owns one always-on adapter per broker session
(never per WebSocket client). It is started at app startup for an existing
session and restarted/stopped by `database.auth_db.upsert_auth` on a real
token change or revoke — do not start adapters from feature code. Brokers
without a push feed use `websocket_proxy.order_adapter.PollingOrderUpdateAdapter`
automatically. Disable globally with `ORDER_UPDATES_ENABLED=FALSE`.

Feature code normally calls the public order facade and lets it select the
sandbox or Action Center path. Direct sandbox calls are appropriate for sandbox
administration and analyzer-only features, not as a replacement for the normal
order facade.

### Flow automation

| Files | Responsibility |
|---|---|
| `flow_executor_service.py` | Executes workflow nodes and maintains workflow context. |
| `flow_openalgo_client.py` | Internal client facade used by Flow nodes. |
| `flow_scheduler_service.py` | APScheduler-backed workflow schedules. |
| `flow_price_monitor_service.py` | In-process price-condition alerts for flows. |

See [Flow import format](flow-import-format.md) for supported node JSON.

Primary internal entry points:

```python
execute_workflow(workflow_id, webhook_data=None, api_key=None)
get_workflow_lock(workflow_id)
get_flow_client(api_key)

get_flow_price_monitor()
FlowPriceMonitor.add_alert(workflow_id, symbol, exchange, condition,
                           target_price, price_lower=None, price_upper=None,
                           percentage=None, api_key=None)
FlowPriceMonitor.remove_alert(workflow_id)
FlowPriceMonitor.get_alert(workflow_id)
FlowPriceMonitor.get_status()
FlowPriceMonitor.shutdown()

init_flow_scheduler(db_url=None, api_key=None)
get_flow_scheduler()
execute_workflow_scheduled(workflow_id, api_key=None)
FlowScheduler.add_workflow_job(workflow_id, schedule_type, time_str="09:15",
                               days=None, execute_at=None,
                               interval_value=None, interval_unit=None,
                               func=None)
FlowScheduler.remove_workflow_job(workflow_id)
FlowScheduler.pause_job(job_id)
FlowScheduler.resume_job(job_id)
FlowScheduler.shutdown()
```

`FlowOpenAlgoClient`, returned by `get_flow_client(api_key)`, is the preferred
Flow-facing facade. Its current operation families are:

```text
Orders: place_order, place_smart_order, modify_order, cancel_order,
        cancel_all_orders, close_all_positions, close_position, basket_order,
        split_order, options_order, options_multi_order
Data:   get_quotes, get_multi_quotes, get_depth, get_history, get_order_status,
        orderbook, tradebook, positionbook, holdings, funds, get_open_position
Lookup: symbol, search_symbols, get_expiry, get_intervals, optionchain,
        optionsymbol, syntheticfuture, get_option_greeks
Other:  holidays, timings, margin, telegram
```

Node execution belongs in `NodeExecutor` and `execute_node_chain(...)`. New Flow
node types must be added to the executor dispatch and to the Flow import schema;
adding a method only to `FlowOpenAlgoClient` does not make a node executable.

### Historify

| Files | Responsibility |
|---|---|
| `historify_service.py` | Watchlists, downloads, catalog, exports, uploads, F&O discovery, and background jobs. |
| `historify_scheduler_service.py` | Persistent Historify schedules and scheduled execution. |

Primary data and catalog entry points:

```python
get_watchlist()
add_to_watchlist(symbol, exchange, display_name=None)
remove_from_watchlist(symbol, exchange)
bulk_add_to_watchlist(symbols)
bulk_remove_from_watchlist(symbols)

download_data(symbol, exchange, interval, start_date, end_date, api_key)
download_watchlist_data(interval, start_date, end_date, api_key)
get_chart_data(symbol, exchange, interval, start_date=None, end_date=None)
get_data_catalog()
get_symbol_data_info(symbol, exchange, interval=None)
get_supported_timeframes(api_key)
get_historify_intervals()
get_exchanges()
get_stats()

export_data_to_csv(output_dir, symbol=None, exchange=None, interval=None,
                   start_date=None, end_date=None)
get_export_dataframe(symbol, exchange, interval, start_date=None,
                     end_date=None)
upload_csv_data(file_path, symbol, exchange, interval)
upload_parquet_data(file_path, symbol, exchange, interval)
delete_symbol_data(symbol, exchange, interval=None)
bulk_delete_symbol_data(symbols)
```

Primary discovery and job entry points:

```python
get_fno_underlyings(exchange=None)
get_fno_expiries(underlying, exchange="NFO", instrumenttype=None)
get_fno_chain(underlying, exchange="NFO", expiry=None, instrumenttype=None,
              strike_min=None, strike_max=None, limit=1000)
get_futures_chain(underlying, exchange="NFO")
get_option_chain_symbols(underlying, exchange="NFO", expiry=None,
                         strike_min=None, strike_max=None)

create_and_start_job(job_type, symbols, interval, start_date, end_date, api_key,
                     config=None, incremental=False)
get_job_status(job_id)
get_all_jobs(status=None, limit=50)
cancel_job(job_id)
pause_job(job_id)
resume_job(job_id)
delete_job(job_id)
retry_failed_items(job_id, api_key)
cleanup_zombie_jobs()
```

Scheduler entry points:

```python
init_historify_scheduler(db_url=None, api_key=None, socketio=None)
get_historify_scheduler()
execute_schedule(schedule_id, api_key=None)
HistorifyScheduler.add_schedule(schedule_id, name, schedule_type,
                                data_interval, interval_value=None,
                                interval_unit=None, time_of_day=None,
                                lookback_days=1, description=None)
HistorifyScheduler.update_schedule(schedule_id, **kwargs)
HistorifyScheduler.enable_schedule(schedule_id)
HistorifyScheduler.disable_schedule(schedule_id)
HistorifyScheduler.trigger_schedule(schedule_id)
HistorifyScheduler.delete_schedule(schedule_id)
```

Initialize Historify and its scheduler through application startup. Feature
code should retrieve the initialized scheduler rather than creating a second
instance.

### Streaming and market-data state

| Files | Responsibility |
|---|---|
| `market_data_service.py` | Validated in-memory market-data cache, health state, and priority subscribers. |
| `websocket_service.py` | Per-user broker WebSocket subscriptions and cached data access. |
| `websocket_client.py` | Client for the OpenAlgo WebSocket proxy. |

The WebSocket client and server interfaces do not use the standard REST service
tuple. Subscription mode and symbol validation must match the WebSocket
protocol documentation.

Process-wide market-data access:

```python
get_market_data_service()
get_ltp(symbol, exchange)
get_ltp_value(symbol, exchange)
get_quote(symbol, exchange)
get_market_depth(symbol, exchange)
subscribe_to_market_updates(event_type, callback, filter_symbols=None)
subscribe_critical(callback, filter_symbols=None, name="")
unsubscribe_from_market_updates(subscriber_id)
is_data_fresh(symbol=None, exchange=None, max_age_seconds=30)
is_trade_management_safe()
get_health_status()
```

Use `subscribe_critical(...)` for risk-management callbacks. Store the returned
subscriber ID and unsubscribe it during feature shutdown.

Per-user WebSocket service access:

```python
get_websocket_connection(username)
get_websocket_status(username, broker=None)
get_websocket_subscriptions(username, broker=None)
subscribe_to_symbols(username, broker, symbols, mode="Quote")
unsubscribe_from_symbols(username, broker, symbols, mode="Quote")
unsubscribe_all(username, broker)
get_market_data(username, symbol=None, exchange=None)
register_market_data_callback(username, callback)
```

Proxy client access:

```python
client = get_websocket_client(api_key, host="localhost", port=8765)
client.connect()
client.subscribe(symbols, mode="Quote")
client.register_callback(event_type, callback)
client.unsubscribe(symbols, mode="Quote")
client.disconnect()
close_all_clients()
```

### Options and chart analytics

| Files | Responsibility |
|---|---|
| `arbitrage_service.py` | Cross-exchange arbitrage universe. |
| `custom_straddle_service.py` | Custom straddle simulation. |
| `gamma_density_service.py` | Gamma-density calculation. |
| `gex_service.py` | Gamma-exposure data. |
| `iv_chart_service.py` | Historical IV chart data. |
| `iv_smile_service.py` | IV smile data. |
| `multi_strike_oi_service.py` | Multi-strike open-interest series. |
| `oi_profile_service.py` | Open-interest profile. |
| `oi_tracker_service.py` | OI tracking and max-pain calculation. |
| `straddle_chart_service.py` | Straddle chart series. |
| `strategy_chart_service.py` | Multi-leg strategy chart series. |
| `vol_surface_service.py` | Multi-expiry volatility surface. |

These services are primarily called by authenticated application blueprints,
not by the `/api/v1` namespace.

Primary analytics entry points:

```python
get_arbitrage_universe(exchanges=DEFAULT_EXCHANGES, api_key=None)
get_custom_straddle_simulation(underlying, exchange, expiry_date, interval,
                               api_key, days=1, adjustment_points=50,
                               lot_size=65, lots=1)
calculate_gamma_density(underlying, exchange, expiry_date, api_key,
                        interest_rate=None)
get_gex_data(underlying, exchange, expiry_date, api_key)
get_iv_chart_data(underlying, exchange, expiry_date, interval, api_key, days=1)
get_default_symbols(underlying, exchange, expiry_date, api_key)
get_iv_smile_data(underlying, exchange, expiry_date, api_key)
get_multi_strike_oi_data(underlying, exchange, legs, interval, api_key, days=5)
get_oi_profile_data(underlying, exchange, expiry_date, interval, days, api_key)
get_oi_data(underlying, exchange, expiry_date, api_key)
calculate_max_pain(underlying, exchange, expiry_date, api_key)
get_straddle_chart_data(underlying, exchange, expiry_date, interval, api_key,
                        days=5)
get_strategy_chart_data(underlying, exchange, legs, interval, api_key, days=5)
get_vol_surface_data(underlying, exchange, expiry_dates, strike_count, api_key)
```

These functions can make multiple history, quote, option-chain, or symbol
lookups. Do not call them from a request loop without checking their existing
caching and workload characteristics.

### Scalping and risk

`scalping_risk_monitor_service.py` manages the background risk monitor for the
scalping terminal. It evaluates stop-loss, target, and trailing state from live
market data. Treat its singleton lifecycle and synchronization methods as
application infrastructure, not as public API helpers.

```python
evaluate_trail(state, ltp)
get_scalping_risk_monitor()
start_scalping_risk_monitor()
notify_sl_changed()

ScalpingRiskMonitor.start()
ScalpingRiskMonitor.request_sync()
ScalpingRiskMonitor.sync()
ScalpingRiskMonitor.stop()
ScalpingRiskMonitor.is_running()
```

Use `start_scalping_risk_monitor()` during application lifecycle integration
and `get_scalping_risk_monitor()` elsewhere. Do not create a separate monitor
inside a feature blueprint.

### Telegram and WhatsApp

| Files | Responsibility |
|---|---|
| `telegram_alert_service.py` | Formats and dispatches order/broadcast alerts. |
| `telegram_bot_service.py` | Active Telegram bot lifecycle and commands. |
| `whatsapp_alert_service.py` | Formats and dispatches WhatsApp order/broadcast alerts. |
| `whatsapp_bot_service.py` | Active WhatsApp pairing state, commands, and synchronous sends. |

`telegram_bot_service_fixed.py` and `telegram_bot_service_v2.py` are not the
active imports used by `app.py`, the REST namespace, or the Telegram blueprint.
Do not select them for new integrations.

Alert-service entry points:

```python
telegram_alert_service.send_order_alert(order_type, order_data, response,
                                        api_key=None)
telegram_alert_service.send_broadcast_alert(message, filters=None)
telegram_alert_service.toggle_alerts(enabled)

whatsapp_alert_service.send_order_alert(order_type, order_data, response,
                                        api_key=None)
whatsapp_alert_service.send_broadcast_alert(message, filters=None)
whatsapp_alert_service.toggle_alerts(enabled)
```

Bot-service entry points:

```python
await telegram_bot_service.initialize_bot(token)
# Synchronous startup wrapper:
telegram_bot_service.initialize_bot_sync(token)
telegram_bot_service.start_bot()
telegram_bot_service.stop_bot()
await telegram_bot_service.send_notification(telegram_id, message)
await telegram_bot_service.broadcast_message(message, filters=None)

whatsapp_bot_service.get_pair_state()
whatsapp_bot_service.start_pair(phone=None, owner_user_id=None,
                                owner_username=None)
whatsapp_bot_service.start_bot()
whatsapp_bot_service.stop_bot()
whatsapp_bot_service.unlink()
whatsapp_bot_service.send_sync(to=None, text=None, image=None, document=None,
                               caption=None, filename=None)
```

WhatsApp `send_sync(...)` returns a per-recipient report. The public notify API
defaults `wait_for_delivery` to `true`; callers must explicitly set it to
`false` for fire-and-forget queuing.

## Reusable lower-level helpers

These functions are useful for internal features that need behavior below the
main service facade.

```python
# History and Flow
get_history_from_db(symbol, exchange, interval, start_date, end_date)
parse_time_string(time_str, default_hour=9, default_minute=15)

# Historify lifecycle and metadata
validate_symbol(symbol, exchange)
initialize_historify()
enrich_and_save_metadata(symbols)
get_catalog_with_metadata_service()
get_catalog_grouped_service(group_by="underlying")

# Option-chain construction
get_strikes_with_labels(available_strikes, atm_strike, strike_count=None)
get_option_symbols_for_chain(base_symbol, expiry_date, strikes_with_labels,
                             exchange)

# Option-symbol construction and cache administration
get_strikes_cache_stats()
clear_strikes_cache()
parse_underlying_symbol(underlying)
get_atm_strike(ltp, strike_int)
calculate_offset_strike(atm_strike, offset, strike_int, option_type)
construct_option_symbol(base_symbol, expiry_date, strike, option_type)
construct_crypto_option_symbol(base_symbol, expiry_date, strike, option_type)
get_available_strikes(base_symbol, expiry_date, option_type, exchange)
find_atm_strike_from_actual(ltp, available_strikes)
calculate_offset_strike_from_actual(atm_strike, offset, option_type,
                                    available_strikes)
get_option_exchange(underlying_exchange)

# Option-Greeks calculation
check_opengreeks_availability()
parse_option_symbol(symbol, exchange, custom_expiry_time=None)
get_underlying_exchange(base_symbol, options_exchange)
calculate_time_to_expiry(expiry)
calculate_greeks(option_symbol, exchange, spot_price, option_price,
                 interest_rate=None, expiry_time=None, api_key=None)

# WhatsApp identity and attachment validation
normalize_phone(raw)
phone_to_jid(phone_digits)
jid_to_phone(jid)
validate_attachment_path(path)
```

The following public-named functions are implementation helpers, not stable
feature contracts: `import_broker_module`, `import_broker_gtt_module`,
`emit_analyzer_error`, response formatters, request validators,
`place_single_order`, `place_single_split_order`,
`place_single_split_order_for_leg`, and `resolve_and_place_leg`. Call the owning
facade unless the feature is explicitly changing that facade's implementation.

## Examples

### API-key order call

```python
from services.place_order_service import place_order

success, response, status_code = place_order(
    {
        "strategy": "Python",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "pricetype": "MARKET",
        "product": "MIS",
        "quantity": 1,
        "price": 0,
        "trigger_price": 0,
        "disclosed_quantity": 0,
    },
    api_key="<openalgo-api-key>",
)

if not success:
    raise RuntimeError(f"{status_code}: {response.get('message')}")
```

### Direct internal quote call

```python
from services.quotes_service import get_quotes

success, response, status_code = get_quotes(
    symbol="RELIANCE",
    exchange="NSE",
    auth_token="<broker-auth-token>",
    feed_token="<broker-feed-token>",
    broker="<broker-plugin-name>",
)
```

### Database-backed symbol search

```python
from services.search_service import search_symbols

success, response, status_code = search_symbols(
    query="NIFTY",
    exchange="NFO",
    api_key="<openalgo-api-key>",
)
```

## Change checklist

When adding or modifying a service:

1. Update the service function and its tests.
2. Update the corresponding `restx_api` model and resource if it is public.
3. Confirm API-key, direct-auth, sandbox, and semi-auto behavior separately.
4. Verify broker capability fallbacks and status codes.
5. Publish side effects through the established EventBus pattern.
6. Update `docs/api`, this prompt reference, Flow node support where relevant,
   and both REST and navigation inventories.
7. Recount method/path pairs from code; do not infer them from file counts.

---

**Last verified:** July 2026

**Version context:** current `main` service and REST implementation
