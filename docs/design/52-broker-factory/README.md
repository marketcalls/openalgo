# 52 - Broker WebSocket Factory

## Purpose

`websocket_proxy/broker_factory.py` dynamically loads the active broker's streaming adapter and optionally wraps it in a connection pool. This factory is specific to real-time broker feeds; normalized REST order/data services perform their own broker-module imports.

## Adapter Resolution

For broker key `<broker>`, the factory:

1. Checks the in-process adapter class registry.
2. Imports `broker.<broker>.streaming.<broker>_adapter`.
3. Resolves `<Broker>WebSocketAdapter` using the current class-name convention.
4. Falls back to `websocket_proxy.<broker>_adapter` for legacy adapter placement.
5. Registers the resolved class for later reuse or raises `ValueError` when no adapter is available.

Plugin presence does not by itself prove a working streaming adapter. `broker/*/plugin.json` is the broker configuration inventory; the factory still requires an importable adapter for WebSocket use.

## Pooling

`create_broker_adapter()` uses `ENABLE_CONNECTION_POOLING` unless a caller overrides it.

| Setting | Default | Meaning |
|---|---:|---|
| `ENABLE_CONNECTION_POOLING` | `true` | Return a pooled wrapper |
| `MAX_SYMBOLS_PER_WEBSOCKET` | `1000` | Capacity allocated to one connection |
| `MAX_WEBSOCKET_CONNECTIONS` | `3` | Maximum connections per user/broker pool |

Pools are keyed by broker and user. The wrapper preserves the adapter interface for initialize, connect, disconnect, subscribe, unsubscribe, unsubscribe-all, status, and publishing operations. Pool cleanup removes the global registry entry.

## ZeroMQ Fan-In

All pooled connections share one thread-safe ZeroMQ publisher. The proxy SUB socket binds `ZMQ_HOST:ZMQ_PORT`; the shared and standalone adapter PUB sockets connect to it. This fixed fan-in direction allows multiple adapter publishers without port-scan or bind races.

```text
broker connection 1 --\
broker connection 2 ----> shared PUB connects ---> proxy SUB binds ---> clients
broker connection 3 --/
```

## Token Refresh And Recovery

Connection pools recognize common authentication failures such as 401, 403, expired token, and invalid credentials. Recovery can force adapter re-initialization with current auth data. Re-authentication with unchanged plaintext broker/feed tokens must preserve the existing shared feed rather than replacing it because encrypted values differ.

## Current Plugin Inventory

There are 34 `broker/*/plugin.json` directories:

`aliceblue`, `angel`, `arrow`, `compositedge`, `definedge`, `deltaexchange`, `dhan`, `dhan_sandbox`, `firstock`, `fivepaisa`, `fivepaisaxts`, `flattrade`, `fyers`, `groww`, `ibulls`, `iifl`, `iiflcapital`, `indmoney`, `jainamxts`, `kotak`, `motilal`, `mstock`, `nubra`, `paytm`, `pocketful`, `rmoney`, `samco`, `shoonya`, `tradejini`, `tradesmart`, `upstox`, `wisdom`, `zebu`, and `zerodha`.

Individual broker symbol limits and depth capabilities are adapter/upstream concerns and must not be inferred from the generic 1000-by-3 pool defaults.

## Key Files

| File | Responsibility |
|---|---|
| `websocket_proxy/broker_factory.py` | Resolution, class registry, pooled wrapper |
| `websocket_proxy/connection_manager.py` | Pools, subscription distribution, shared publisher |
| `websocket_proxy/base_adapter.py` | Common adapter interface and standalone publisher |
| `websocket_proxy/server.py` | Authentication, subscription index, SUB binder, client fan-out |
| `broker/*/streaming/` | Broker-specific upstream implementations |

See `docs/design/06-websockets/README.md`, `docs/bdd/broker_plugin_inventory.feature`, and `docs/bdd/websocket_streaming.feature`.
