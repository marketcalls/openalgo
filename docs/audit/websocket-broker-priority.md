# WebSocket Broker Priority Audit

**Scope:** All broker WebSocket integrations under `broker/*/streaming/`, the WebSocket proxy layer (`websocket_proxy/`), service-layer code in `services/` that depends on live broker streams, and cross-platform deployment compatibility (Windows/macOS dev → Docker/Ubuntu+gunicorn+eventlet production).
**Date:** 2026-05-04 (revised for 24×7×365 self-hosted reality, weekend/holiday gap, and cross-platform deployment).
**Companion to:** [`websocket-keepalive-audit.md`](./websocket-keepalive-audit.md) (transport/keepalive layer) and Issue [#1101 — Standard WebSocket Ping/Heartbeat](https://github.com/marketcalls/openalgo/issues/1101).
**Source of truth:** code (every defect cited with `file:line`).

---

## 1. Purpose & Real-World Workload

The keepalive audit catalogs **what each broker does** for ping/heartbeat. This document identifies **which brokers are broken or fragile under OpenAlgo's actual self-hosted production workload**, ranked by impact, with concrete defects and a phased remediation plan.

### 1.1 The deployment reality

OpenAlgo is **self-hosted by individual traders** on their own server (per CLAUDE.md: "Single user per deployment — no multi-user, no privilege escalation. One user, one broker session per instance."). The realistic operational profile:

| Dimension | Reality |
|---|---|
| **Server uptime** | **24×7×365.** Process never stops. Trader doesn't restart between sessions. |
| **Symbol count** | **1000+** active subscriptions per session (option chains, scanners, multi-strategy portfolios). |
| **Daily session** | 9:15am equity open → 11:55pm commodity close → 3:30 AM IST quiet window → next-day open. |
| **Token lifecycle** | **Daily expiry at ~3:00 AM IST.** Per CLAUDE.md: "Indian broker tokens expire daily at ~3:00 AM IST. Session management is aligned to this schedule." |
| **Weekend gap** | **Friday 11:55pm → Monday 8:00am.** Trader doesn't login Sat/Sun/holidays. Adapter sits with stale token for **48-72+ hours**. |
| **Indian holidays** | Multi-day gaps (Diwali, Holi, election days). Some 3-4 day stretches with no trader login. |
| **Crypto traders** | Delta Exchange runs 24/7. No 3am gap. Different lifecycle. |
| **Network conditions** | VPS / NAT / consumer broadband. Silent stalls common. Brief drops every few hours typical. |
| **Cross-platform** | Dev: Windows + macOS (Flask dev server, threading). Prod: Docker + Ubuntu direct (gunicorn + eventlet + systemd). |

### 1.2 Deployment paths (per `install/install.sh`, `install/install-docker.sh`)

| Path | Server | Worker | Implications for WebSocket code |
|---|---|---|---|
| **Dev (Win/Mac/Linux)** | Flask dev server (`uv run app.py`) | Standard `threading` | `asyncio` works. `time.sleep()` blocks OS thread. SQLite locking is OS-dependent (Windows strictest). |
| **Production (Ubuntu direct)** | `gunicorn --worker-class eventlet -w 1` (`install/install.sh:1151-1166`) + systemd | Single eventlet worker | Per CLAUDE.md: `asyncio.run()`/`async/await` **incompatible** with eventlet monkey-patching unless run on a separate real OS thread. `time.sleep()` is cooperative (yields green thread). `threading.local()` maps to green-thread-local. |
| **Production (Docker)** | `gunicorn --worker-class eventlet -w 1` + container | Single eventlet worker | Same as Ubuntu direct. Adds container restart semantics on hang. |

**Critical implication:** **code must work in both dev (threading) and production (eventlet).** A bug that's invisible on a developer's Mac may surface only after deploying to gunicorn+eventlet on a customer's server.

### 1.3 What "smooth operation" means for this workload

A WebSocket layer is healthy if **all** these hold:

1. Survives 12-hour sessions without leaking memory, threads, or file descriptors.
2. Recovers transparently from transient network drops (no client-visible data gap).
3. **Detects auth-failure responses** (401/403/"unauthorized") and stops retrying instead of hammering dead tokens for 30+ minutes — and 50+ HOURS over a weekend.
4. **3am orchestrator does clean teardown** — clears subscription state at 3am IST every day so Monday's fresh login starts from zero. Subsequent `subscribe(symbol, exchange)` calls naturally resolve through the freshly-loaded master contract; F&O contract rotation handled transparently.
5. Restores 1000+ subscriptions in seconds, not minutes — via batched send and queue-coalescing.
6. Runs the tick hot path lock-free (or near-lock-free) so reconnect activity doesn't stall live data.
7. Shuts down cleanly within 1-2 seconds (interruptible sleeps; threads joinable).
8. Handles **Friday-to-Monday gap**: detects 3am Saturday token death, stops retrying within minutes, sits idle, then reconnects cleanly when Monday's fresh login completes.
9. Service layer (`services/`) sees consistent state when WebSocket is dead — no silent failures.
10. **Works identically on dev (threading) and prod (eventlet)** — no platform-specific bugs.

This audit measures every broker and the platform against criteria 1-10.

---

## 2. The Standardization Framework (11 invariants)

Every broker WebSocket layer should satisfy these. Source-of-truth references vary by criterion since no single broker meets all of them.

| # | Invariant | Reference | Fleet status |
|---|---|---|---|
| 1 | **Daemon-thread reconnect loop** with `while self.running` and exponential backoff (start 2s, cap 60s, max 50 attempts). | `broker/zerodha/streaming/zerodha_websocket.py:148-183` | 27/32 ✅ |
| 2 | **Resubscribe on `_on_open`** — replay tracked subscriptions, batched by mode. State persists across reconnects. | `zerodha_websocket.py:453-477` | 26/32 ✅ |
| 3 | **Health-check thread** monitoring `last_message_time`; force-close socket on data stall. | `zerodha_websocket.py:435-451` | 14/32 ✅ |
| 4 | **`_on_close` flips flags only** — never spawns threads, sleeps, or recurses. | `zerodha_websocket.py:416-424` | 28/32 ✅ |
| 5 | **Lock discipline** — never hold a lock across external I/O. Snapshot under lock; release; perform I/O. | `zerodha_websocket.py:453-477` | 24/32 ✅ |
| 6 | **Auth-failure short-circuit** — detect 401/403/"unauthorized"/"session expired"/"invalid token" and stop the reconnect loop. | `broker/firstock/streaming/firstock_websocket.py:455-485` | **4/32 ✅** |
| 7 | **Interruptible sleeps** — use `_stop_event.wait(delay)` instead of `time.sleep(delay)`. | `firstock_websocket.py:235` | **6/32 ✅** |
| 8 | **Subscribe batch-queue** — coalesce many `subscribe()` calls into one broker message. | `broker/zerodha/streaming/zerodha_adapter.py:60-62, 151-194` | **5/32 ✅** |
| 9 | **Configurable timeouts via env vars** (per #1101). | **Not implemented anywhere** | **0/32 ✅** |
| 10 | **Eventlet-safe** — no `asyncio.run()` / bare `asyncio.get_event_loop()`. Async work isolated to a real OS thread. | telegram_bot_service.py pattern (per CLAUDE.md) | **31/32 ✅** (only dhan_sandbox at risk) |
| 11 | **Weekend-gap-aware** — adapter is cleanly torn down by 3am orchestrator (Phase 4c), so subscription state doesn't carry stale tokens across multi-day gaps. Monday morning fresh login → fresh master contract → fresh `subscribe()` calls auto-resolve through normal flow. | **Not implemented anywhere** — depends on Phase 4c (3am orchestrator) + Phase 4b (`cache_loaded` listener tracking **symbols, not tokens**) | **0/32 ✅** |

**Note on previous Invariant 9 ("master-contract-aware resubscribe"):** The earlier draft of this document treated stale-token resubscribe as a separate broker-level invariant. After review, this is **automatically resolved by Phase 4c clean teardown** — once the 3am orchestrator clears `subscribed_tokens` and adapter state, every subsequent `subscribe(symbol, exchange)` call goes through `get_token()` which resolves via the freshly-downloaded `SymToken` table. F&O contract token rotation (new expiries, new strikes) is handled transparently. No per-broker change needed; only the Phase 4b listener must track **symbols, not cached tokens**, when restoring subscriptions.

**Current scoreboard:** zerodha satisfies 1, 2, 3, 4, 5, 8, 10 (7/11). flattrade and dhan also at 7/11. firstock satisfies 1, 2, 4, 5, 6, 7, 10 (7/11) — uniquely strong on auth-fail and interruptible sleeps but lacks batch-queue. **No broker satisfies 9 or 11. dhan_sandbox is the only broker at risk on 10.** Most brokers score 4-6/11.

---

## 3. Revised Priority Matrix (three axes)

A broker can be broken on **reliability** (data loss on drop), weak on **performance** (slow at 1000 symbols), or risky on **lifecycle** (weekend / 3am / auth-fail / cross-platform). The matrix below combines them.

### 3.1 Reliability priority

```
RELIABILITY HIGH (8): broken in production — silent data loss, deadlock risk, races
RELIABILITY MEDIUM (3): works in happy path; failure modes exist but rarer
RELIABILITY LOW (21): reconnect/resubscribe correct; only need #1101 env-var rollup
```

| Reliability | Brokers |
|---|---|
| **HIGH** | aliceblue, fivepaisa, groww, indmoney, mstock, samco, tradejini, wisdom |
| **MEDIUM** | compositedge, upstox, jainamxts |
| **LOW** | angel, definedge, deltaexchange, dhan, dhan_sandbox, firstock, fivepaisaxts, flattrade, fyers (HSM+TBT), ibulls, iifl, iiflcapital, kotak, motilal, nubra, paytm, pocketful, rmoney, shoonya, zebu, zerodha |

### 3.2 Performance priority

```
PERFORMANCE HIGH (4): major brokers, no batch queue, used by many traders
PERFORMANCE MEDIUM (24): no batch queue but lower-traffic OR has alt batching
PERFORMANCE LOW (5): batch-queue implemented (zerodha, dhan, flattrade, upstox, fyers)
```

| Performance | Brokers |
|---|---|
| **HIGH** (most-used brokers without batch-queue) | **angel, kotak, samco, shoonya** |
| **MEDIUM** (no batch-queue, lower traffic) | aliceblue, compositedge, definedge, deltaexchange, dhan_sandbox, firstock, fivepaisa, fivepaisaxts, groww, ibulls, iifl, iiflcapital, indmoney, jainamxts, motilal, mstock, nubra, paytm, pocketful, rmoney, tradejini, wisdom, zebu |
| **LOW** (already have batch-queue) | zerodha, dhan, flattrade, upstox, fyers (HSM, 150ms variant) |

### 3.3 Lifecycle priority (NEW)

Captures auth-fail behavior, weekend-gap survival, and cross-platform safety.

| Lifecycle issue | Brokers affected |
|---|---|
| **No auth-fail detection** → 30-min retry storm at 3am, 50+ hour storm over weekend | **28/32**: every broker except firstock, dhan, rmoney, nubra |
| **Eventlet incompatibility risk** → may break only on production gunicorn+eventlet | **dhan_sandbox** (uses asyncio + websockets-async — see §6) |
| **Non-interruptible sleeps** → slow shutdown / restart | **26/32**: most brokers use `time.sleep()` instead of `_stop_event.wait()` |
| **No weekend-gap recovery** → adapter stays dead until user manually re-subscribes | **All 32** (depends on missing service-layer `cache_loaded` listener) |

### 3.4 Combined priority — the "must fix first" list

> **Revised 2026-05-05** after cross-validation pass — see Appendix D. samco demoted from CRITICAL to HIGH (no actual dual-retry race); mstock demoted from "no callback hook" critical concern to "parallel state drift" medium concern; fivepaisa "run_forever blocks adapter" claim overstated. The five P0/P1 platform-level findings (Appendix D) reorganize the urgency landscape.

| Combined Severity | Broker / item | Reason |
|---|---|---|
| **CRITICAL (platform)** | PUB→PUB cache_invalidation bug | Cache invalidation messages from `database/cache_invalidation.py` cannot reach the proxy SUB. See Appendix D §D.1. |
| **CRITICAL (platform)** | Mode case mismatch in proxy | `server.py:80` and `:991` use different conventions for the same enum. Documented `"QUOTE"`/`"DEPTH"` may fail at runtime. See Appendix D §D.2. |
| **CRITICAL (broker)** | dhan_sandbox | Lifecycle (asyncio under eventlet — production-only failure mode invisible during dev). See §6. |
| **HIGH (platform)** | Subscribe ack correlation, 12-broker hardcoded list, ZMQ bind-to-* | See Appendix D §D.3, §D.4, §D.5. |
| **HIGH (broker)** | aliceblue, groww, indmoney, tradejini, wisdom | Reliability HIGH (real lock/race/recursion bugs); performance MEDIUM. |
| **HIGH (broker)** | samco | No batch-queue + no auth-fail. **Note:** previous "dual retry paths racing" was overstated — `samcoWebSocket.py:478` explicitly delegates reconnect to the adapter; `max_retry_attempts=5` field is unused. |
| **HIGH (broker)** | fivepaisa | Duplicate reconnect chains + no batch-queue + no auth-fail. **Note:** previous "run_forever blocks adapter retry loop" was overstated — `fivepaisa_adapter.py:100, 285` correctly wires `_on_open` → on-open resubscribe. |
| **HIGH (broker)** | angel, kotak, shoonya | Reliability LOW but Performance HIGH — slow startup at 1000 symbols frustrates users. |
| **MEDIUM (broker)** | compositedge, jainamxts, upstox, mstock | Reliability MEDIUM; varies on performance. mstock revised: SDK has self-resubscribe (`mstockwebsocket.py:253-273`); concern is parallel-state drift + missing platform integration, not "no callback hook". |
| **PLATFORM-WIDE** | All brokers | Auth-fail detection (28 missing — but **shared helpers already exist** in `base_adapter.py:523, 554` per Appendix D §D.6; just unwired in most adapters), cache_loaded listener (missing), 3am orchestrator (missing), env-var rollup (partial — proxy has `WS_PING_INTERVAL`, `WS_AUTH_GRACE_SECONDS`, etc.). |

---

## 4. Workload-specific deep audit (per-broker matrix)

Each broker scored against the 8 measurable per-broker criteria from §2. Criteria 9 (env-var) is "no" for everyone; 10 (eventlet-safe) is "yes" for everyone except dhan_sandbox; 11 (weekend-gap-aware) is "no" for everyone today (resolved by Phase 4c) — omitted from the row.

**Legend:** ✅ implemented · ⚠️ partial · ❌ missing · n/a not applicable

| Broker | 1 reconnect loop | 2 resubscribe | 3 health check | 4 on_close clean | 5 lock discipline | 6 auth-fail | 7 interruptible sleep | 8 batch queue |
|---|---|---|---|---|---|---|---|---|
| **zerodha** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **angel** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ (health only) | ❌ |
| **dhan** | ✅ | ⚠️ caller-driven | ❌ | ✅ | ✅ | ✅ (fatal-error) | ❌ | ✅ |
| **dhan_sandbox** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ⚠️ async mixed | ❌ |
| **flattrade** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **fyers HSM** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ⚠️ health only | ✅ (150ms) |
| **fyers TBT** | ✅ | ⚠️ | ❌ | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| **firstock** | ✅ | ✅ | ✅ | ✅ | ✅ | **✅** | ✅ | ❌ |
| **shoonya** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **zebu** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **definedge** | ✅ | ⚠️ | ❌ (50s HB only) | ✅ | ✅ | ❌ | ❌ | ❌ |
| **deltaexchange** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **kotak** | ✅ adapter | ✅ adapter | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **motilal** | ✅ | ✅ | ⚠️ passive | ✅ | ✅ | ❌ | ✅ | ❌ |
| **paytm** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **pocketful** | ✅ | ✅ | ⚠️ HB only | ✅ | ✅ | ❌ | ❌ | ❌ |
| **rmoney** | ✅ | ✅ | n/a (Socket.IO) | ✅ | ✅ | **✅** partial (re-auth + 1 retry) | ✅ via SIO | ❌ |
| **fivepaisaxts** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **ibulls** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **iifl** | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **iiflcapital** | n/a (REST poll) | n/a | n/a | n/a | ✅ | n/a | ✅ | n/a |
| **nubra** | ✅ | ✅ implicit | ❌ | ✅ | ✅ | **✅** ("Invalid Token") | ✅ | ❌ |
| **upstox** | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| **aliceblue** | ✅ | ⚠️ | ❌ | ✅ | **❌** (lock during send) | ❌ | ❌ | ❌ |
| **fivepaisa** | **❌** (run_forever blocks) | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **groww** | **❌** (recursive on_close, no cap) | ✅ | ❌ | **❌** | ✅ | ❌ | ❌ | ❌ |
| **indmoney** | ✅ | ✅ | ❌ | ✅ | **❌** (unguarded flag) | ❌ | ❌ | ❌ |
| **mstock** | ✅ | **❌** (no callback hook) | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **samco** | ⚠️ (dual paths racing) | ✅ | ✅ | **❌** (race) | ⚠️ | ❌ | ❌ | ❌ |
| **tradejini** | ✅ | ⚠️ | ❌ | ✅ | **❌** (lock during subscribeL1/L2) | ❌ | ❌ | ❌ |
| **wisdom** | ❌ (no WS reconnect) | **❌** | ❌ | ✅ | **❌** (HTTP under lock) | ❌ | ❌ | ❌ |
| **compositedge** | ✅ | ⚠️ (iter race) | ❌ | ⚠️ | ⚠️ | ❌ | ❌ | ❌ |
| **jainamxts** | ✅ (racing with SIO) | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |

---

## 5. The Six Cross-Cutting Gaps

These affect every broker — the root causes of why so many cells in §4 are ❌. **These are the highest-leverage fixes**: each closes a gap across the entire fleet.

### 5.1 Gap A: Auth-failure detection (criterion 6)

**28 of 32 brokers don't detect auth-failure responses.** When the broker returns 401/403/"unauthorized"/"session expired" mid-stream, only **firstock** (full short-circuit), **dhan** (fatal-error pattern), **rmoney** (re-auth + 1 retry), and **nubra** (Invalid Token close) handle it cleanly.

Everyone else — including **zerodha** — treats auth failure as transient and retries up to 50 times with exponential backoff.

**At 3am IST daily:** every adapter attempts ~50 reconnects over ~30-50 minutes:
- 30+ broker IPs hammered with auth-failed requests
- Audit logs filled with retry noise (`errors.jsonl` auto-truncates to 1000 entries → genuine errors get evicted)
- Risk of **broker-side rate limit** on the user's registered IP. **Critical post April 2026** when SEBI's static-IP mandate takes effect — broker may temp-ban the registered IP.

**Over a weekend (Friday 3am to Monday 8am ≈ 53 hours):** the same retry storm only lasts ~50 minutes (loop hits max attempts and gives up). After that, adapter sits in a "dead" state for the remaining ~52 hours. But:
- 50 minutes × 30 brokers × auth-fail requests = **substantial unnecessary load** delivered to broker IPs from the registered server IP. Repeated weekend after weekend, this trains broker rate-limit systems against the user.
- Each adapter death also leaks the file descriptors and ZMQ socket of the dying connection unless explicit cleanup runs.

**Reference pattern (firstock):**
```
broker/firstock/streaming/firstock_websocket.py:455-485
```
Detects "unauthenticated" → sets `is_running=False` → exits supervisor loop. Less than 50 LOC.

**Update (2026-05-05):** The proxy already has shared auth helpers — `BaseBrokerWebSocketAdapter.is_auth_error()` (`websocket_proxy/base_adapter.py:523`) and `handle_auth_error_and_retry()` (`:554`). The `websocket_proxy/server.py` invokes them at lines 728, 759, 823, 1388. **Phase 4a's task is therefore not "build the helper" but "wire the existing helper into each broker's `_on_error` / `_on_close` / message-parse hot paths."** Smaller surface than originally framed.

### 5.2 Gap B: Subscription state across the 3am cycle (resolved by Phase 4c)

**Re-framed (this section was previously titled "Master-contract-aware resubscribe").** The earlier framing assumed adapter `subscribed_tokens` state would persist through 3am with stale broker tokens, requiring per-broker re-resolution. After review, the cleaner design is to **let Phase 4c's 3am orchestrator perform a clean teardown**:

```
3am IST (every day, holidays included)
  → 3am orchestrator runs (Phase 4c)
  → adapter.disconnect() called on every broker
  → subscribed_tokens / mode_map / token_to_symbol cleared
  → ZMQ sockets closed
  → adapters in fresh state (no stale tokens carried forward)

Monday 8am (or any post-3am login)
  → user logs in fresh
  → master contract re-downloaded (fresh F&O tokens for new expiries)
  → user / strategies call subscribe("BANKNIFTY28APR2548000CE", "NFO")
  → get_token() resolves via FRESH SymToken table
  → broker subscribes with current, valid token → ticks flow
```

**With Phase 4c in place, F&O contract rotation is handled transparently.** No per-broker change needed.

**The remaining requirement:** Phase 4b's `cache_loaded` listener must track **symbols** (`("BANKNIFTY28APR2548000CE", "NFO")`), not cached **tokens**, when restoring subscriptions on relogin. As long as it re-issues `subscribe(symbol, exchange)` and lets the normal flow re-resolve through the fresh master contract, F&O works automatically.

**No event listener exists for `cache_loaded` today.** The SocketIO event is emitted at `database/master_contract_cache_hook.py:45-46` when a fresh contract loads, but **no service consumes it for resubscribe coordination**. Confirmed via `services/` audit (§7). This is the actionable gap — Phase 4b builds it.

**What was wrong in the previous framing:** the "stale token in `subscribed_tokens`" concern only manifests if 3am orchestration is missing AND adapters are left dangling with old in-memory state. Once Phase 4c does clean teardown, that concern evaporates and per-broker `_resubscribe_all` doesn't need to be master-contract-aware — it simply doesn't run because `subscribed_tokens` is empty.

### 5.3 Gap C: 3am token-expiry orchestration (services layer)

**No `services/` file orchestrates the 3am cycle.**

- `utils/session.py:57-94`: Session validity is checked **reactively** when a user makes a request. No proactive scheduler.
- `database/auth_db.py:81`: `SESSION_EXPIRY_TIME = "03:00"` IST is a config constant. Used for cache TTL only.
- No APScheduler / cron / background thread proactively revokes tokens at 3am.
- No service emits a "session_expired" event to coordinate adapter teardown.
- WebSocket adapters keep retrying past 3am with stale auth (per Gap A).

**Net effect at 3am daily:** WebSocket dies silently. Until user manually re-logins, all live data is gone. Strategies depending on live data silently stall.

**Net effect over weekend:** Adapter dies Saturday 3am. Sits dead for ~52+ hours. Monday user logs in. Master contract refreshes. Adapter is still dead (no listener for `cache_loaded`). User must manually re-subscribe each symbol — or strategies that auto-restore via `restore_strategies_after_login` work, raw SDK clients don't.

### 5.4 Gap D: Subscribe batch-queue (criterion 8)

**5 of 32 brokers have a batch-queue** that coalesces rapid `subscribe()` calls into one broker message. The other **27 send one WebSocket message per `subscribe()` call.**

| Has batch-queue | Reference | Delay |
|---|---|---|
| zerodha | `broker/zerodha/streaming/zerodha_adapter.py:60-62` | 500ms |
| upstox | `broker/upstox/streaming/upstox_adapter.py:55-57` | 500ms |
| flattrade | `broker/flattrade/streaming/flattrade_adapter.py:335-337` | 500ms (recently added — commit `ed37dbc2`) |
| dhan | `broker/dhan/streaming/dhan_adapter.py:67-69` | 500ms |
| fyers HSM | `broker/fyers/streaming/fyers_websocket_adapter.py:51, 77-79` | 150ms |

**Missing batch-queue (highest user-impact first):**

| Broker | Impact at 1000 rapid subscribe() calls |
|---|---|
| **angel** | 1000 individual messages. Major broker. Likely rate-limited. |
| **kotak** | 1000 individual messages, one per symbol. Heavy option-chain users hit this. |
| **samco** | 1000 individual messages. Compounds the dual-retry-path race. |
| **shoonya** | 1000 individual messages. Largest retail NSE broker by user count. |
| firstock, definedge, deltaexchange, ibulls, iifl, jainamxts, motilal, mstock, paytm, pocketful, rmoney, tradejini, wisdom, zebu | Lower traffic but same pattern. |
| aliceblue, compositedge, fivepaisa, fivepaisaxts, groww, indmoney, nubra | No batch-queue AND has reliability bugs — fix both at once. |
| dhan_sandbox | Diverged from prod dhan; should inherit batch-queue |
| iiflcapital | n/a (REST polling) |

The batch-queue pattern is small surface (~50 LOC per broker, copy from zerodha) and a clean win.

### 5.5 Gap E: Interruptible sleeps in reconnect loops (criterion 7)

**Most brokers use `time.sleep(60)` instead of `_stop_event.wait(60)` in their reconnect-backoff loop.** Implications:

- **On dev (threading):** `time.sleep` blocks the OS thread. Shutdown waits up to 60s.
- **On prod (eventlet):** monkey-patched `time.sleep` is cooperative — yields the green thread. **But:** systemd graceful timeout (default 30s) will kill the worker if it doesn't respond, dropping all WebSocket connections and triggering a fleet-wide reconnect storm. Not a hang per se, but ungraceful restart.

**Implementing correctly** (firstock):
```
broker/firstock/streaming/firstock_websocket.py:235
    self._shutdown_event.wait(self.retry_delay)  # interruptible
```

Brokers using `_stop_event.wait()` correctly: firstock, motilal, nubra, iiflcapital, fyers HSM (health loop only), angel (health loop only). **Even zerodha doesn't** — known issue.

### 5.6 Gap F: Weekend / holiday gap recovery (criterion 12)

**0 of 32 brokers** are designed for the multi-day gap scenario. Combination of Gaps A + B + C produces the failure mode:

**Friday 11:55pm (commodity close) → Saturday 3:00 AM IST → Monday 8:00 AM (user relogin) ≈ 53 hours**

Timeline:
- **Sat 03:00 IST:** Tokens expire. WebSocket adapters get auth-failed responses on next ping/data.
- **Sat 03:00 → 03:50:** Retry storm. 50 attempts × backoff. ~50 min of useless requests. Risk to registered IP.
- **Sat 03:50 → Mon 08:00:** Adapter is in "running=False" state. Daemon thread has exited. Subscriptions dict still in memory. ZMQ socket likely still open (cleanup_zmq runs only on explicit `disconnect()`).
- **Mon 08:00:** User logs in. `auth_utils.py` triggers `async_master_contract_download(broker)` (line 425-437). Master contract refreshes. `socketio.emit("cache_loaded")` fires.
- **Mon 08:00 onwards:** No service listens for `cache_loaded` to restart WebSocket adapters. User's WebSocket clients see "no ticks" until they manually re-subscribe.

Cumulative weekly cost across 30 brokers × every weekend × every Indian holiday: significant.

---

## 6. Cross-Platform Compatibility (per CLAUDE.md)

OpenAlgo runs on Windows, macOS, Docker, and Ubuntu+gunicorn+eventlet. Code that works in dev may break in production due to eventlet's stdlib monkey-patching.

### 6.1 dhan_sandbox — eventlet compatibility risk

**The only broker using `asyncio` + `websockets`-async** (per grep across `broker/*/streaming/`).

`broker/dhan_sandbox/streaming/dhan_websocket.py`:
- Line 6: `import asyncio`
- Lines 143-159: creates `asyncio.new_event_loop()` and `asyncio.set_event_loop(self.loop)` inside a `threading.Thread`
- Line 17: `import websockets` (the async websockets-async library)
- Lines 174-457: extensive `async def` / `await` / `asyncio.sleep` / `asyncio.create_task`

Per CLAUDE.md: "**eventlet monkey-patches the stdlib and is incompatible with `asyncio.run()`, `async/await`, and `asyncio.get_event_loop()`. Any code that needs async behavior must use eventlet green threads or run async work on a separate real OS thread.**"

**The risk:** dhan_sandbox spawns its asyncio loop inside a `threading.Thread`. Under production eventlet+gunicorn:
- `threading.Thread` is monkey-patched → may become a green thread instead of a real OS thread.
- asyncio inside a green thread is undefined behavior — may hang, may produce silent errors, may work intermittently.

**The reference workaround** (per CLAUDE.md): `services/telegram_bot_service.py:_render_plotly_png` runs Plotly's async chart rendering on a separate **real** OS thread, explicitly avoiding eventlet's monkey-patched threading. Use as model.

**Why this is CRITICAL:** the bug only manifests on production gunicorn+eventlet. Developer testing on Mac/Windows (Flask dev server, standard threading) sees it work fine. The bug only surfaces when a real customer deploys via `install.sh` and starts dhan_sandbox streaming. Hard to reproduce, hard to debug, easy to ship.

### 6.2 SQLite locking differences (Windows vs Linux)

Per CLAUDE.md: "SQLite concurrency behavior differs (Windows is more restrictive with file locking)." Affects the database-layer subscription/state writes during reconnect storms. Out of scope for this audit (subscriptions aren't persisted to DB anyway — see Gap B context).

### 6.3 `time.sleep` semantics

| Environment | `time.sleep(60)` behavior |
|---|---|
| Dev (Windows / macOS / Linux Flask dev) | Blocks the OS thread. Affects only that thread. Other adapters continue. |
| Prod (gunicorn+eventlet) | Cooperative yield. Doesn't block other green threads in the same worker. **But:** systemd `graceful_timeout` (default 30s) will SIGKILL the worker if it can't respond in time. 60s sleep > 30s graceful → ungraceful restart. |

**Implication:** Gap E (interruptible sleeps) matters more on production than dev. Fixing it is a cross-platform improvement.

### 6.4 `threading.local()` semantics

Per CLAUDE.md: "`threading.local()` maps to green threads under eventlet." This is why scoped sessions and `request_local` work correctly under both.

Most broker WebSocket code uses `threading.Lock()`, not `threading.local()`. No specific concern flagged.

---

## 7. Service Layer (`services/`) Findings

### 7.1 CRITICAL — No `cache_loaded` listener for resubscribe

Master contract finishes loading → `socketio.emit("cache_loaded", ...)` at `database/master_contract_cache_hook.py:45-46`. **No service in `services/` listens for this event.**

Consequence (combined with Gaps B + F): after relogin and fresh master contract download (daily at 3am, every Monday morning, after every holiday), **subscriptions are not automatically restored**. Manual re-subscribe required.

The only downstream consumer is `restore_strategies_after_login()` (`master_contract_cache_hook.py:98-106`), which restores **strategy state**, not raw WebSocket subscriptions. Strategies internally re-subscribe via their own logic, so stateful strategies recover; raw SDK clients (e.g., a TradingView webhook integration, a standalone scanner) don't.

### 7.2 CRITICAL — No `services/` file orchestrates the 3am or weekend cycle

No scheduled task in `services/` (or anywhere else) that:
- Detects 3am IST passage.
- Cleanly closes broker WebSockets (instead of letting them hammer expired tokens for 30-50 min).
- Marks adapters as "session-expired".
- Coordinates re-login → contract reload → reconnect → resubscribe when the user returns Monday morning.

### 7.3 HIGH — Silent SocketIO emit failures

`services/telegram_bot_service.py:2435-2439`:
```python
try:
    from extensions import socketio
    socketio.emit("app_mode_changed", {"analyze_mode": new_mode})
except Exception:
    pass  # No log, no recovery
```
Mode-change notification can fail silently. Hides upstream WebSocket-related issues.

### 7.4 MEDIUM — Flow executor depends on live WS without health check

`services/flow_executor_service.py:1480-1585` — `_get_websocket_data()` subscribes, waits 5s, falls back to REST. Concerns:
- No pre-flight check that broker WebSocket is alive.
- 5-second timeout may be too short for Depth (full mode) subscriptions.
- If WebSocket is dead at 3am or post-weekend, every flow execution burns 5s before falling back.

### 7.5 MEDIUM — Reconnect counter never reset

`services/market_data_service.py:240` — `ConnectionHealthMonitor.reconnect_count` (line 196) never reset. Over a 12-hour session with ~10 transient drops, distorts dashboards.

### 7.6 LOW — Service-layer locks are well-designed

No deadlock found. Locks released before invoking callbacks (`market_data_service.py:212-225`). Snapshot pattern followed.

---

## 8. Detailed HIGH Priority Broker Findings

### 8.1 aliceblue — `broker/aliceblue/streaming/aliceblue_client.py`

**Defect 1 — Blocking I/O held under lock.** `_resubscribe_after_auth:867-890` iterates `self.subscriptions` inside `with self.lock` and calls `ws_client.send()` at line 887.

**Defect 2 — `connected` flag race.** `_handle_message:702` writes without lock; `subscribe():412` reads without lock.

**Defect 3 — No batch-queue.**

**Fix:** Snapshot subscriptions under lock, release, then send. Guard `connected` consistently. Add zerodha-style batch-queue.

### 8.2 fivepaisa — `broker/fivepaisa/streaming/fivepaisa_websocket.py`

**Revised 2026-05-05.** Earlier framing of "run_forever blocks adapter retry loop" was overstated — `fivepaisa_adapter.py:100` correctly wires `ws_client.on_open = self._on_open` and `:285` defines `_on_open` which performs on-open resubscribe. `run_forever()` blocks only the SDK's own worker thread, not the adapter. The actual concerns:

**Defect 1 — Duplicate reconnect chains.** Adapter retry loop and SDK both manage reconnection independently; no single source of truth.

**Defect 2 — No subscribe batch-queue.** 1000 rapid subscribe calls = 1000 messages.

**Defect 3 — No auth-failure short-circuit.** Reconnect blindly retries on auth-failed responses.

**Fix:** Pick one canonical reconnect owner. Add zerodha-style batch-queue. Wire shared `is_auth_error()` helper from `base_adapter.py`.

### 8.3 groww — `broker/groww/streaming/nats_websocket.py`

**Defect 1 — Recursive `_on_close`.** Lines 478-493: `time.sleep(5)` + recursive `_run_websocket()` from dispatch thread. Can deadlock dispatch.

**Defect 2 — No reconnect-attempt cap.** Retries forever. **Especially bad over a weekend** — 50+ hours of infinite retries.

**Defect 3 — NATS auth is per-connection.** Socket token + nkey must regenerate each reconnect.

**Fix:** Replace with `while running:` loop. Move token regeneration inside loop body. `_on_close` flips state only. Add 50-attempt cap with exponential backoff.

### 8.4 indmoney — `broker/indmoney/streaming/indmoney_adapter.py` + `indWebSocket.py`

**Defect 1 — Unguarded `connected` flag.** Writes 276, 335; reads 186 — without lock.

**Defect 2 — `RESUBSCRIBE_FLAG` (module-level)** at `indWebSocket.py:193` mutated without sync.

**Defect 3 — Duplicate reconnect threads.** `_on_close:339` spawns without guard.

**Fix:** Wrap flag accesses with `self.lock`. Add `_reconnect_thread_active` guard.

### 8.5 mstock — `broker/mstock/streaming/mstock_adapter.py` + `broker/mstock/api/mstockwebsocket.py`

**Revised 2026-05-05.** Earlier framing of "vendor SDK has no callback hook for resubscribe" was **invalid**. Verification:
- `mstockwebsocket.py:189-193` spawns `_run_websocket` with reconnect loop
- `mstockwebsocket.py:253-260` marks logged-in after broker login response, then calls `self._resubscribe_all()`
- `mstockwebsocket.py:273` defines `_resubscribe_all` walking the SDK's own subscriptions dict

**The SDK self-resubscribes after login confirmation.** Demoted from HIGH to MEDIUM.

The actual remaining concern:

**Defect — Parallel state drift between adapter and SDK.** Adapter tracks `self.subscriptions:163`, `self.token_modes:182`, `self.token_correlation_ids:205` in parallel to the SDK's own internal state. If subscribe/unsubscribe paths drift, the SDK resubscribes from its dict and the adapter's dict gets stale.

**Fix:** Either (a) consolidate state — drop adapter's parallel tracking and route lookups through SDK; or (b) verify subscribe/unsubscribe always update both atomically. Lower-priority than originally framed. Most important: wire shared `is_auth_error()` helper for platform-level auth-fail handling.

### 8.6 samco — `broker/samco/streaming/samco_adapter.py` + `samcoWebSocket.py`

**Revised 2026-05-05.** Earlier framing of "two reconnect paths racing" was overstated. Verification:
- `samcoWebSocket.py:478` explicitly states: `"""Handle WebSocket connection errors — reconnection is handled by the adapter"""`
- The SDK's `max_retry_attempts = 5` field at line 107 is unused in the actual reconnect path
- The adapter owns reconnection via `_connect_with_retry`

**No actual race condition.** Demoted from CRITICAL 3-axis to HIGH 2-axis.

The actual remaining concerns:

**Defect 1 — No subscribe batch-queue.** Major broker (large retail derivatives user base); strategy startups subscribing to 100+ option strikes hit broker rate limits with 1000 individual messages. Performance HIGH.

**Defect 2 — No auth-failure short-circuit.** Wire shared `is_auth_error()` helper from `base_adapter.py` into adapter's error/close paths.

**Fix:** Add zerodha-style batch-queue (`zerodha_adapter.py:60-194`). Wire auth-fail helper. Adapter's existing reconnect guard is fine — leave it alone.

### 8.7 tradejini — `broker/tradejini/streaming/tradejini_adapter.py` + `nxtradstream.py`

**Defect — Lock held during external `subscribeL1/L2` calls.** `_on_connection_event:312-332` holds `self.lock` while iterating subscriptions and making blocking broker calls (lines 322, 324).

**Fix:** Snapshot under lock, release, then iterate.

### 8.8 wisdom — `broker/wisdom/streaming/wisdom_adapter.py` + `wisdom_websocket.py`

**Defect 1 — HTTP POST held under lock.** `_resubscribe_all:526-536` iterates while holding lock and calls `ws_client.subscribe()` (HTTP-backed).

**Defect 2 — No WS-layer reconnect.** Drops silently absorbed.

**Defect 3 — `_on_close:542-549` spawns thread without lock.**

**Fix:** Snapshot pattern. Add WS-layer reconnect (Socket.IO with `reconnection=True` + backoff, mirror rmoney).

### 8.9 dhan_sandbox — `broker/dhan_sandbox/streaming/dhan_websocket.py` (NEW — eventlet risk)

**Defect — Uses asyncio + websockets-async inside a `threading.Thread`.** Under production gunicorn+eventlet, the thread may be a green thread (eventlet monkey-patches threading). asyncio inside a green thread is undefined.

**Fix:** Either (a) switch to sync `websocket-client` like its prod sibling `dhan/`; or (b) ensure the asyncio loop runs on a real OS thread (use `_thread.start_new_thread()` or eventlet-aware native-threading helpers — model after `services/telegram_bot_service.py:_render_plotly_png` per CLAUDE.md).

---

## 9. MEDIUM Priority Broker Findings

### 9.1 compositedge

`_resubscribe_all:530-538` iterates over a stale snapshot (lock released at 539). Race with concurrent unsubscribe. `_on_close:544-551` spawns reconnect without re-checking `_reconnect_thread_active`. No data-stall watchdog.

**Fix:** Snapshot pattern + re-check inside lock.

### 9.2 jainamxts

Socket.IO auto-reconnect not explicitly disabled; adapter also reconnects → racing reconnect threads.

**Fix:** Add `reconnection=False` (mirror rmoney).

### 9.3 upstox

Data-stall reconnect chain works but indirect. `DATA_TIMEOUT=90s` hardcoded.

**Fix:** Lightweight hardening — log distinction; env-configurable timeout.

---

## 10. LOW Priority Brokers — Notes

| Broker | Notes |
|---|---|
| **angel** | Tier 2. **Performance HIGH — needs batch-queue.** |
| **definedge** | Tier 4. 50s app HB unusually long; dual reconnect. |
| **deltaexchange** | Single-layer reconnect, `_active_sub_msgs` replayed every reconnect. **Crypto: 24/7 market, no 3am gap — token expiry concerns differ.** |
| **dhan** | Has batch-queue + auth-fail short-circuit. **Caveat:** subscriptions stored but caller must re-call subscribe — design choice. |
| **firstock** | **Cleanest in fleet on auth-fail and interruptible sleeps.** Reference for both. Only gap is no batch-queue. |
| **fivepaisaxts** | Phase 1 disputed — has full reconnect + Socket.IO built-in + `_resubscribe_all`. |
| **flattrade** | **Tier 1 — strongest keepalive coverage.** Recently got batch-queue. Reference-quality. |
| **fyers (HSM)** | Tier 2. Has 150ms batch-queue. Strong. |
| **fyers (TBT)** | Pong not validated; linear backoff. Worth tightening. |
| **ibulls / iifl / jainamxts** | XTS family. No health-check thread. jainamxts has racing-reconnect bug. |
| **iiflcapital** | **Not WebSocket** — REST polling. Out of scope for keepalive standardization. |
| **kotak** | HSWebSocketLib wrapper. **Performance HIGH — needs batch-queue.** |
| **motilal** | `_start_heartbeat()` no-op. Passive on-demand health check. Worth cleaning. |
| **nubra** | Phase 1 disputed — implicit resubscribe. Detects "Invalid Token". |
| **paytm** | Functional. Dual reconnect. |
| **pocketful** | Phase 1 disputed — has full `_connect_with_retry`. |
| **rmoney** | Only Socket.IO broker doing reconnect right (`reconnection=False`). **Has partial auth-fail re-auth.** Reference for jainamxts/wisdom fixes. |
| **shoonya** | Tier 1. Dual heartbeat. **Performance HIGH — needs batch-queue.** |
| **zebu** | Phase 1 disputed — full `_schedule_reconnection`. Tier 1. |
| **zerodha** | **Reference implementation** for reconnect/resubscribe. One known gap: no auth-fail short-circuit. |

---

## 11. Phased Remediation Roadmap

Sequenced for atomic rollouts and minimal risk.

### Phase 1 — Standardization framework (Days 1-2)
- Codify the 11 invariants in `docs/broker-integration-guide.md`.
- Add PR-template checklist.
- No code changes.

### Phase 2 — Reliability HIGH fixes (Days 3-12)

**Phase 2a — Mechanical (parallel, ~3 days):** fivepaisa, groww, samco, mstock.
**Phase 2b — Lock discipline (serial, ~5 days):** aliceblue, tradejini, wisdom, indmoney.

### Phase 3 — Performance HIGH (parallel, ~3 days)
Add batch-queue to **angel, kotak, samco, shoonya**. Copy zerodha's pattern.

### Phase 4 — Cross-cutting Gaps A/B/C/F (Days 13-22)

**Phase 4a — Auth-failure detection (cross-broker, ~5 days):**
- Add a shared `is_auth_failure(msg)` helper to `websocket_proxy/base_adapter.py` matching common patterns: 401/403, "unauthorized", "session expired", "invalid token", "e-session-0007", "unauthenticated".
- Wire into each broker's error handler. On match: `running=False`, emit `services`-layer event, **stop retrying**.
- References: firstock, dhan, rmoney, nubra.
- **Critical post-April-2026:** prevents broker-side IP rate-limiting under SEBI static-IP mandate.

**Phase 4b — `cache_loaded` → resubscribe orchestration (~3 days):**
- Add `services/websocket_resync_service.py` that listens for `cache_loaded` SocketIO events.
- **Tracks subscriptions by symbol, NOT by cached broker token.** Storage shape: `set[(symbol, exchange, mode)]`.
- On event: walk stored symbol set, re-issue `subscribe(symbol, exchange, mode)` through the proxy. Each subscribe goes through normal `get_token()` resolution against the fresh master contract → F&O token rotation handled automatically.
- Coordinate with `restore_strategies_after_login` so resubscribes don't double-fire.
- **Closes the weekend-gap recovery problem** (Gap F) AND auto-resolves Gap B (former master-contract concern): Monday morning fresh login → master contract reload → `cache_loaded` fires → listener re-issues subscribes by symbol → fresh tokens resolved → ticks flow.

**Phase 4c — 3am token-expiry orchestrator with clean teardown (~3 days):**
- Add APScheduler task in `services/` that fires at 3:00 AM IST every day (including holidays — server runs 24×7×365).
- For each broker adapter: call `disconnect()` which **clears** `subscribed_tokens`, `mode_map`, `token_to_symbol`, and closes ZMQ sockets. **State must be torn down, not preserved.**
- Emits `session_expiry` event.
- Pairs with Phase 4a (auth-fail prevents the pre-3am retry storm) and Phase 4b (post-relogin restoration via symbols, not tokens).
- **This clean teardown is the design that eliminates the master-contract-stale-token problem entirely.** No per-broker resubscribe-from-stale-state path is ever exercised, because state is gone.

### Phase 5 — Cross-platform fix (Days 23-25)

**Phase 5 — dhan_sandbox eventlet compatibility:**
- Either rewrite as sync (mirror prod `dhan/`), or ensure asyncio loop runs on a real OS thread (per CLAUDE.md `telegram_bot_service.py` pattern).
- Verify on production gunicorn+eventlet (not just dev).

### Phase 6 — Reliability MEDIUM + LOW gaps (Days 26-30)

- compositedge snapshot-pattern + thread-spawn re-check.
- jainamxts `reconnection=False`.
- upstox stall-trigger logging + env-configurable `DATA_TIMEOUT`.
- Add batch-queue to remaining 23 brokers (Phase 3 only covered the 4 highest-impact).

### Phase 7 — Env-var rollup per #1101 (Days 31-35)

- `WS_PING_INTERVAL` / `WS_HEALTH_CHECK_INTERVAL` / `WS_DATA_TIMEOUT` / `WS_HEARTBEAT_TIMEOUT` reads in `websocket_proxy/base_adapter.py`.
- Per-broker rollup PRs by tier.
- Document defaults in `docs/userguide/`.

### Phase 8 — Long-running hardening (Days 36-40)

- Replace `time.sleep()` with `_stop_event.wait()` in all reconnect loops (Gap E).
- Bound subscription dicts by broker symbol cap.
- Add data-stall detection to the 18 brokers without it.
- Address dual-reconnect-storm risk in angel/definedge/motilal/paytm/dhan_sandbox.

---

## 12. Verification Gates

### 12.1 Per-PR verification

1. `uv run python -m py_compile` on edited files.
2. Import check: `uv run python -c "from broker.<name>.streaming import <Adapter>; print('ok')"`.
3. Unit-test gate where unit tests exist.

### 12.2 Reconnect-drill (per broker, per phase)

1. **Normal drop** — firewall broker WS port for 30s, restore. Verify reconnect within 2 min, all 1000 symbols deliver ticks again without client resubscribe.
2. **Sustained outage** — firewall for 5 min. Verify max-attempts cap and graceful give-up.
3. **Auth-failure simulation** — pass invalid token. Verify reconnect loop stops within 1-3 attempts (not 50). [Phase 4a gate]
4. **3am simulation** — invalidate token in DB. Verify adapter detects, stops retrying, emits `session_expiry`. Re-login. Verify master contract reload + automatic resubscribe via `cache_loaded` listener. [Phase 4a/b/c gate]

### 12.3 Weekend-gap drill (NEW — Phase 4b/c gate)

Specifically tests Gap F:
1. Friday EOD: have 500+ active subscriptions running.
2. Manually invalidate broker token in DB at 3am Saturday simulation.
3. Verify each broker adapter detects auth-fail within ~30s (Phase 4a).
4. Verify each adapter stops its reconnect loop within 2-5 minutes (instead of 50 min hammering).
5. Verify ZMQ socket and FDs released.
6. Leave server idle 48 simulated hours.
7. Re-login Monday simulation. Master contract reloads.
8. Verify `cache_loaded` listener (Phase 4b) re-resolves symbols and restores all 500 subscriptions automatically — no manual user action.
9. Verify ticks flow within 30 seconds of relogin.

### 12.4 Scale-load verification

Subscribe 1000 symbols rapidly via test client. Measure:
- Time to all 1000 delivering ticks (target: <15s with batch-queue, ~5-10s with both batch-queue + bulk subscribe).
- Number of broker WS messages during subscribe phase (target: <20 with batch-queue + 200/batch — vs 1000 without).

### 12.5 Long-running verification

Run a 12-hour session with 500+ symbols. Measure:
- Memory growth (target: bounded, <10% growth).
- Thread count (target: stable).
- `ConnectionHealthMonitor.reconnect_count` (target: matches expected drops).
- `errors.jsonl` lines (target: only genuine errors).

### 12.6 Cross-platform verification (NEW — Phase 5 gate)

Run an identical test on both:
- Dev machine (Mac/Windows): `uv run app.py`
- Production-equivalent: Docker with `gunicorn --worker-class eventlet -w 1`

Verify dhan_sandbox specifically:
- Subscribe 100 symbols on each.
- Run 1 hour.
- Compare tick delivery counts (should match within 5%).
- Check for asyncio errors in `errors.jsonl` (should be zero on production).

### 12.7 Multi-broker concurrent verification

Verify that a fix to one broker doesn't disrupt others. Run all enabled brokers concurrently for 30 minutes; check that none of the others' ConnectionHealthMonitor.reconnect_count increases beyond baseline.

---

## 13. Out of Scope

- **Per-broker keepalive tuning rationale** — defer to [keepalive-audit](./websocket-keepalive-audit.md).
- **WebSocket proxy server (port 8765) client-facing protocol.**
- **Data correctness** (tick parsing, symbol mapping) — separate concern.
- **Token refresh on broker side** — out of OpenAlgo's control.

---

## 14. Cross-References

- Issue [#1101 — Standard WebSocket Ping/Heartbeat](https://github.com/marketcalls/openalgo/issues/1101)
- [`docs/audit/websocket-keepalive-audit.md`](./websocket-keepalive-audit.md)
- [`docs/websocket-architecture.md`](../websocket-architecture.md)
- [`install/install.sh`](../../install/install.sh) — production deployment via gunicorn+eventlet+systemd
- Gold-standard reconnect: [`broker/zerodha/streaming/zerodha_websocket.py`](../../broker/zerodha/streaming/zerodha_websocket.py)
- Auth-fail reference: [`broker/firstock/streaming/firstock_websocket.py:455-485`](../../broker/firstock/streaming/firstock_websocket.py)
- Batch-queue reference: [`broker/zerodha/streaming/zerodha_adapter.py:60-194`](../../broker/zerodha/streaming/zerodha_adapter.py)
- Recently-merged batch-queue: commit `ed37dbc2` (flattrade)
- Eventlet+asyncio reference pattern: `services/telegram_bot_service.py:_render_plotly_png` (per CLAUDE.md)
- Crypto 24/7 exception: `broker/deltaexchange/streaming/`

---

## Appendix A — Phase 1 verification notes (2026-05-04, AM)

A prior excerpt-based audit flagged 14 brokers as broken. Phase 1 verification (full-file reads) disputed 4:

| Broker | Original verdict | Phase 1 verdict | What original missed |
|---|---|---|---|
| **fivepaisaxts** | NOT OK — no reconnect | DISPUTED | Has reconnect on `_on_close:549` + Socket.IO + `_resubscribe_all:524`. |
| **pocketful** | NOT OK — `_on_close` doesn't reconnect | DISPUTED | Has `_connect_with_retry:95-139`. |
| **zebu** | NOT OK — no adapter reconnect | DISPUTED | `_schedule_reconnection → _attempt_reconnection:756-820`. |
| **nubra** | NOT OK — no resubscribe wired | DISPUTED | Implicit resubscribe via vendor SDK + persistent maps. |

**Lesson:** read whole files for any "NOT OK" verdict before action.

## Appendix B — Phase 2 deep audit notes (workload-aware, 2026-05-04, PM)

5 cross-cutting Gaps A/B/C/D/E identified; per-broker matrix produced. Findings:
- 4/32 brokers detect auth-fail (Gap A)
- Master-contract stale-token concern (former Gap B framing) — **resolved at design level by Phase 4c clean teardown + Phase 4b symbol-based listener.** No per-broker change required.
- No service handles 3am cycle (Gap C)
- 5/32 brokers have batch-queue (Gap D)
- 6/32 brokers use interruptible sleeps (Gap E)

## Appendix C — Phase 3 lifecycle audit notes (24×7×365 + cross-platform, 2026-05-04 evening)

This update added:
- §1.1 Real deployment profile (24×7, weekend gaps, holidays, crypto exception).
- §1.2 Cross-platform deployment paths (Win/Mac dev → Docker/Ubuntu+gunicorn+eventlet prod).
- §2 Invariant 10 (eventlet-safe) and 11 (weekend-gap-aware via Phase 4c clean teardown). Previous Invariant 9 (master-contract-aware resubscribe) was removed — auto-handled by clean teardown design.
- §3.3 Lifecycle priority axis.
- §5.6 Gap F (weekend-gap recovery).
- §6 Cross-platform compatibility (with **dhan_sandbox eventlet risk** elevated to CRITICAL).
- §11 Phase 5 (cross-platform fix) and Phase 4c (3am orchestrator) added to roadmap.
- §12.3 Weekend-gap drill and §12.6 Cross-platform drill added.

**The single highest-leverage fix in this audit** is Phase 4 (Gaps A/B/C/F together) — implementing auth-failure detection across the fleet + a `cache_loaded` listener + a 3am orchestrator. This converts the 30+ broker fleet from "silently breaking every night and over every weekend" to "transparently recovering on relogin," with zero per-broker work needed beyond auth-fail wiring.

The single highest **risk** in this audit is **dhan_sandbox** — the eventlet incompatibility is invisible during dev testing on Mac/Windows but may break for every customer running production gunicorn+eventlet via `install.sh`.

---

**Total brokers needing reliability work:** 8 (Phase 2 HIGH).
**Total brokers needing batch-queue:** 27 (Phases 3 + 6).
**Cross-cutting platform-level work:** 4 sub-phases (4a auth-fail, 4b cache-loaded listener, 4c 3am scheduler, 5 dhan_sandbox eventlet).
**Remaining keepalive standardization:** Phase 7 (env-var rollup per #1101).

---

## Appendix D — Cross-validation pass (2026-05-05)

A peer-review pass against `docs/audit/websocket-broker-priority-updated.md` produced this delta. **Five new platform-level findings confirmed by direct code inspection**, plus three broker findings revised after re-verification.

### D.1 (P0) — PUB→PUB cache_invalidation topology

**Files:** `database/cache_invalidation.py:58, 64`; `websocket_proxy/connection_manager.py:83, 110, 123`; `websocket_proxy/server.py:91, 95`.

**What:** `cache_invalidation.py` creates a `zmq.PUB` socket and **connects** to `tcp://{ZMQ_HOST}:{ZMQ_PORT}` — which is the same address that `connection_manager.py` **binds** with another `zmq.PUB`. Two PUB sockets on the same address don't form a connection in ZMQ. Cache-invalidation messages from the database/auth layer never reach the proxy SUB.

**Why fix:** Multi-process deployments (proxy in its own process) silently lose cache-invalidation events. Auth/session changes don't propagate. Stale auth state in the proxy after broker re-login.

**Normalization:** Use a dedicated control-channel topology — proxy binds a `PULL` or separate `SUB` socket, `cache_invalidation.py` connects to it as `PUSH` or `PUB`. Don't reuse the market-data PUB/SUB bus for lifecycle control.

**Advantages:** Cache invalidation actually reaches the proxy. Multi-process correctness. Test-able with a one-liner subscribe-and-assert.

### D.2 (P0) — Mode case mismatch in proxy

**Files:** `websocket_proxy/server.py:80, 991`.

**What:** Server has TWO different mode mappings in the same file:
- Line 80: `self.MODE_MAP = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}` (uppercase)
- Line 991: `mode_mapping = {"LTP": 1, "Quote": 2, "Depth": 3}` (capitalized)

`docs/websocket-quote-feed.md` documents `"QUOTE"` and `"DEPTH"` (uppercase). Depending on which code path handles the request, documented requests may fail.

**Why fix:** Real client-facing bug. SDK clients sending the documented `"QUOTE"` mode may be silently rejected on the line-991 path (which expects `"Quote"`).

**Normalization:** Single normalizer accepting numeric `1/2/3`, `"LTP"`/`"Quote"`/`"QUOTE"`/`"Depth"`/`"DEPTH"` (case-insensitive). Returns canonical numeric mode + canonical string label. Used everywhere mode is parsed.

**Advantages:** Documentation matches code. SDK clients work as documented. Tests can be exhaustive without ambiguity.

### D.3 (P1) — Service reports subscribe success before broker ack

**Files:** `services/websocket_client.py:152-174`.

**What:** `subscribe_to_symbols` calls `asyncio.run_coroutine_threadsafe(self.ws.send(...), self.loop)` and `future.result(timeout=5)` — but only awaits the **WebSocket send completion**, not the proxy's subscribe response or the broker's ack. Then immediately marks `active_subscriptions[key].add(mode)` and returns success.

**Why fix:** `services/flow_executor_service.py` and other consumers can believe a symbol is subscribed when the proxy or broker actually rejected it. Silent partial-failure mode.

**Normalization:** Add `request_id` to subscribe/unsubscribe messages. Wait for matching response from proxy. Update `active_subscriptions` only on confirmed success. Track per-symbol partial failures.

**Advantages:** Service callers see truthful state. Partial failures surface to UI/strategies. Unit-testable.

### D.4 (P1) — 12-broker hardcoded WebSocket support list

**Files:** `services/websocket_service.py:348-362`.

**What:** Hardcoded list of 12 brokers as "WebSocket-enabled":
```
zerodha, angel, fivepaisaxts, aliceblue, dhan, flattrade, shoonya,
upstox, compositedge, iifl, ibulls, wisdom
```
Repository has **32 streaming adapters**. The 20 brokers silently excluded: definedge, deltaexchange, dhan_sandbox, firstock, fivepaisa, fyers, groww, iiflcapital, indmoney, jainamxts, kotak, motilal, mstock, nubra, paytm, pocketful, rmoney, samco, tradejini, zebu.

**Why fix:** API responses claim these 20 brokers don't have WebSocket. Tests skip them. Docs misrepresent fleet capability.

**Normalization:** Derive supported list from filesystem (`broker/*/streaming/*_adapter.py`) or maintain a single capability registry shared by API, docs, tests, and `services/websocket_service.py`.

**Advantages:** No drift between code and config. New brokers auto-recognized. Single source of truth for capability claims.

### D.5 (P1) — ZMQ shared publisher binds to all interfaces

**Files:** `websocket_proxy/connection_manager.py:110, 123`.

**What:** `SharedZmqPublisher` binds `tcp://*:{port}` (all interfaces) regardless of `ZMQ_HOST` env var (default `127.0.0.1`).

**Why fix:** Security — exposes market-data publisher to any interface on the host. On a multi-tenant or cloud-deployed server, neighboring tenants/services can subscribe to the user's market data without credentials.

**Normalization:** Bind to `ZMQ_HOST` (default `127.0.0.1`) explicitly. Add `ZMQ_BIND_ALL=true` opt-in for multi-host deployments.

**Advantages:** Loopback-only by default. Explicit opt-in for wider exposure. Aligns with single-user deployment model in CLAUDE.md.

### D.6 — Proxy auth helpers already exist (correction to §5.1)

**Files:** `websocket_proxy/base_adapter.py:523, 554`; `websocket_proxy/server.py:728, 759, 823, 1388`.

**What:** Earlier framing of Phase 4a as "build a shared `is_auth_failure(msg)` helper" was overstated. The helpers already exist:
- `BaseBrokerWebSocketAdapter.is_auth_error(error_message)` (line 523)
- `BaseBrokerWebSocketAdapter.handle_auth_error_and_retry(...)` (line 554)
- `WebSocketServer._is_auth_error_exception(error_message)` (line 1388)

The server uses them at lines 728, 759, 823. **What's missing is per-broker wiring** — most adapters don't call `self.is_auth_error()` from their own `_on_error` / `_on_close` / message-parser hot paths.

**Phase 4a is therefore smaller:** wire the existing helper into 28 adapters, not "build the helper from scratch."

### D.7 — Broker findings revised after re-verification

| Broker | Original framing (REVISED) | Verification |
|---|---|---|
| **fivepaisa** | "run_forever() blocks adapter retry loop" | OVERSTATED. `fivepaisa_adapter.py:100, 285` correctly wires `_on_open` resubscribe. `run_forever()` blocks only the SDK's worker thread. Real issues: duplicate reconnect chains + no batch-queue + no auth-fail. |
| **samco** | "Two reconnect paths racing" | OVERSTATED. `samcoWebSocket.py:478` explicitly delegates reconnect to adapter; `max_retry_attempts=5` is unused. No actual race. Real issues: no batch-queue + no auth-fail. |
| **mstock** | "Vendor SDK has no callback hook for resubscribe" | INVALID. SDK self-resubscribes after login confirmation (`mstockwebsocket.py:253-273`). Real concern: parallel-state drift between adapter and SDK. Demoted from HIGH to MEDIUM. |

### D.8 — Updated count summary

After cross-validation:

- **Per-broker custom investigations:** 11 (was 12 — mstock demoted to MEDIUM, kept in count for parallel state drift; same broker count).
- **Per-broker batch-queue rollout:** 27 (unchanged).
- **Platform-wide rollouts:** 4 sweeps (auth-fail wiring is now smaller scope per D.6).
- **`websocket_proxy/` issues:** **9** (was 4; +5 new from D.1-D.5).
- **`services/` issues:** 5 (unchanged in count, but D.3 + D.4 now formally tracked).

**The 5 new platform issues (D.1-D.5) are likely higher leverage than 20+ of the per-broker batch-queue rollouts.** Sequence Phase 4 to land them first.
