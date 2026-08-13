# WebSocket Proxy PRD

## Purpose

The WebSocket proxy gives frontend and external clients one authenticated protocol for broker-normalized live market data. Broker-specific adapters own upstream connections; the proxy owns client authentication, subscription state, public tick fan-out, and lifecycle diagnostics.

## Client Protocol

Clients connect to `WEBSOCKET_HOST:WEBSOCKET_PORT` and send JSON action envelopes.

| Action | Current behavior |
|---|---|
| `authenticate` or `auth` | Accepts `api_key` or `apikey`, resolves the active user and broker, and creates or reuses an adapter |
| `subscribe` | Accepts one symbol or a symbols array and stores `LTP`, `Quote`, or `Depth` subscriptions |
| `unsubscribe` | Removes requested subscriptions |
| `unsubscribe_all` | Removes all subscriptions for the client |
| `get_broker_info` | Returns authenticated broker and feature information |
| `get_supported_brokers` | Returns broker discovery information |
| `ping` | Returns a pong and echoes `_pingId` when supplied |

Mode values normalize from names and integers: `LTP`/`1`, `Quote`/`2`, and `Depth`/`3`. Subscription responses report per-symbol success or failure. Clients that do not authenticate within `WS_AUTH_GRACE_SECONDS` are disconnected; the default is 15 seconds.

## Internal Data Topology

```text
broker upstream WebSockets
  -> broker adapters / connection pools
  -> shared ZeroMQ PUB sockets connect to ZMQ_HOST:ZMQ_PORT
  -> proxy ZeroMQ SUB socket binds ZMQ_HOST:ZMQ_PORT and subscribes to all topics
  -> O(1) subscription index
  -> authenticated WebSocket clients
```

The bind/connect direction is deliberate: one proxy subscriber binds while multiple broker publishers connect. Private order, position, and margin topics are not fanned out as public market data. Higher-detail public data may satisfy lower-detail subscriptions where the proxy's mode rules allow it.

## Connection And Subscription Requirements

- Track connected clients, client subscriptions, user mappings, broker mappings, adapter references, and an O(1) subscription index.
- Share broker feeds where possible and reference-count frontend subscriptions.
- Default connection-pool capacity is 1000 symbols per connection and 3 connections; `MAX_SYMBOLS_PER_WEBSOCKET` and `MAX_WEBSOCKET_CONNECTIONS` configure those limits.
- `WS_MAX_QUEUE`, `WS_PING_INTERVAL`, and `WS_PING_TIMEOUT` configure server queue and protocol heartbeat behavior.
- Disconnect cleanup must remove client indexes and release an adapter only after the user's remaining clients no longer require it.
- Re-authentication with unchanged broker/feed tokens must not tear down the shared feed.
- Frontend market data must automatically reconnect, pause/resume for page visibility, and use `/api/v1/multiquotes` as REST fallback where implemented.

## Process Model

| Environment | Proxy lifecycle |
|---|---|
| Docker or `APP_MODE=standalone` | Started separately by the container startup path |
| Gunicorn with eventlet | Spawned as a child Python process to isolate asyncio from the eventlet hub |
| Development server without eventlet | Runs in a real OS thread with its own asyncio event loop |

The old same-process daemon-thread and single-Gunicorn-worker description is not the current production model.

## Operational Requirements

- Shutdown must close WebSocket and ZeroMQ resources and stop the child process or OS thread.
- Proxy stats are written to `WS_PROXY_STATS_FILE`, defaulting to `log/ws_proxy_stats.json`.
- Stale-tick and connection failures must be observable through logs/stats without emitting private credentials.
- The WebSocket stream is distinct from REST depth: `/api/v1/depth` returns one snapshot.

## Ownership And Coverage

| Area | Source |
|---|---|
| Client actions, ZMQ subscriber, fan-out | `websocket_proxy/server.py` |
| Connection pools and shared publishers | `websocket_proxy/connection_manager.py` |
| Broker abstraction | `websocket_proxy/base_adapter.py`, `websocket_proxy/broker_factory.py` |
| Flask/process lifecycle | `websocket_proxy/app_integration.py`, `app.py` |
| Frontend sharing/fallback | `frontend/src/lib/MarketDataManager.ts` and market-data hooks |

See `docs/design/06-websockets/README.md`, `docs/bdd/websocket_streaming.feature`, and `docs/bdd/session_lifecycle.feature`.
