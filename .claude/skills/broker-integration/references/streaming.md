# Market-data streaming — the hardest part; copy zerodha/upstox closely

This file covers the **market-data** adapter (ticks, quotes, depth). The
account-level **order-update** stream is a separate, much smaller contract —
see `order-updates.md`.

3-layer pipeline: broker adapter -> ZeroMQ bus -> unified proxy (port 8765).

- Adapter subclasses **`websocket_proxy/base_adapter.BaseBrokerWebSocketAdapter`**;
  call `super().__init__()`. Implement `initialize(broker_name, user_id,
  auth_data=None)`, `connect()`, `subscribe(symbol, exchange, mode=2,
  depth_level=5)`, `unsubscribe(symbol, exchange, mode=2)`, `disconnect()`.
- Modes: **1=LTP, 2=Quote, 3=Depth**.
- Publish ticks with the inherited **`self.publish_market_data(topic, data)`** —
  do NOT create your own ZMQ socket. Topic = `f"{exchange}_{symbol}_{MODE}"`
  with MODE in `LTP/QUOTE/DEPTH`.

### Two different "topics" — don't conflate them

The **internal ZMQ topic** you publish to is `f"{exchange}_{symbol}_{MODE}"`
(e.g. `NSE_RELIANCE_QUOTE`). The **client-facing topic** in the WebSocket
protocol is `"{symbol}.{exchange}"` (e.g. `RELIANCE.NSE`). The proxy translates.
You only ever produce the first form. See `docs/prompt/websockets-format.md`
for the exact client-facing payloads your normalized dict must be able to fill
(`ltp`, `change`, `change_percent`, `volume`, `open/high/low/close`,
`last_trade_quantity`, `avg_trade_price`, `depth.buy/sell`).

### Depth levels beyond 5

`depth_level` may be 5, 20, 30, or 50 depending on broker capability. Declare
what you actually support via `get_supported_depth_levels()` and return
`actual_depth` from `subscribe()`. When a client requests an unsupported level
the proxy emits an `UNSUPPORTED_DEPTH_LEVEL` error listing `supported_depths`,
so an inaccurate registry surfaces as a confusing client-side error rather than
a server failure.
- Register the class in `websocket_proxy/__init__.py` (`register_adapter`). The
  factory also has a dynamic-import fallback expecting module
  `broker.<name>.streaming.<name>_adapter` and class `<Name>WebSocketAdapter`.
- Capability registry (`<name>_mapping.py`): declare modes and
  `get_supported_depth_levels()`. **Most plugins do not implement this** — the
  live mechanism is the `depth_level=5` parameter on `subscribe()` plus the
  `actual_depth` you return, which is what the proxy reports. Implement the
  registry method anyway if you serve more than 5 levels, or clients cannot
  discover the capability. For depth > 5, follow the **fyers** pattern (a
  second TBT socket routed by `depth_level`).

## Repo-wide invariants that apply here

Read the two "do not break this" blocks in the root `CLAUDE.md` before writing
socket code:

- **ZeroMQ bus: SUB binds, PUBs connect.** Your adapter is a publisher. It
  CONNECTs to the fixed `ZMQ_PORT`. Never `bind()`, never port-scan, never
  mutate `os.environ["ZMQ_PORT"]`. Using the inherited
  `self.publish_market_data()` keeps you on the right side of this
  automatically.
- **Multi-session login must not tear down the shared feed.** One adapter pool
  per `{broker}_{user_id}` fans out to up to 5 browser sessions. Do not add
  teardown on login paths.

## NUANCES (the eventlet/FD ones that cause real bugs)

- **Use sync `websocket-client` in a daemon thread — NEVER asyncio/`websockets`.**
  eventlet monkey-patching breaks asyncio under gunicorn.
- **Never `join()` daemon threads** (eventlet raises Timeout). Stop via a
  `threading.Event` and close the socket.
- **Close-before-reconnect**; reconnect with interruptible exponential backoff.
- **Re-read a fresh token on reconnect** (`get_auth_token(user_id,
  bypass_cache=True)`) — Indian broker tokens roll over ~3 AM IST. Bounded
  auth-refresh retry instead of dying on the first 403.
- **Keepalive**: `run_forever(ping_interval, ping_timeout)` + a data-stall
  health-check watchdog that forces reconnect after N seconds of silence.
- **FD hygiene**: call `self.cleanup_zmq()` in `disconnect()` (and `__del__`).
  Run the `fd-audit` skill on any streaming change.
- **Token-based feeds**: indices stream like any instrument (token from the
  master contract) — no special casing needed.
- If your broker has a new two-segment index exchange, add it to the proxy's
  topic-split prefix set in `websocket_proxy/server.py` (NSE_INDEX/BSE_INDEX are
  already handled).
- Binary feeds: confirm framing (one packet per message vs length-prefixed
  multi-packet) and endianness against a LIVE capture before trusting offsets.

## NUANCE — binary offsets: never guess, and know the symptom of a wrong guess

If the docs don't publish byte offsets, get them from the **official SDK's
parser source** (download the SDK from PyPI and read it — see the SKILL entry
point). A wrong offset doesn't crash — it produces *plausible garbage*: Arrow's
draft parser read bytes 13:17 as "close" in every packet, but in 93-byte quote
packets that field is **last traded quantity**, so the UI showed "close 0.02"
(LTQ=2). Also beware mode-dependent layouts: the same offset means different
things at different packet sizes (13:17 IS close in the 17-byte LTPC packet).
The broker may run TWO streams with different protocols (Arrow: standard stream
= big-endian/token-keyed, HFT stream = little-endian/symbol-keyed) — make sure
the docs page you're reading matches the URL you connect to.

**Test the parser with synthetic packets** before going live: build byte
buffers with `struct.pack` placing known values at the documented offsets for
every packet size (ltp/ltpc/quote/full + legacy sizes), and assert each parsed
field. This catches off-by-N immediately and needs no market hours.

## NUANCE — tick-parsing hot path

The parser runs per tick; keep it allocation-light: module-level **precompiled
`struct.Struct`** objects with ONE `unpack_from` per packet region (not 15
separate `struct.unpack` calls), `iter_unpack` for repeated depth levels, and
**no lock acquisition per tick** (CPython dict reads are GIL-atomic; lock only
the writers). Arrow's parser does ~2.3us per full-depth packet this way.

Emit the **same normalized key set as the zerodha adapter** (`open/high/low/
close`, `volume`, `average_price`, `last_quantity`, `total_buy_quantity`,
`total_sell_quantity`, `oi`, `depth.buy/sell` with `price/quantity/orders`) so
the proxy/UI see one shape across brokers.
