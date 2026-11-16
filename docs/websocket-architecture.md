# OpenAlgo WebSockets and ZeroMQ

OpenAlgo shares a broker market-data feed between browser panels, internal services and external clients. A shared feed can contain several upstream broker WebSocket connections when connection pooling is enabled. Adding a client for an existing symbol/exchange/mode reuses that subscription instead of opening an independent broker session.

The [protocol reference](prompt/websockets-format.md) defines messages; the [quote-feed guide](websocket-quote-feed.md) provides a working integration example.

## Data path

```text
Broker market-data sockets (one or more in a shared pool)
    -> broker/<broker>/streaming/ adapter normalizes data
    -> ZeroMQ publishers CONNECT to the configured bus
    -> proxy SUB socket BINDS the bus (default 127.0.0.1:5555)
    -> WebSocket proxy (default :8765)
         -> browser clients
         -> external Python/JavaScript/etc. clients
         -> services/websocket_client.py in the Flask process
              -> services/websocket_service.py callbacks
              -> services/market_data_service.py cache and subscribers
```

ZeroMQ is an inter-process transport here, not an in-process-only bus. The proxy's SUB is the **only binder**. Broker PUB sockets, `SharedZmqPublisher` and the cache-invalidation publisher connect to it. `ZMQ_HOST` defaults to loopback and `ZMQ_PORT` to 5555. The port stays fixed: do not make publishers bind, scan for another port or mutate it at runtime. Otherwise a publisher and subscriber can end up on different ports while clients appear subscribed.

The bus is internal and unversioned. External integrations should use the authenticated WebSocket proxy, normally reverse-proxied to `wss://<domain>/ws` on an HTTPS installation.

## Where the proxy runs

`websocket_proxy/app_integration.py:resolve_proxy_mode()` selects the topology:

| Mode | Default context | Ownership |
|---|---|---|
| `subprocess` | Gunicorn, both eventlet and gthread | Flask starts and supervises a separate `python -m websocket_proxy.server` process |
| `external` | Docker / `APP_MODE=standalone` | `start.sh` starts a separate proxy process |
| `thread` | Development server (`uv run app.py`) | Proxy asyncio loop runs on a real OS thread |

A valid `WEBSOCKET_PROXY_MODE` explicitly overrides the default. Never start a second proxy for the same configured ports. The production Flask server still uses one Gunicorn worker; its caches, Socket.IO state and broker session are shared in that process. Internal services reach the proxy through `services/websocket_client.py`. The listener also calls `MarketDataService` directly in the proxy process. These caches are process-local instances, not shared memory: the Flask process's callback-fed cache can be separate from the proxy's own cache.

## Subscriptions and pooling

The proxy maintains an index keyed by `(symbol, exchange, mode)` with client owners. Requests for the same key share the upstream subscription. Releasing one client must preserve every other owner's feed. A last-owner unsubscribe removes local ownership only after an acknowledged adapter release; disconnect cleanup removes the dead session and tears down an unresolved last-client feed as needed. Flattrade and Shoonya may keep their adapter connected after an acknowledged `unsubscribe_all`.

With pooling enabled, `broker_factory.py` shares a `ConnectionPool` under `{broker}_{user_id}`. The pool counts unique symbols for capacity, tracks mode owners, and upgrades/downgrades upstream modes as required. Adapters must preserve the requested modes when sharing or upgrading a broker subscription. The proxy also fans a higher-mode publication to owners of lower modes, tagging the outgoing frame with each client's subscribed mode; a Quote/LTP client can therefore receive fields originating in a Depth publication. Broker protocol restrictions and supported instruments remain the adapter's responsibility.

| Setting | Default | Meaning |
|---|---|---|
| `ENABLE_CONNECTION_POOLING` | `true` | Wrap streaming adapters in the shared pool |
| `MAX_SYMBOLS_PER_WEBSOCKET` | `1000` | OpenAlgo symbol capacity per upstream connection |
| `MAX_WEBSOCKET_CONNECTIONS` | `3` | OpenAlgo maximum upstream connections per pool |

These are OpenAlgo ceilings, not broker entitlements. The pool is configured from these values; it does not automatically discover every broker's current account limits. Configure them within the broker's allowed symbol, connection and subscription budgets. Setting 1000 × 3 does not guarantee a broker accepts 3000 symbols. Broker depth levels are also independent of pool size.

Several login devices share one broker feed. Reusing unchanged broker tokens must not invalidate that feed; a real token change or revocation must invalidate adapters and pooled credentials. `database/auth_db.py:upsert_auth()` and `database/cache_invalidation.py` implement that distinction.

## Modes and available fields

| Wire mode | Label | Typical contents |
|---|---|---|
| `1` | `LTP` | Last traded price and timestamp |
| `2` | `Quote` | LTP and the quote fields the broker supplies |
| `3` | `Depth` | Order-book levels and available quote fields |

Requests accept numeric modes and case-insensitive labels; outbound market-data frames use numeric modes with values under `data`. Request `depth` selects a desired level count (default 5); the broker can reject unsupported depths or instruments.

Quote and Depth are not a guarantee of complete OHLCV, previous close, OI, buy/sell totals or order counts. Examples:

- Sahi's stream carries no OHLC or previous close, so those keys are omitted.
- Groww emits the available fields from its merged cache; its usual stream is LTP-only.
- Index streams may have price/OHLC but no tradable depth or volume. Zerodha index packets are parsed separately from equity packets; Fyers does not fabricate index depth.
- Fyers, Upstox, Kotak and other adapters can carry quote fields inside Depth frames when their feed supplies them. A field absent upstream must not be reconstructed as an invented price or quantity.

Use optional lookups and distinguish missing values from measured zeroes. REST snapshot calls have their own field normalization and may provide more information than the stream.

## Delivery and reconnection

The current proxy forwards publications without a server-side LTP time throttle (`zmq_listener()`); the legacy `message_throttle_interval` attribute is not applied there. LTP, Quote and Depth cadence depends on the broker and subscriptions. Subscribers share the upstream data, but do not receive a guarantee of simultaneous delivery, every exchange tick, replay, or execution at a stop price. Network outages, market closures, illiquid instruments and slow consumers all affect freshness.

Disconnected client sessions are cleaned up; reconnecting clients must re-authenticate and re-subscribe. Client libraries may remember desired subscriptions, but the server does not restore a disconnected session or backfill its missed ticks. Broker adapters have broker-specific reconnect and resubscribe behavior.

The server has an authentication deadline (`WS_AUTH_GRACE_SECONDS`, default 15 seconds). `WS_PING_INTERVAL` and `WS_PING_TIMEOUT` default to 20 seconds. `WS_MAX_QUEUE` (default 1024) is passed to the `websockets` library's **incoming receive queue**; it is not an application send queue and does not guarantee tick delivery to a slow client. There is no explicit downstream client-count cap in `handle_client`; file descriptors and host capacity still bound connections.

## Internal cache, health, and callbacks

`MarketDataService` validates incoming frames, records feed health, caches values and invokes subscribers in CRITICAL, HIGH, NORMAL, LOW order. This ordering applies to its internal callbacks; the public proxy does not give Flow a separate faster stream than external clients.

The validator rejects missing/nonpositive LTP for ordinary price frames. It can accept a Depth packet with valid levels before a positive LTP arrives. Timestamps older than 60 seconds and single-tick moves above 20% produce **warnings**, not automatic rejection or exchange circuit-breaker enforcement.

The connection health monitor checks for silence and marks the feed stale after 30 seconds. `is_trade_management_safe()` exposes a health gate that callers such as Flow can consult. This gate can pause actions while prices are stale; it cannot execute an exit during an outage or guarantee a stop-loss fill.

Registering a local callback is distinct from subscribing to the broker feed. For custom internal code:

1. Use the existing WebSocket service/client to request the symbol and mode.
2. Register a callback with `subscribe_critical(...)` or the appropriate update helper.
3. Inspect health and per-symbol freshness before acting.
4. Unregister the callback and release subscriptions during cleanup.

The cache is in memory. A cache read does not fetch broker REST data or create a subscription. Symbols without an available streamed value can return `None`. See the [internal service reference](prompt/services_documentation.md) for exact callable contracts.

## Streaming versus snapshots

Chart and quote consumers can subscribe through the proxy. Option-chain and many analytics tools request snapshots through REST instead. A snapshot caller does not itself subscribe on the public proxy, but some broker REST adapters internally use a temporary broker-feed subscription to obtain quote/depth data. Do not assume every REST snapshot is independent of the broker's streaming capacity.

The price, data source and refresh behavior of a particular panel are defined by its caller. There is no global switch that converts every analytics panel from polling to streaming.

## Order updates and Socket.IO

The proxy also supports an account-level [order-update stream](api/websocket-streaming/order-updates.md) through `subscribe_orders` / `unsubscribe_orders`. Broker push adapters, postbacks or broker-specific polling can feed it; sandbox updates use `mode: "analyze"`. Consumers must handle duplicate events and reconcile with broker books when needed.

Flask-SocketIO remains a separate protocol for application UI notifications. A raw WebSocket client connecting to port 8765 does not subscribe to Socket.IO events.

## Source map

| Source | Responsibility |
|---|---|
| `websocket_proxy/server.py` | Authentication, client ownership, ZMQ subscriber and mode-aware fan-out |
| `websocket_proxy/broker_factory.py` | Adapter discovery, shared pool registry and cleanup |
| `websocket_proxy/connection_manager.py` | Capacity, mode/refcount management, shared publisher |
| `websocket_proxy/base_adapter.py` | Adapter contract and ZMQ publisher connection |
| `websocket_proxy/app_integration.py` | Proxy topology, startup, supervision and shutdown |
| `services/websocket_client.py` | In-process proxy client and reconnect lifecycle |
| `services/websocket_service.py` | Per-user subscriptions and callbacks |
| `services/market_data_service.py` | Cache, validation, priority callbacks and health |
