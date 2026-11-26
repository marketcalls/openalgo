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
- **Keepalive and the data-stall watchdog.** `run_forever(ping_interval,
  ping_timeout)` keeps the socket alive; it does not prove data is flowing. A
  Noren session kept answering heartbeats while sending no ticks for the rest
  of the day (Flattrade #2089; Shoonya, Definedge, TradeSmart, Zebu #2094).
  Keep a separate clock that only market-data frames reset (not auth acks, not
  heartbeat acks such as Noren `hk`), and recycle the socket after N seconds of
  silence. Start the watchdog only after frames have arrived across several
  separate time slices, never on a frame count: a subscribe outside market
  hours returns a burst of snapshots, and recycling every N seconds until the
  open trips the broker's reconnect cooldown. Reset it per connection. A feed
  with no heartbeat at all (XTS) needs the same watchdog (5paisa XTS #2155).
  Decide "steady data" from the frames, not from session times hardcoded in
  the adapter.
- **Reconnect: one owner, one loop, never give up on the network.** Turn off a
  library's own auto-reconnect (Socket.IO's reuses a stale token and survives
  `disconnect()`, Wisdom #2469). Reconnect from a loop, never by recursing from
  `on_close` (Groww #2312). On a network outage keep retrying at the maximum
  delay rather than giving up after N attempts (Flattrade #2359 gave up after
  about 7 minutes and stayed down all day). Give an auth refusal its own small
  budget. Every failed attempt schedules the next, including an error raised
  before the socket opened, which fires no close callback.
- **Expired login: say so once, then back off quietly.** Dial only a freshly
  authorised feed URL, never one the broker already refused (Upstox). Never
  fall back to a credential the feed does not accept (Groww socket token versus
  login token, #2312). Log one warning that asks for a new login, and log again
  when it recovers.
- **Per-connection state dies with the connection.** Ping and heartbeat
  threads stop when their socket is replaced (Pocketful, Groww). Protocol
  parsers and handshakes are rebuilt per connection, and the handshake is sent
  once per connection (Groww answered a second NATS INFO with a second CONNECT
  and was disconnected, #2312).
- **FD hygiene**: call `self.cleanup_zmq()` in `disconnect()` (and `__del__`).
  Run the `fd-audit` skill on any streaming change.
- **Indices need their own check.** A token-keyed feed may send indices a
  different packet layout (Kite: 28 bytes in quote mode, 32 in full, no
  volume, depth or OI, #2361). A symbol-keyed feed may want the broker's
  published index name, not the ticker stem (Fyers fetches
  `index_hsm_mapping.json` once, with a bundled fallback, #2139). One broker
  key may serve several OpenAlgo symbols (NIFTY and NIFTY50 on Kotak): fan the
  tick out to all of them. Test Quote and Depth on NSE_INDEX and BSE_INDEX, not
  just LTP.
- **Send the auth the official SDK sends**, even where the server tolerates
  another form (Fyers TBT wants `appId:accessToken`, #2139).
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

## NUANCE — what a tick carries: snapshot, absent fields, every mode

Use the zerodha adapter's key names (`open/high/low/close`, `volume`,
`average_price`, `last_quantity`, `total_buy_quantity`, `total_sell_quantity`,
`oi`, `depth.buy/sell` with `price/quantity/orders`), but emit only the keys the
broker actually sent. `docs/prompt/websockets-format.md` ("Field availability")
is the contract. Each rule below was learned from a live bug:

- **Merge, then publish.** Most feeds send incremental frames. Apply every
  field of a frame to one snapshot per (exchange, token), then publish that
  snapshot once per frame. Never de-duplicate on LTP: an update that moves only
  bid, ask or volume is a real update. Fyers published LTP on time and every
  other field one update behind (#2323); Upstox, Groww, HDFC Sky and 5paisa
  sent partial packets as full ticks with OHLC 0 (#2377, #2396).
- **Absent, never zero.** Leave out a field the feed does not carry: no 0, no
  REST fill, no bid/ask midpoint as LTP, no made-up depth levels for an index
  (an index has no book; send an empty book with the real index value). A
  client computing change against a close of 0 shows the whole LTP as the
  change (Sahi #2376, Fyers #2323, Zerodha #2361). Derive `change` and
  `change_percent` from ltp and the previous close when the feed has none, as
  the official SDK does.
- **A present zero is a value.** Fall back to an alias field only when the
  first is absent, not when it is falsy (a `tbq` of 0 was replaced by an older
  `tBQ`, Samco #2397).
- **`close` is the previous session's close.** Not Day Close, which the
  exchange fills after market (Dhan sends previous close in its own packet on
  every subscribe), and not today's daily candle (Upstox). #2377.
- **`ltt` is the exchange's last trade time**, never the wall clock. Omit it
  when the packet has none: 0 reads as 1970 (Kotak, Sahi #2376; mStock #2383;
  Samco #2396; AliceBlue #2473).
- **Depth carries the full quote.** The proxy sends a DEPTH tick to that
  symbol's Quote and LTP subscribers too ("Higher modes include all lower-mode
  data" in `websocket_proxy/server.py`), and `market_data_service` copies a
  depth LTP into the shared LTP cache. If the broker's book message has no
  quote, subscribe its quote feed as well and merge it in. Publish depth only
  once both the quote and the book have arrived (Fyers, Kotak #2376; Upstox
  #2377; Tradejini #2383; 5paisa #2396; AliceBlue #2473).
- **Every subscribed mode gets the tick.** Keep state per mode, not one slot
  per symbol (Definedge sent ticks only to the first matching subscription,
  #2383; HDFC Securities only to the highest, #2124). The broker subscription
  stays at the highest mode any subscriber needs: a later LTP subscribe never
  downgrades it, and unsubscribing one mode leaves the others (Upstox, HDFC
  Sky). Route frames by message type (5paisa #2396).
- **Route on exchange AND token, exactly.** Key subscriptions, stream ids,
  retry budgets and snapshots on (exchange, token). A token can exist on two
  exchanges or segments, and bare-token matching published one exchange's
  prices under both symbols (mStock #2383, Samco and HDFC Sky #2396). No
  substring or "only subscription" fallback (Fyers #2376).

## NUANCE — order books: snapshot or diff

Find out whether book messages are snapshots or diffs. A snapshot replaces the
whole book; never fill its empty levels from the previous one (Kotak #2376). A
diff carries only the levels that changed: apply it by the level index it
carries, not by its position in the list, and act on field presence rather
than truthiness, since 0 can mean the level was cleared (Fyers TBT #2122,
AliceBlue #2473).

## NUANCE — price precision is per instrument

Divide by the precision and multiplier the feed or master contract gives for
that instrument (`raw / (10 ** precision * multiplier)` for Fyers HSM, the SDK's
formula), not a fixed /100. Currency is usually 4 decimals or 1e7: Fyers CDS
came out 100x too large (#2235), and Angel currency is /1e7 (#2377). Treat a
multiplier of 0 or less as 1.

## NUANCE — subscribe, unsubscribe and resubscribe

- **Batch.** Gather subscribes for a short window (about 0.5 s), then send one
  request per mode, capped at the broker's per-request limit (Wisdom: 50). A
  refused batch is retried one instrument at a time; a failed send goes back on
  the queue with a bounded retry count (Tradejini: 3). An unsubscribe for an
  instrument still queued removes it from the queue instead of sending a frame
  (Firstock, RMoney, Pocketful #2176; Wisdom #2469; Tradejini #2359).
- **Resubscribe after the auth ack, not from `on_open`**, from a copy of the
  subscription state taken under the lock. Iterating the live dict while
  request threads changed it raised mid-loop and silently skipped every later
  scrip (Motilal).
- **No network wait under the shared lock.** Copy what you need under the lock
  and send outside it (Wisdom sent one blocking HTTP POST per scrip under the
  adapter lock, #2469). Callers that arrive while a connection is being made
  wait for that connection instead of opening a second one (Pocketful,
  AliceBlue).
- **Frames follow the order the state changed.** Re-check the wanted state at
  send time, so a late subscribe cannot bring back an instrument unsubscribed
  meanwhile. Guard snapshots with a generation, so a late partial packet cannot
  rebuild one an unsubscribe removed. Unsubscribing during the handshake still
  retracts the state. A subscribe the broker refuses (its limit) is reported as
  a failure and rolled back, not acknowledged (HDFC Sky #2397).
- Unsubscribing the last symbol does not stop the feed, and an unsubscribed
  symbol must not come back on reconnect (Wisdom #2469).
- **A feed that replaces the whole set on each subscribe** gets the full set,
  once per type, after a short debounce, never in chunks (Nuvama #2461).
- **`initialize()` stops the previous client before replacing it**: the proxy
  re-initializes in place after a failed connect (Nuvama). Give each
  connection its own stop `Event`, publish the socket under the lock
  `disconnect()` takes, ignore an `on_open` from a socket that is no longer
  current, and wait with `stop_event.wait(delay)`, not `time.sleep` (Pocketful).
  Bound any receive buffer you keep (Nuvama, 1 MB).
- **Clear caches on disconnect** (previous close, merged snapshot, depth book),
  or the first ticks after a reconnect carry the last session's values (Dhan,
  Groww #2377; Tradejini #2359). Keep snapshots only for subscribed
  instruments, or the dict grows without bound (5paisa #2397). Clear a released
  instrument's cached tick even when its unsubscribe send fails (Pocketful).
