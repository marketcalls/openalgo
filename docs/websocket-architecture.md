# OpenAlgo Websockets and ZMQ

**How websocket data is distributed across the UI, Risk Management, and External Websockets.**

This page is written for traders first, with developer details toward the end. If you've ever wondered "why doesn't opening the option chain mess up my live algo?" or "can I capture broker tick data without breaking my GUI?" — this is the doc for you.

---

## The 30-second version

OpenAlgo connects to your broker's live market feed **once**. That single feed is then distributed locally to three different audiences:

1. **The UI** — the charts, quote panels, option chain etc. you see in the browser.
2. **Risk Management** — the Flow engine that watches your stoplosses, targets, and price triggers in real time.
3. **External Websockets** — your own Python, JavaScript, Excel, or AmiBroker scripts that connect to OpenAlgo to receive ticks.

All three see the same ticks at the same time. They don't compete with each other, and adding a second consumer does **not** double the load on your broker.

The plumbing that makes this possible is a small in-process message bus called **ZeroMQ (ZMQ)** plus a unified **Websocket Proxy** that the rest of the world talks to.

---

## Why is it built this way?

Every Indian broker imposes hard limits on websockets:

- Usually **1–2 websocket connections** per login (Flattrade and Kotak, for example, allow up to 2).
- Usually **1000–3000 symbols total** across those connections.
- Some brokers will silently drop subscriptions if you exceed the cap.

If every part of OpenAlgo opened its own websocket directly to the broker, you'd burn through that budget instantly — the GUI would fight your live algo, and your data-capture script would fight both.

So OpenAlgo runs **one connection to the broker per session**, demultiplexes it locally, and lets every consumer subscribe to whatever they need without anyone knowing about anyone else.

---

## The big picture

```
                ┌─────────────────────────────┐
                │     Your Broker's Feed       │
                └──────────────┬──────────────┘
                               │
                               ▼
                ┌─────────────────────────────┐
                │   Broker Websocket Adapter   │  (per broker, normalises ticks)
                │   wrapped in ConnectionPool   │  (manages 1..N broker WS sessions)
                └──────────────┬──────────────┘
                               │
                               ▼
                ┌─────────────────────────────┐
                │   ZeroMQ Bus  (port 5555)    │  internal "post office", loopback
                └──────────────┬──────────────┘
                               │
                               ▼
                ┌─────────────────────────────┐
                │  Websocket Proxy (port 8765) │  unified WSS endpoint, dedup + auth
                └───┬─────────────┬───────────┬┘
                    │             │           │
                    ▼             ▼           ▼
                  UI         MarketData    External
              (browser)        Service     (your scripts)
                                  │
                                  ▼
                            Flow / RMS
                          (stoploss, target,
                           price triggers)
```

The broker only ever sees one consumer (the pool). Everyone else taps in downstream.

---

## Roles: who does what

OpenAlgo's websocket layer is built from four distinct pieces. Each has one job. Understanding them separately makes the rest of this page (and most user questions) much easier.

### 1. The Broker Websocket Adapter

**Job:** speak the broker's proprietary websocket protocol and translate everything into a standard OpenAlgo tick format.

Every broker has its own websocket — different login flow, different message shape, different way of expressing market depth, different reconnect rules. The adapter (`broker/<broker_name>/streaming/<broker>_adapter.py`) is the *only* code in OpenAlgo that knows about those quirks. Once a tick has been parsed and normalised, it leaves the adapter looking the same regardless of which broker it came from.

The adapter does **not** know who's listening. It just publishes.

### 2. ConnectionPool

**Job:** make the broker's symbol cap invisible to everyone above it.

Most brokers cap a single websocket at 1000 symbols (Zerodha is 3000). If you need to subscribe to more than that, you need a *second* broker websocket. ConnectionPool handles that for you — it transparently opens a new broker connection when the first is full, and routes new subscriptions to whichever connection has space. From the outside, it looks like one big pipe. (Full details below in the **Connection pooling** section.)

### 3. The ZeroMQ Bus (port 5555, loopback)

**Job:** be the in-process post office between the broker side and the consumer side.

ZeroMQ here is the simplest possible "publish/subscribe" message bus. The broker adapter (or pool) publishes every normalised tick onto this bus, tagged with a topic like `NSE_RELIANCE_QUOTE`. Anything in the same machine that wants ticks can subscribe — but in practice, only the Websocket Proxy does.

Why bother with a bus instead of just calling Python functions directly?

- **Decoupling.** The broker side runs independently. If a downstream consumer is slow, ZeroMQ drops messages for that consumer rather than blocking the broker feed. Your live algo's stoploss watcher never blocks because a browser tab is being slow.
- **One-to-many fan-out for free.** Adding a new consumer (a tick recorder, a custom dashboard) doesn't require touching the broker adapter at all.
- **Resilience.** A crashing client doesn't bring down the broker session.

The bus is bound to `127.0.0.1` (loopback) only. It is not exposed off the machine. It is not a public, versioned API.

### 4. The Websocket Proxy (port 8765)

**Job:** be the *one* websocket endpoint the rest of the world talks to, and demultiplex ticks to the right clients.

The proxy:

- Listens on port 8765 for WSS clients (browsers, Python scripts, AmiBroker, etc.).
- Authenticates them with their OpenAlgo API key.
- Maintains the master subscription registry, keyed by `(symbol, exchange, mode)` → set of client IDs.
- Subscribes to the ZeroMQ bus; for every incoming tick, it looks up who wants it and forwards to those clients only.
- Throttles LTP updates to 50 ms per symbol so slow clients don't drown.
- **Deduplicates subscriptions** — see the "one subscription, many consumers" rule below.

The proxy is what enforces "one broker subscription per symbol, no matter how many people are watching".

### 5. The Market Data Service (in-process, Python)

**Job:** be the in-process Python facade that internal services use to read prices, with safety gates wrapped around it.

This is the piece most users have never heard of, but it's how Flow and the rest of the Python codebase consume the feed. Detailed in its own section below.

---

## The three audiences in detail

### 1. UI — what you see in the browser

When you open OpenAlgo in your browser and look at a live chart, a quote panel, or any ticking number, the browser is connected to the **Websocket Proxy on port 8765** behind the scenes. Each panel asks for the symbols it needs (e.g. NIFTY, BANKNIFTY) and unsubscribes automatically when you close the panel.

A few things worth knowing as a trader:

- **Lazy subscription.** A symbol is only subscribed when a panel that needs it is actually open. Closing the panel releases it.
- **Tab pause.** If you switch away from the OpenAlgo tab for more than 5 seconds, the UI automatically pauses its subscriptions to save bandwidth. It resumes when you come back.
- **Snapshot vs. stream.** Many panels (option chain, GEX, vol surface, IV smile, OI tracker, straddle chart, etc.) **do not** use the websocket at all — they fetch snapshots from the broker REST API on a refresh interval. See "Which features stream vs. poll" below.

### 2. Risk Management — Flow

If you're running Flow strategies, two background services watch the market in real time:

- **Price Monitor** (`flow_price_monitor_service`) — fires entries when your trigger conditions hit.
- **Executor** (`flow_executor_service`) — watches stoplosses and targets on open positions.

Both connect to the same Websocket Proxy as the UI does. They subscribe to exactly the symbols your active strategies need, nothing more.

For a trader this means: **your live algo's risk management runs on the same shared feed as everything else.** It does not open a separate broker connection. It does not "miss ticks" because the GUI is open. The proxy delivers the same stream to every subscriber simultaneously.

### 3. External Websockets — your own clients

OpenAlgo exposes the Websocket Proxy as a public WSS endpoint at `ws://<host>:8765`. Any client in any language can connect, authenticate with an OpenAlgo API key, and subscribe to symbols.

This is how you'd:

- Stream ticks into a Python or Node script.
- Pipe data into AmiBroker, Excel, MetaTrader, or a notebook.
- Run a tick recorder that writes to Parquet, CSV, or a database.
- Build a custom dashboard that updates without polling.

The protocol (subscribe/unsubscribe message format, authentication, modes) is documented in [`websocket-quote-feed.md`](./websocket-quote-feed.md). That doc is the developer reference; this one is the architectural overview.

External clients are first-class citizens — they share the same broker subscription as the UI and Risk Management. If you're already running NIFTY in the UI and your script also subscribes to NIFTY, the broker is **not** asked twice.

---

## How Python services consume the feed: the Market Data Service

External clients talk WSS to port 8765. The browser does too. But internally, OpenAlgo's own Python code (Flow, watchlists, dashboards, RMS) doesn't speak WSS to itself — that would be wasteful. It uses an in-process facade called **`MarketDataService`** (`services/market_data_service.py`).

Think of it as a thin layer that sits inside the same Python process as the proxy and offers two things to other services:

1. **A cache** — the latest LTP, quote, and depth for every subscribed symbol, so any service can call `get_ltp("NIFTY", "NSE")` and get an answer immediately, without round-tripping anywhere.
2. **A subscription model with priorities and safety gates** — so trade-management code (Flow's stoploss/target watcher) is treated as more important than a watchlist UI panel, and is automatically paused when the feed is unhealthy.

### What it does on every tick

When a tick arrives from the websocket layer, the service:

1. **Validates** — checks the LTP is positive, checks for a stale timestamp (>60 s old), and runs a circuit-breaker that flags any single-tick price change >20% from the last known price.
2. **Updates the cache** — `(exchange, symbol)` → `{ ltp, quote, depth, last_update }`.
3. **Records data-received** — bumps the health monitor's `last_data_timestamp`, which is how the service knows the feed is alive.
4. **Broadcasts to subscribers** — in priority order: CRITICAL → HIGH → NORMAL → LOW. Stoploss/target callbacks fire first, dashboard callbacks last.

### Priority subscriber tiers

```
CRITICAL  →  Flow stoploss / target / price triggers
HIGH      →  Price alerts, monitoring
NORMAL    →  Watchlists, general displays
LOW       →  Dashboards, analytics
```

A subscriber registers a callback function and gets back a subscriber ID. When data flows, callbacks are run in priority order. This means even if a heavy dashboard subscriber takes 50 ms to process a tick, the stoploss watcher has already been called first.

### Safety gates for trade management

This is the part traders should know about, even if you'll never call this code yourself.

The service runs a background **health monitor** thread that checks every 5 seconds:

- Has the underlying websocket been silent for >30 s? → mark connection **STALE**.
- Was the connection lost? → flip the `_trade_management_paused` flag.
- Did data come back? → flip it off again.

When `_trade_management_paused` is set, Flow's stoploss/target engine calls `is_trade_management_safe()` before triggering anything — and that returns `(False, "Connection lost — trade management paused for safety")`. So a stoploss won't fire on a stale price just because the websocket dropped for 45 seconds. It waits until ticks resume.

This is the layer that makes "the algo missed my SL because the broker WS dropped" not happen by accident.

### What it doesn't do

- **It doesn't open the websocket itself.** It receives ticks via callbacks registered through `websocket_service.register_market_data_callback()`. The actual subscriptions are still managed at the Websocket Proxy layer.
- **It doesn't persist anything.** The cache is in-memory and is wiped on app restart. Stale entries are cleaned up after 1 hour of no updates.
- **It doesn't talk to the broker REST API.** If a symbol isn't being streamed, `get_ltp()` returns `None`. It's a *cache of the live feed*, not a quote service.

### How a typical Flow strategy uses it

1. Flow service calls `subscribe_critical(callback, filter_symbols={"NSE:RELIANCE"}, name="sl_watcher_42")`.
2. Behind the scenes, OpenAlgo also subscribes that symbol on the websocket if it isn't already subscribed (this is what the proxy's deduplication handles).
3. Every tick for RELIANCE flows: broker → adapter → ZMQ → proxy → MarketDataService → callback → Flow's stoploss check.
4. If the connection dies, the safety gate prevents `callback` from ever firing on stale data.
5. When Flow shuts down, it calls `unsubscribe_priority(subscriber_id)` and the symbol is released (and ultimately unsubscribed from the broker if no one else cares).

### When you build something custom

If you're writing your own Python integration (a custom alert, a scanner, a recording bot), you have two reasonable choices:

- **Use `MarketDataService` directly** if your code runs inside the same OpenAlgo process. It's the lightest path: one function call, no serialisation, automatic safety gates.
- **Use the public WSS endpoint on port 8765** if your code runs in a separate process or different machine. Same data, slight serialisation overhead, but completely decoupled.

For a trader, the takeaway is just: when Flow says "I'm watching your stoploss", that watching goes through this service, and it has guards built in.

---

## The "one subscription, many consumers" rule

This is the most important thing for traders to internalise:

**Every subscription is keyed by `(symbol, exchange, mode)`.** When the second client subscribes to the same key, the broker is **not** asked again — that client just gets added to the recipient list.

A concrete walk-through:

1. You open the option chain in the UI → it subscribes to NIFTY → the broker adapter sends one subscribe call to your broker.
2. Your Flow strategy starts and also wants NIFTY → the proxy notes it, but does **not** call the broker again.
3. You start a Python script that records NIFTY → again, no extra broker call.

All three now receive every NIFTY tick. The broker only sees one subscription.

When the **last** consumer disconnects (or unsubscribes), only then does the proxy tell the broker to drop the symbol. This is what lets you run the UI, Flow, and an external recorder side by side without blowing past your broker's limits.

---

## Modes (LTP, Quote, Depth)

Every subscription has a mode, which controls how much data you get:

| Mode  | What you get                          | Notes                                              |
|-------|---------------------------------------|----------------------------------------------------|
| LTP   | Last traded price only                | Throttled to one update per 50 ms per symbol.       |
| Quote | Full quote (LTP, OHLC, volume, etc.)  | Standard for most trading needs.                    |
| Depth | Quote + market depth (bid/ask levels) | Heaviest payload; some brokers offer 5 or 20 levels.|

Modes are hierarchical: if a symbol is already subscribed at Depth (the heaviest), a later request for Quote or LTP on the same symbol piggy-backs on it instead of issuing a separate broker call.

---

## Which features stream vs. poll

This is the question people ask the most. Not every OpenAlgo feature uses the websocket — many of them poll the broker's REST API instead. **Knowing which is which lets you reason about your websocket budget.**

### Use the websocket (live stream)

- The UI's live charts, quote panels, and tickers
- `flow_price_monitor_service` (Flow entry triggers)
- `flow_executor_service` (Flow stoploss / target watcher)
- Any external client you build that connects to port 8765

### Poll the broker REST API (no websocket)

These features fetch data on a refresh interval. They do **not** open a websocket subscription:

- Option chain
- Market depth (when viewed as a snapshot)
- Vol surface, GEX, IV smile, IV chart
- OI tracker, OI profile, multi-strike OI
- Straddle chart, custom straddle
- Option Greeks, synthetic future
- Snapshot quotes (`/api/v1/quotes`), funds, holdings, position book, order book, trade book

**Practical implication:** opening the option chain or running the vol surface does **not** consume websocket symbol slots. The broker REST API is rate-limited separately, and brokers vary on how many symbols you can request per call. Some brokers are strict about multi-quote calls (Azhagesan's point on Discord); for those, the option chain may feel slower because of throttling on the REST side, but it is **not** competing with your live algo's websocket.

If you want the option chain to use the websocket instead, that's a feature request, not a config toggle today — see "Known gaps" below.

---

## Connection pooling: what it is and why it matters

This is the question we get most often once people start subscribing to a lot of symbols. So let's be precise.

### What is "websocket pooling"?

A **broker websocket** is the live TCP connection from OpenAlgo to your broker's market-data servers. Each broker imposes a cap on how many symbols a single such connection can carry — typically 1000 symbols, sometimes 3000 (Zerodha), occasionally less.

If you need more symbols than one broker websocket can hold, your only option is to open a **second** broker websocket (and a third, and so on, up to whatever the broker allows on a single login).

**Connection pooling** is the OpenAlgo feature that does this for you automatically. The `ConnectionPool` (in `websocket_proxy/connection_manager.py`) manages a small set of broker websocket sessions on your behalf, distributes new subscriptions across them, and presents the whole thing as one logical pipe to the rest of OpenAlgo.

You never have to think "I'm at 998/1000, I need to open a new connection". The pool does it.

### Why is it important?

Three reasons:

1. **Symbol scale.** Without pooling, you'd hit the per-connection cap and just stop being able to subscribe. Pooling lets a single user reach the broker's full per-login symbol budget — usually 3000 symbols, in three connections.
2. **One ZMQ destination.** All connections in the pool publish to the **same** ZeroMQ socket via a singleton called `SharedZmqPublisher`. The Websocket Proxy keeps subscribing to *one* port no matter how many broker connections are actually open. This is why scaling out broker connections doesn't add complexity downstream.
3. **Mode hierarchy and deduplication done right.** When a second consumer asks for the same symbol at a different mode, the pool has the smarts to upgrade or downgrade existing subscriptions instead of opening duplicates. (More on this below.)

### How it works, concretely

When you (or any feature, or any external client) subscribe to a new symbol, the pool runs through this checklist:

1. **Already subscribed at this exact mode?**
   Just track the new client and return success. No broker call.
2. **Already subscribed at a different mode for the same symbol?**
   - If your requested mode is *higher* (e.g. you want Depth, the existing sub is Quote) → tell the broker to upgrade that single subscription. Don't open a new one.
   - If your requested mode is *lower* or equal (e.g. you want LTP, the existing sub is Quote) → just track you as a subscriber. The broker is already sending more data than you asked for; you'll receive what you need from the same stream.
3. **First time seeing this symbol:**
   - Look at the pool's connection list. Is there an adapter with capacity (`< MAX_SYMBOLS_PER_WEBSOCKET` symbols)? Use it.
   - If every existing adapter is at capacity, and we're still under `MAX_WEBSOCKET_CONNECTIONS`, open a new broker websocket and use it.
   - If we're at the absolute cap, return `MAX_CAPACITY_REACHED`.

Unsubscribe is the mirror image:

- **Last consumer for the highest mode left?** Tell the broker to downgrade to the next-highest still-active mode (or fully unsubscribe if nothing's left).
- **Last consumer for a lower mode left, but a higher mode is still active?** Just remove the tracking entry. Broker doesn't need to know — the higher mode is already supplying that data.
- **Last consumer for the entire symbol left?** Fully unsubscribe from the broker, free up the slot.

### Mode hierarchy, briefly

`Depth (3) ≥ Quote (2) ≥ LTP (1)`. If the broker is already streaming Depth for a symbol, anyone who asks for Quote or LTP on the same symbol gets what they need from the existing stream — the broker is never asked for "the same data again, just less of it".

This is why you'll sometimes see logs like:

```
[POOL] Tracked NIFTY28APR2425000CE.NFO mode 1 (covered by active mode 3)
```

Translation: a new subscriber wanted LTP for that strike. The pool noticed Depth was already running for that strike and just tracked the subscriber. No broker call, no new symbol slot used.

### What capacity actually looks like

| Setting                          | Default | Where                              |
|----------------------------------|---------|------------------------------------|
| Symbols per broker connection    | 1000    | `MAX_SYMBOLS_PER_WEBSOCKET` in .env |
| Max broker connections per user  | 3       | `MAX_WEBSOCKET_CONNECTIONS` in .env |
| Total cap (OpenAlgo side)        | 3000    | derived                            |
| LTP throttle                     | 50 ms   | hard-coded                         |
| Connection pooling enabled       | yes     | `ENABLE_CONNECTION_POOLING=true`    |

The actual ceiling is the **lower** of (OpenAlgo's cap) and (your broker's per-login cap):

- **Most brokers** allow exactly 1 websocket per login. Pooling is still on, but the pool will only ever spin up one connection — when it fills, you simply can't subscribe to more symbols on that account.
- **Flattrade, Kotak, and a few others** allow 2 sessions per credential. The pool will use both when needed.
- **Zerodha** uses a single session with a higher (3000) per-session symbol cap, configured via the broker adapter — same pooling code, different per-connection limit.

If you push the pool past its limit, you get a structured error rather than a silent drop:

```python
{
  "status": "error",
  "code": "MAX_CAPACITY_REACHED",
  "message": "Maximum capacity reached: 3 connections × 1000 symbols = 3000 symbols. Currently subscribed to 3000 symbols."
}
```

### What the pool does *not* do

- It doesn't bypass broker limits. If your broker says 1 websocket, it stays 1 websocket.
- It doesn't do load-balancing in any clever sense. Connections fill in order: first connection until full, then second, then third. (This works fine because all connections feed the same ZMQ bus anyway.)
- It doesn't share connections *across users*. Pooling is per-(broker, user). Each OpenAlgo deployment is single-user, so in practice you have one pool.
- It doesn't persist subscriptions across restarts. On startup the pool is empty; clients re-subscribe as they reconnect.

### Tuning

The two knobs that matter, both via `.env`:

- `MAX_SYMBOLS_PER_WEBSOCKET` — set this to whatever your broker actually allows per session. Most are 1000, Zerodha is 3000, some are smaller. Setting it higher than the broker allows just means subscriptions will fail at the broker level instead of being routed to a fresh connection.
- `MAX_WEBSOCKET_CONNECTIONS` — set this to whatever your broker allows per login. 1 for most brokers, 2 for Flattrade/Kotak.

Setting these correctly means OpenAlgo will reject "you've gone too far" cleanly instead of letting the broker cut you off mid-trade.

---

## Frequently asked questions

**Q: If I open the option chain panel in the GUI, does that count against my live algo's websocket?**
No. The option chain uses the broker REST API, not the websocket. Your live algo's subscription is unaffected.

**Q: I'm running Flow with 50 symbols, and I want a Python script to record those same 50 symbols. Do I need to double my broker capacity?**
No. The proxy deduplicates: one broker subscription, two consumers. Your broker still sees 50 symbols, not 100.

**Q: Can I capture all websocket ticks to a file for backtesting?**
Not built in. You'd write your own client against port 8765 (or, if you're comfortable, against the internal ZMQ bus) and persist the data yourself. There's no parquet/CSV recorder in OpenAlgo today.

**Q: Some users on Discord mentioned exposing ZMQ to external scripts. Is that supported?**
The internal ZMQ bus on `127.0.0.1:5555` is not a public, versioned API right now. The supported way to consume the feed is the WSS endpoint on port 8765. If you want to subscribe to ZMQ directly from a local script you can, but the topic format and message schema are not contractually stable across releases.

**Q: My broker says I can have 2 websocket connections. Does OpenAlgo use both?**
With pooling enabled (the default), yes — when the symbol cap on the first connection is reached, the proxy automatically opens a second one. You don't need to do anything.

**Q: Does the Risk Management (Flow) feed have priority over the UI?**
No, all consumers are equal. Every subscriber gets the same tick at the same time. The proxy throttles LTP to 50 ms per symbol globally to protect slow clients, but no consumer is treated specially.

---

## Known gaps

Things that don't exist yet and have come up in user requests:

- **Built-in tick recorder.** No parquet/CSV/SQLite writer. You'd build it yourself against port 8765.
- **Per-feature stream/poll toggle.** You can't currently tell the option chain to use the websocket, or tell Flow to use polling. Routing is fixed in code.
- **Stable external ZMQ interface.** The internal bus is loopback and not versioned. A future "external bus" would need its own design.
- **Capture mode.** No way to keep a websocket subscription alive purely for recording, independent of any UI panel or strategy.

If any of these are blockers for your workflow, that's worth raising as a GitHub issue with concrete numbers — what symbols, what frequency, what destination.

---

## Developer reference

The rest of this section is for people writing code or debugging.

### Components

| File | Role |
|---|---|
| `websocket_proxy/server.py` | Public WSS server on `:8765`. API-key auth, subscription registry, throttling, ZMQ listener. |
| `websocket_proxy/connection_manager.py` | `ConnectionPool` — manages multiple broker WS connections per user when symbol caps are hit. |
| `websocket_proxy/base_adapter.py` | Abstract base every broker streaming adapter inherits. Handles ZMQ publish, port allocation, auth-error retry. |
| `websocket_proxy/broker_factory.py` | Loads the right adapter for the logged-in broker, optionally wraps it in a pool. |
| `websocket_proxy/app_integration.py` | Starts/stops the proxy alongside the Flask app. |
| `broker/<name>/streaming/<name>_adapter.py` | Per-broker implementation (Flattrade, Kotak, Angel, Zerodha, etc.). |

### ZMQ topic format

```
EXCHANGE_SYMBOL_MODE
e.g. NSE_RELIANCE_QUOTE
     NFO_NIFTY28APR2425000CE_DEPTH
     MCX_CRUDEOIL20MAY24FUT_LTP
```

Topic strings are deliberately stable for the duration of a release but are not part of a public contract.

### Subscription deduplication

```python
# inside websocket_proxy/server.py
sub_key = (symbol, exchange, mode)
if sub_key not in self.subscription_index:
    # First subscriber — actually call the broker adapter
    adapter.subscribe(symbol, exchange, mode)
self.subscription_index[sub_key].add(client_id)

# ... on unsubscribe:
self.subscription_index[sub_key].discard(client_id)
if not self.subscription_index[sub_key]:
    # Last subscriber gone — release the broker subscription
    adapter.unsubscribe(symbol, exchange, mode)
    del self.subscription_index[sub_key]
```

### Eventlet considerations

The Flask app runs under Gunicorn with the `eventlet` worker (`-w 1`). The Websocket Proxy is started in a daemon thread that runs an asyncio event loop separately, because asyncio and eventlet do not coexist in the same thread. See `websocket_proxy/app_integration.py` for the startup pattern.

### Note on Flask-SocketIO vs. the Websocket Proxy

OpenAlgo also uses **Flask-SocketIO** for control-plane events (order placed/filled/rejected, analyzer updates, master contract loaded, etc.). That is a separate websocket from the market-data Websocket Proxy described here. Don't confuse the two:

- **Flask-SocketIO** (Socket.IO protocol, app-internal) → order updates, UI notifications.
- **Websocket Proxy on `:8765`** (raw WSS, JSON protocol) → market data ticks.

A trader using only the GUI doesn't need to think about this. A developer building integrations does.

### Quick reference

| Thing | Value |
|---|---|
| Public WSS port | `8765` |
| Internal ZMQ port | `127.0.0.1:5555` (loopback) |
| Auth | OpenAlgo API key |
| Default symbols per broker connection | 1000 (3000 for Zerodha) |
| Max broker connections per user | 3 (with pooling enabled) |
| LTP throttle | 50 ms per symbol |
| Pooling flag | `ENABLE_CONNECTION_POOLING` (default `true`) |

For the message format and language-specific client examples, see [`websocket-quote-feed.md`](./websocket-quote-feed.md).
