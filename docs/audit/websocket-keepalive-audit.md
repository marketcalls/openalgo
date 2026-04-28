# WebSocket Keepalive & Reconnection Audit

**Scope:** All 32 broker streaming integrations under `broker/*/streaming/` (and `broker/*/api/*websocket*.py` for adapter-only brokers).
**Tracking issue:** [#1101 — Standard WebSocket Ping/Heartbeat](https://github.com/marketcalls/openalgo/issues/1101).
**Audit date:** 2026-04-28.
**Source of truth:** code, not documentation. Every value below was read directly from the broker's streaming files.

## 1. Executive Summary

The 32 broker integrations use **five different transport stacks** (websocket-client, websockets-async, python-socketio, custom HSWebSocket, NATS-over-WS, REST polling), and within each stack the keepalive policy is set per-broker by whoever wrote the integration. There is no platform-wide standard.

### What's good

- **27 of 32 brokers have working auto-reconnect** at either the WS layer, the adapter layer, or both. The exponential-backoff-5s-to-60s-with-10-retries pattern has emerged as a de-facto convention used by ~20 brokers.
- **Resubscription on reconnect** is implemented in nearly every broker that has reconnect logic. State is preserved in adapter-level dicts and replayed on the next successful `on_open`.
- **Three brokers explicitly detect silent stalls** (data flowing == 0 even though TCP is alive) via a separate health-check thread monitoring `_last_message_time`: **Angel, Fyers HSM, Upstox, Zerodha, Flattrade, Samco, Shoonya, Zebu, Motilal**. This is the most VPS-resilient pattern.

### What's not

- **9 brokers have no ping configuration at all** at the websocket-client layer (rely purely on TCP keepalive, server-side pings, or app-level heartbeats). Three of those have neither WS-level nor app-level heartbeats: **Wisdom, Tradejini, Compositedge, FivepaisaXTS, Ibulls, IIFL, Jainamxts** (Socket.IO transport hides this concern, but it still means OpenAlgo has no visibility into liveness).
- **18 brokers have no silent-stall detection.** They rely entirely on the WebSocket library's ping/pong to notice a dead connection. On a sleeping VPS or NAT-translated cloud network, this can leave a "connected" socket delivering zero ticks indefinitely.
- **Ping intervals across the fleet vary from 10s (Angel, FivePaisa, Fyers TBT) to 295s (RMoney) to "never" (8 brokers).** No reason for the spread other than what each integrator copied from the broker's reference SDK.
- **No broker reads its keepalive policy from environment variables.** Every interval, every timeout, every retry count is hardcoded in source.
- **Three brokers have dual reconnect mechanisms** (WS layer + adapter layer both retrying): **Angel, Motilal, Paytm, Indmoney, Dhan_sandbox**. This can produce retry storms on flapping connections.

### What we should do

A single shared `base_adapter.py` constants block reading from `WS_PING_INTERVAL`, `WS_HEALTH_CHECK_INTERVAL`, `WS_DATA_TIMEOUT`, `WS_HEARTBEAT_TIMEOUT` env vars (per Issue #1101 proposal), with each broker's hardcoded constants replaced by `int(os.getenv(...))` reads. Default values preserved for backward compatibility. See §6.

## 2. Master Matrix

Legend: **Lib** = transport library. **Ping** = WS-frame ping interval (seconds) / timeout. **App HB** = application-level JSON heartbeat interval. **Health** = dedicated thread monitoring `last_message_time`. **Data TO** = seconds without a message that triggers a forced reconnect. **Retries** = max reconnect attempts. **Backoff** = base seconds × multiplier capped at max-delay.

| # | Broker | Lib | Ping | App HB | Health | Data TO | Retries | Backoff | Notes |
|--|---|---|---|---|---|---|---|---|---|
| 1 | aliceblue | ws-client | none | 30s `{"k":"","t":"h"}` | ❌ | none | 10 (adapter) | 5×2ⁿ→60 | Heartbeat-only liveness. No stall detection. |
| 2 | angel | ws-client | 10s `"ping"` | none | ✅ 30s | 90 | 1 (ws) + 10 (adapter) | 10×2ⁿ→60 | Dual reconnect layers. Strongest stall detection. |
| 3 | compositedge | socketio | engine.io managed | none | ❌ | none | 10 | 5×2ⁿ→60 | Reconnect on disconnect callback only. |
| 4 | definedge | ws-client | none | 50s `{"t":"h"}` | ❌ | none | 5 (ws) + 10 (adapter) | 5×2ⁿ→60 | 50s heartbeat is unusually long. Dual reconnect. |
| 5 | deltaexchange | ws-client | 30/10 | none | ❌ | none | 5 | 5×2ⁿ→60 | Sub `_active_sub_msgs` replayed every reconnect. |
| 6 | dhan | ws-client | 30/10 | none | ❌ | none | 10 | 5×2ⁿ→60 | **Resubscribe NOT automated** — caller must re-call. Fatal-error short-circuit on 429/blocked/expired. |
| 7 | dhan_sandbox | websockets-async | 30/10 | 15s | ❌ | none | 10+10 | 1×2ⁿ→60 (ws), 5×2ⁿ→300 (adapter) | Async + sync hybrid. Heartbeat (15s) shorter than ping (30s) — wasteful. Dual layer. |
| 8 | firstock | ws-client | 30/10 | none | ✅ pong-monitor | implicit pong-timeout | 5 | **fixed 5s** | Cleanest supervisor pattern. **Only broker without exponential backoff** (5s flat between retries). |
| 9 | fivepaisa | ws-client | 10/- | none | ❌ | none | 10 | 5×2ⁿ→60 | No health check, shortest WS-ping interval. |
| 10 | fivepaisaxts | socketio | engine.io managed | none | ❌ | none | 10 | 5×2ⁿ→60 | XTS family — identical to ibulls/iifl/jainamxts. |
| 11 | flattrade | ws-client | 30/10 | 30s `{"t":"h"}` | ✅ 30s | **120** | 10 | 5×2ⁿ→60 | Triple-layer keepalive (WS ping + app HB + health). Robust. |
| 12 | fyers (HSM) | ws-client | server-driven | none | ✅ 30s | 90 | 10 | 5×2ⁿ→60 | Binary HSM protocol; server pings invisible to code. |
| 13 | fyers (TBT) | ws-client | **disabled (0)** | 10s text `"ping"` | ❌ | none | 10 | 5+/5-attempts→30 | 50-level depth only. Linear-ish backoff. Pong response not validated. |
| 14 | groww | ws-client + NATS | 30/10 | 10s NATS PING | ❌ | none | **unbounded** | fixed 5s | NATS protocol; **no max-retry cap**, retries forever while running=True. |
| 15 | ibulls | socketio | engine.io managed | none | ❌ | none | 10 | 5×2ⁿ→60 | XTS family. |
| 16 | iifl | socketio | engine.io managed | none | ❌ | none | 10 | 5×2ⁿ→60 | XTS family. |
| 17 | iiflcapital | **REST polling 0.8s** | n/a | n/a | n/a | n/a | none | n/a | **Not a WebSocket.** Polls REST every 800ms. No reconnect concept. |
| 18 | indmoney | ws-client | 30/- `"ping"` payload | none | passive (last_pong only) | none | 5 (ws) + 10 (adapter) | 5×2ⁿ→60 | Dual reconnect; effective limit 10. last_pong tracked but not actively monitored. |
| 19 | jainamxts | socketio | engine.io managed | none | ❌ | none | 10 | 5×2ⁿ→60 | XTS family. Socket.IO auto-reconnect not explicitly disabled — possible double-reconnect race. |
| 20 | kotak | ws-client (HSWebSocketLib) | 30/10 | none | ❌ | none | 10 (adapter) | 5×2ⁿ→60 | Proprietary HSWebSocket library wrapper. |
| 21 | motilal | ws-client | none | none | ✅ passive 60s | implicit (returns False if stale) | 5 (ws) + 10 (adapter) | adapter 5×2ⁿ→60, ws 2ⁿ→30 | No active health-check thread; `is_websocket_connected()` is on-demand. Dual reconnect. |
| 22 | mstock | ws-client | 20/10 | none | ❌ | none | 10 (ws-internal) | 2×1.5ⁿ→60 | Only broker using **1.5× multiplier** (gentler escalation). |
| 23 | nubra | ws-client | 20/10 | none | ❌ | none | **50** | 2×2ⁿ→60 | Highest retry cap of any broker (tied with Zerodha). |
| 24 | paytm | ws-client | 30/- (HEART_BEAT_INTERVAL=30) | none | last_pong tracked | none | 5 (ws) + 10 (adapter) | 5×2ⁿ→60 | Dual reconnect. |
| 25 | pocketful | ws-client | none | 15s `{"a":"h"}` | ❌ | none | 10 | 5×2ⁿ→60 | App heartbeat is sole keepalive. |
| 26 | rmoney | socketio + engine.io | **295/295** | none | ❌ | none | 10 (adapter) | 5×2ⁿ→60 | Floor of 300s on engine.io activity timeout. Socket.IO auto-reconnect explicitly **disabled** to prevent double-reconnect. |
| 27 | samco | ws-client | 30/10 | none | ✅ 30s | **120** | 10 | 5×2ⁿ→60 | Strong stall detection. |
| 28 | shoonya | ws-client | 30/10 | 30s `{"t":"h"}` | ✅ 30s | **120** | 10 | 5×2ⁿ→60 | Dual heartbeat (WS + app). Timer-based reconnect (not thread-based). |
| 29 | tradejini | ws-client | none | none (server-initiated only) | ❌ | none | 10 | 5×2ⁿ→60 | No client-initiated keepalive. |
| 30 | upstox | ws-client | 30/10 | none | ✅ dedicated loop | 90 | 5 | 2×2ⁿ→30 | Lower max-delay cap (30s) than fleet norm. |
| 31 | wisdom | socketio | engine.io managed | none | ❌ | none | **none** | n/a | No reconnect logic at WS layer. Hybrid HTTP+WS architecture. **Worst keepalive coverage in the fleet.** |
| 32 | zebu | ws-client | 30/10 | 30s app HB | ✅ 30s | **120** | (config in adapter) | adapter exp | Similar to shoonya pattern. |
| 33 | zerodha | ws-client | 30/10 + server 1-byte HB | none | ✅ 30s | 90 | **50** | 1.5×→60 | Tracks `last_heartbeat_time` and `last_message_time` separately. Unique 1.5× multiplier. |

(33 rows because Fyers has two distinct WS protocols — HSM and TBT — counted separately.)

## 3. Categorization

### 3.1 By transport library

| Stack | Brokers |
|---|---|
| `websocket-client` (sync `WebSocketApp.run_forever`) | aliceblue, angel, definedge, deltaexchange, dhan, firstock, fivepaisa, flattrade, fyers (HSM+TBT), groww, indmoney, kotak, motilal, mstock, nubra, paytm, pocketful, samco, shoonya, tradejini, upstox, zebu, zerodha |
| `python-socketio` (Socket.IO over engine.io) | compositedge, fivepaisaxts, ibulls, iifl, jainamxts, rmoney, wisdom |
| `websockets` (async) | dhan_sandbox |
| Custom (HSWebSocketLib) | kotak (wrapper around websocket-client) |
| NATS over WebSocket | groww |
| **REST polling** (no WS) | iiflcapital |

### 3.2 By keepalive coverage

| Tier | Brokers | Description |
|---|---|---|
| **Tier 1 — Robust** (WS ping + app HB + active health check + data-timeout) | flattrade, samco, shoonya, zebu | Triple-layer: detects TCP-dead, application-dead, AND silent-data-stall. |
| **Tier 2 — Strong** (WS ping + active health check + data-timeout, no app HB) | angel, fyers HSM, upstox, zerodha | Detects TCP-dead and silent-data-stall. |
| **Tier 3 — Standard** (WS-level ping only, no health check) | dhan, deltaexchange, fivepaisa, kotak, mstock, nubra, paytm | TCP-dead detection only. Will not notice silent stalls. |
| **Tier 4 — App-heartbeat-only** (no WS-level ping, JSON heartbeat on a timer) | aliceblue, definedge, fyers TBT, pocketful | Liveness depends on a single timer thread. |
| **Tier 5 — Transport-managed** (Socket.IO / engine.io / NATS handles its own heartbeat invisibly) | compositedge, fivepaisaxts, ibulls, iifl, jainamxts, rmoney, groww | OpenAlgo has zero visibility into liveness. |
| **Tier 6 — Weak / missing** | tradejini (no client-initiated keepalive), motilal (passive on-demand only), wisdom (no reconnect, no health), iiflcapital (REST polling) | Lowest resilience. |

### 3.3 By reconnect strategy

| Strategy | Brokers | Notes |
|---|---|---|
| **Exponential 5s × 2ⁿ → 60s, 10 retries** (fleet de-facto standard) | ~18 brokers | The pattern propagated by copy-paste. |
| Exponential, 50 retries | nubra, zerodha | More aggressive. Zerodha uses 1.5× multiplier. |
| Exponential, 5 retries | deltaexchange, upstox | More conservative. Upstox caps at 30s. |
| Fixed delay (no backoff) | firstock (5s), groww (5s) | Firstock supervisor pattern. Groww **has no max retries**. |
| 1.5× multiplier instead of 2× | mstock, zerodha | Gentler escalation. |
| **Dual reconnect (WS-layer + adapter-layer)** — risk of retry storms | angel, definedge, motilal, paytm, indmoney, dhan_sandbox | Both layers retry independently; can produce 2× the actual reconnect attempts. |
| **No reconnect at all** | wisdom, iiflcapital | wisdom relies on Socket.IO defaults; iiflcapital is REST polling. |

## 4. Per-Broker Findings (Detailed)

> The Section 2 matrix and Section 3 categorization are the audit's primary output. The following per-broker notes capture quirks, file paths, and code references that the matrix can't carry.

### 4.1 websocket-client cohort

#### Angel (`broker/angel/streaming/`)
- `smartWebSocketV2.py` uses `run_forever(ping_interval=10, ping_payload="ping")`. Server replies `"pong"`. `last_pong_timestamp` and `last_ping_timestamp` both tracked.
- `_health_check_loop` runs every 30s checking `_last_message_time`. If gap > 90s, calls `_force_reconnect()`.
- **Dual reconnect**: WS layer has `max_retry_attempt=1` (essentially gives up after one try); adapter (`angel_adapter.py`) has `max_reconnect_attempts=10` with exponential backoff.
- `RESUBSCRIBE_FLAG` triggers full resubscribe after every reconnect.
- `_reconnecting` mutex prevents concurrent reconnect attempts.

#### Aliceblue (`broker/aliceblue/streaming/`)
- `aliceblue_client.py` calls `run_forever()` with no ping args.
- 30s app heartbeat thread sends `{"k": "", "t": "h"}` (broker requires heartbeat within 50s per code comment).
- Adapter manages reconnection; per-attempt daemon thread.
- **Gap:** no health-check thread; reconnect only triggered by error/disconnect, not by data stall.

#### Definedge (`broker/definedge/streaming/`)
- `definedge_websocket.py` uses `run_forever()` without ping args.
- 50s app heartbeat thread sends `{"t": "h"}`. **50s is unusually long** — risks blind window if connection silently dies.
- WS layer max retries 5; adapter max retries 10. **Dual reconnect.**
- Stored subscriptions replayed via dict.

#### Deltaexchange (`broker/deltaexchange/streaming/`)
- `delta_websocket.py` uses `run_forever(ping_interval=30, ping_timeout=10)`.
- `HEARTBEAT_INTERVAL = 30`. No app HB.
- Single-layer reconnect (cleaner than most). `_active_sub_msgs` replayed every reconnect — never cleared.
- 5 retries.

#### Dhan (`broker/dhan/streaming/`)
- `dhan_websocket.py`: `run_forever(ping_interval=30, ping_timeout=10)`.
- Recognizes broker response code `0` as heartbeat ack (silently consumed).
- **Fatal-error short-circuit**: matches "429", "too many requests", "client id is blocked", "subscription", "plan" — sets `_fatal_error=True` and stops reconnecting.
- **Subscriptions stored but NOT auto-replayed** on reconnect — caller responsibility.

#### Dhan_sandbox (`broker/dhan_sandbox/streaming/`)
- Async via `websockets` library: `ping_interval=30, ping_timeout=10`.
- Sync app heartbeat at **15s** — out of sync with the 30s ping. Wasteful.
- WS-layer max 10 retries (1s base, 60s cap, jittered 0.8–1.2). Adapter-layer max 10 retries (5s base, 300s cap).
- **Dual reconnect** combined with both layers having 10 retries → up to 20 total attempts.

#### Firstock (`broker/firstock/streaming/`)
- `firstock_websocket.py`: `run_forever(ping_interval=30, ping_timeout=10)`.
- Pong-monitor thread (`_monitor_connection`) tracks `last_pong_time`.
- **Fixed 5s retry delay — only broker without exponential backoff.**
- Single supervisor thread (no per-attempt thread spawn). Cleanest lifecycle in the fleet.
- Max 5 retries.

#### Fivepaisa (`broker/fivepaisa/streaming/`)
- `fivepaisa_websocket.py`: `run_forever(ping_interval=10)` only — no `ping_timeout`. **Shortest WS ping interval in fleet alongside Angel.**
- No health-check thread.
- Adapter exponential backoff, 10 retries, 60s cap.

#### Flattrade (`broker/flattrade/streaming/`)
- `run_forever(ping_interval=30, ping_timeout=10)` PLUS app heartbeat (`{"t": "h"}`) every 30s.
- `_heartbeat_worker` thread also functions as health-check: if `_last_message_time` > 120s old, closes the WS.
- 10 retries, exponential, scheduled via `threading.Timer` with cancellation on disconnect.
- **Tier 1 — strongest coverage in fleet.**

#### Fyers HSM (`broker/fyers/streaming/fyers_hsm_websocket.py`)
- `run_forever()` without ping config — Fyers' binary HSM protocol manages it server-side.
- `_health_check_thread` runs every 30s; data timeout 90s.
- Pending subscriptions replayed on reconnect.
- (Fyers also fixes today's commit `5eb7baaa` that was scrambling HSM↔OpenAlgo symbol mappings — see issue #1093.)

#### Fyers TBT (`broker/fyers/streaming/fyers_tbt_websocket.py`)
- 50-level depth only, NSE/NFO equity only.
- `run_forever(ping_interval=0)` — explicit disable. App-level text `"ping"` every 10s instead.
- **Pong response received but never validated for timeout.**
- Linear-ish backoff: 0s for attempts 1–4, +5s every 5 attempts, capped at 30s.
- No health check thread.

#### Groww (`broker/groww/streaming/`)
- NATS protocol over WebSocket. `run_forever(ping_interval=30, ping_timeout=10)`.
- Additional NATS PING every 10s via daemon thread.
- **No max-retry cap** — retries indefinitely while `running=True`.
- Two heartbeat mechanisms (WS 30s + NATS 10s) is redundant.

#### Indmoney (`broker/indmoney/streaming/` + `broker/indmoney/api/indWebSocket.py`)
- `run_forever(ping_interval=30, ping_payload="ping")`. No timeout.
- `last_pong_timestamp` tracked but only used post-max-retries (not as active monitor).
- WS layer: `max_retry_attempt=5`. Adapter: 10. **Dual reconnect — effective 10 max.**

#### Kotak (`broker/kotak/streaming/`)
- Wraps proprietary `HSWebSocketLib` which itself uses `websocket-client`. `run_forever(ping_interval=30, ping_timeout=10)`.
- All reconnect/resubscribe logic at adapter layer; HSWebSocketLib is stateless w.r.t. retries.
- No health check.

#### Motilal (`broker/motilal/streaming/` + `broker/motilal/api/motilal_websocket.py`)
- `run_forever()` without ping args. `_start_heartbeat()` is a **no-op** (line 1105–1112).
- Health check is **passive on-demand** via `is_websocket_connected()` checking if `last_message_time` < 60s ago. No background thread.
- WS retry max 5; adapter max 10. **Dual reconnect.**
- Daemon threads tracked and joined on disconnect to prevent orphans.

#### Mstock (`broker/mstock/streaming/` + `broker/mstock/api/mstockwebsocket.py`)
- `run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=20, ping_timeout=10)`.
- WS-internal retry loop: max 10. **Uses 1.5× multiplier** (only broker besides Zerodha) — gentler escalation: `min(2 * 1.5ⁿ, 60)`.
- No health check.

#### Nubra (`broker/nubra/streaming/` + `broker/nubra/api/nubrawebsocket.py`)
- `run_forever(ping_interval=20, ping_timeout=10)`.
- **Max 50 retries** (highest in fleet alongside Zerodha).
- Backoff: `min(2 * 2ⁿ⁻¹, 60)` capped at attempt 5 in the exponent (so multiplier flat at 32 thereafter).

#### Paytm (`broker/paytm/streaming/`)
- `run_forever(ping_interval=30)` (no `ping_timeout`).
- `last_pong_timestamp` tracked.
- WS retry max 5; adapter max 10. **Dual reconnect.**

#### Pocketful (`broker/pocketful/streaming/`)
- Adapter-only file; WS opened inline via `websocket.WebSocketApp`. `run_forever()` with no ping args.
- 15s app heartbeat thread sends `{"a": "h"}`.
- 10 retries, exponential.

#### Samco (`broker/samco/streaming/` + `broker/samco/api/samcoWebSocket.py`)
- `run_forever(ping_interval=30, ping_timeout=10)`.
- `_heartbeat_worker` thread monitors `_last_message_time`; closes connection on 120s gap.
- 10 retries, exponential, mutex-guarded.

#### Shoonya (`broker/shoonya/streaming/`)
- **Dual heartbeat:** `run_forever(ping_interval=30, ping_timeout=10)` + app `{"t":"h"}` every 30s.
- `_heartbeat_worker` checks `_last_message_time` under lock; 120s timeout.
- **Timer-based reconnect** (`threading.Timer`, not a thread) — unique pattern in fleet.
- 10 retries, exponential.

#### Tradejini (`broker/tradejini/streaming/` + `nxtradstream.py`)
- `run_forever()` with no ping args. **No client-initiated keepalive of any kind.**
- Server-initiated PING via packet type 16; `sendPing()` available on demand but not on a timer.
- Adapter handles reconnect (10 retries, exponential).

#### Upstox (`broker/upstox/streaming/`)
- `upstox_client.py` (note: no `_websocket.py` filename) uses `run_forever(ping_interval=30, ping_timeout=10)`.
- Dedicated `_health_check_loop` thread. `_last_message_time` updated on every message AND on open.
- `DATA_TIMEOUT = 90`. 5 retries (lower than fleet norm). **Backoff capped at 30s** (lower than fleet 60s norm).

#### Zebu (`broker/zebu/streaming/`)
- `run_forever(ping_interval=30, ping_timeout=10)` + app heartbeat `"h"` type every 30s.
- `_heartbeat_worker` monitors `_last_message_time`; 120s timeout.
- Reconnect/retry parameters in adapter Config class.

#### Zerodha (`broker/zerodha/streaming/`)
- `run_forever(ping_interval=30, ping_timeout=10)` + recognizes Zerodha's **1-byte binary heartbeat** (server-initiated, separate from WS-frame ping).
- `_health_check_loop` tracks both `last_message_time` (90s timeout) AND `last_heartbeat_time` (60s timeout).
- **50 retries, 1.5× multiplier** capped at 60s.
- Subscribe batching: max 200 tokens per call, max 3000 per connection.

### 4.2 Socket.IO cohort (XTS family + others)

#### Compositedge / Fivepaisaxts / Ibulls / IIFL / Jainamxts (XTS family)
- All use `python-socketio.Client`. No explicit `ping_interval`/`ping_timeout` — engine.io transport-level heartbeat handles it (opaque to OpenAlgo).
- Adapter-layer reconnect: 10 retries, `5 × 2ⁿ → 60s` exponential.
- Subscriptions stored, replayed via `_resubscribe_all()` after `on_connect`.
- **Gap:** no health-check thread. No data-timeout. If engine.io's internal heartbeat hangs, OpenAlgo learns about it only via `on_disconnect` callback.
- **Jainamxts caveat:** Socket.IO's built-in auto-reconnect is **not explicitly disabled**, so two reconnect mechanisms (Socket.IO + adapter) may race.

#### Rmoney
- Socket.IO with engine.io. `MIN_ENGINEIO_ACTIVITY_TIMEOUT = 300s`. Constructor pre-sets `eio.ping_interval = eio.ping_timeout = 295s`, then `_apply_engineio_timeout_floor()` enforces the 300s floor.
- Socket.IO auto-reconnect explicitly **disabled** (`reconnection=False`) — the only Socket.IO broker that does this. Eliminates the double-reconnect race that jainamxts has.
- Adapter `_reconnect_worker` thread: 10 retries, `5 × 2ⁿ → 60s`.

#### Wisdom
- Socket.IO. **No explicit ping configuration.**
- **No reconnect logic at WebSocket layer.** Subscriptions managed via HTTP REST endpoints (POST/PUT) — hybrid architecture.
- Adapter has only login-retry on `initialize()`, no WS-reconnect.
- **Worst keepalive coverage in the fleet** — explicit recommendation to harden.

### 4.3 Outliers

#### Iiflcapital
- **Not a WebSocket integration.** Pure REST polling at 800ms interval (configurable via `IIFLCAPITAL_POLL_INTERVAL`).
- No reconnect concept; failed polls logged and skipped.
- Out of scope for keepalive standardization.

## 5. Gaps Identified

Numbered for traceability when filing follow-up issues.

1. **Hardcoded constants everywhere.** No broker reads keepalive intervals from `WS_PING_INTERVAL` / `WS_HEALTH_CHECK_INTERVAL` / `WS_DATA_TIMEOUT` / `WS_HEARTBEAT_TIMEOUT` env vars. Tuning for production today requires patching source.
2. **18 brokers cannot detect silent stalls** (no active `last_message_time` health-check thread): aliceblue, compositedge, definedge, deltaexchange, dhan, fivepaisa, fivepaisaxts, fyers TBT, groww, ibulls, iifl, indmoney, jainamxts, kotak, mstock, nubra, paytm, pocketful, rmoney, tradejini, wisdom. (Motilal's passive on-demand check is borderline — counted out of this list because it does check.)
3. **Dhan does not auto-resubscribe after reconnect.** Subscriptions are stored but not replayed; caller must re-call `subscribe(...)` manually. Will produce silent data gaps.
4. **Dual reconnect mechanisms** in angel, definedge, motilal, paytm, indmoney, dhan_sandbox can produce retry storms on flapping connections.
5. **Groww has no max-retry cap.** Retries forever while `running=True`. Should cap to align with fleet.
6. **Wisdom has no reconnect logic** at the WebSocket layer.
7. **Jainamxts has racing reconnect mechanisms** (Socket.IO auto-reconnect not disabled, adapter also reconnects). Should mirror rmoney's `reconnection=False`.
8. **Definedge's 50s app heartbeat** is unusually long; 30s aligns with fleet norm.
9. **Fyers TBT does not validate pong response** — silent ping failure goes undetected.
10. **Dhan_sandbox heartbeat (15s) is shorter than its ping (30s)** — wasteful; should match.
11. **Iiflcapital uses REST polling** instead of WebSocket. Not a bug per se, but inconsistent with platform pattern. Out of scope for this issue.

## 6. Recommendation — Standardization Plan

Aligned with Issue #1101's environment-variable proposal. Below is the audit-grounded version with default values calibrated against what's actually deployed today.

### 6.1 Environment variables

```env
# Per-connection ping (WebSocket-frame level)
WS_PING_INTERVAL=30        # seconds; brokers that support client-side ping
WS_PING_TIMEOUT=10         # seconds; pong wait before declaring connection dead

# App-level heartbeat (JSON message on a timer)
WS_APP_HEARTBEAT_INTERVAL=30   # seconds; brokers that need an app-level "h" message

# Active health-check (separate thread monitoring last_message_time)
WS_HEALTH_CHECK_INTERVAL=30    # seconds; how often the thread polls
WS_DATA_TIMEOUT=90             # seconds without any message → forced reconnect

# Reconnection
WS_RECONNECT_BASE_DELAY=5      # seconds; initial backoff
WS_RECONNECT_MAX_DELAY=60      # seconds; max backoff cap
WS_RECONNECT_MAX_TRIES=10      # max attempts before giving up
WS_RECONNECT_MULTIPLIER=2.0    # exponential backoff multiplier
```

Defaults mirror the fleet's de-facto standard (~18 brokers already use `5s × 2ⁿ → 60s, 10 retries`).

### 6.2 Code changes (rollup)

**Add a shared block to `websocket_proxy/base_adapter.py`:**

```python
import os

WS_PING_INTERVAL          = int(os.getenv("WS_PING_INTERVAL", "30"))
WS_PING_TIMEOUT           = int(os.getenv("WS_PING_TIMEOUT", "10"))
WS_APP_HEARTBEAT_INTERVAL = int(os.getenv("WS_APP_HEARTBEAT_INTERVAL", "30"))
WS_HEALTH_CHECK_INTERVAL  = int(os.getenv("WS_HEALTH_CHECK_INTERVAL", "30"))
WS_DATA_TIMEOUT           = int(os.getenv("WS_DATA_TIMEOUT", "90"))
WS_RECONNECT_BASE_DELAY   = int(os.getenv("WS_RECONNECT_BASE_DELAY", "5"))
WS_RECONNECT_MAX_DELAY    = int(os.getenv("WS_RECONNECT_MAX_DELAY", "60"))
WS_RECONNECT_MAX_TRIES    = int(os.getenv("WS_RECONNECT_MAX_TRIES", "10"))
WS_RECONNECT_MULTIPLIER   = float(os.getenv("WS_RECONNECT_MULTIPLIER", "2.0"))
```

**Per-broker substitutions:** every hardcoded `30`, `5`, `10`, `60`, `90`, `120` etc. that controls keepalive becomes a read from one of the constants above. Broker-specific defaults can be preserved by passing the constructor argument:

```python
# Was:
HEART_BEAT_INTERVAL = 10
# Becomes:
HEART_BEAT_INTERVAL = int(os.getenv("WS_PING_INTERVAL", "10"))
```

(Keep `10` as Angel's own default if you don't want to disrupt a known-good broker; the env var still wins when set.)

### 6.3 Higher-impact fixes (separate from env-var rollup)

These are not just configuration — they're behavioral gaps that should be filed as their own issues:

- **G2 (silent-stall detection):** Add an active health-check thread to the 18 Tier-3/4/5 brokers that lack one. The pattern is well-established in angel/zerodha/upstox/flattrade/samco/shoonya/zebu — copy it.
- **G3 (Dhan auto-resubscribe):** Replay `_subscriptions` dict in `on_open` after reconnect.
- **G4 (dual reconnect):** Pick one layer per broker. The adapter layer is generally the right one to keep (it owns the subscription state).
- **G5 (Groww unbounded retries):** Cap at `WS_RECONNECT_MAX_TRIES`.
- **G6 (Wisdom):** Add adapter-level reconnect loop using the standard pattern.
- **G7 (Jainamxts double-reconnect):** Set `reconnection=False` on the Socket.IO client to match rmoney.
- **G9 (Fyers TBT):** Track pong-timestamp and trigger reconnect on stale pong.

### 6.4 Verification

The same plan from Issue #1101 applies, plus:

- After the rollup, run `grep -rn "ping_interval\|HEART_BEAT_INTERVAL\|HEARTBEAT_INTERVAL\|HEALTH_CHECK_INTERVAL\|DATA_TIMEOUT" broker/` and confirm every constant either reads from `os.getenv(...)` or is documented as broker-protocol-fixed.
- Set `WS_PING_INTERVAL=15` in `.env`, restart, and verify each broker's logs show 15s intervals (or document why a broker is exempt — e.g., rmoney's 300s engine.io floor).
- For Tier-3/4/5 brokers receiving new health-check threads, set `WS_DATA_TIMEOUT=30` and confirm the thread fires `_force_reconnect` after 30s of synthetic silence.

## 7. Out of scope

- The WebSocket Proxy server (`websocket_proxy/server.py`) handles client-initiated `{"action":"ping"}` from SDKs and responds with `{"type":"pong",...}`. That's the *external* keep-alive between SDK clients and OpenAlgo, separate from this audit which covers the *internal* keep-alive between OpenAlgo and the brokers. Issue #1101 mentions both; this audit only covers the latter.
- IIFLCapital's REST-polling adapter. Not a WebSocket; separate concern.
- Today's Fyers fixes (#1093 routing fix `5eb7baaa`, #1243 multiquotes fix `15c2c63b`, batching fix `671b8548`) — those are functional fixes, not keepalive.

---

**Audit completed by:** parallel scan of all 32 broker `streaming/` directories.
**Maintenance:** when adding a new broker, add a row to §2 and place it in the appropriate §3 tier.
