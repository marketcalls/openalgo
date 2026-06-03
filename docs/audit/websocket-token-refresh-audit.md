# WebSocket Token-Refresh-on-Reconnect Audit (all brokers)

**Date:** 2026-06-03
**Updated:** 2026-06-03 after working-tree broker fixes
**Scope:** every `broker/*/streaming/` adapter (32 brokers)
**Question:** When the broker WebSocket reconnects, does the adapter **re-read a fresh auth token from the database** (or otherwise re-authenticate), or does it **reuse the construction-time token**?

## Why this matters

Indian broker tokens roll over **daily at ~3:00 AM IST** (session management is aligned to this — see `CLAUDE.md`). When the token rolls over, the live broker WebSocket drops. What happens next is entirely determined by the adapter's **reconnect path**:

- If the reconnect path **re-reads the token from the DB** (`get_auth_token(user_id)`) — or re-authenticates from static credentials — it picks up the fresh token and **self-heals**.
- If the reconnect path **reuses the token captured at construction** (baked into the WS URL, or held as `self.access_token`/`self.susertoken`), every reconnect retries with the **dead token**. At the **adapter level** the feed then stays dead until the process is restarted — though the proxy's connection-pool / auth-error recovery path *may* rebuild it after a re-login (see the Fyers note below). The durable fix is still per-adapter token refresh.

This is the root cause behind the recurring *"feed works after restart, dies again next morning, only a restart fixes it"* reports — the **daily reconnect/relogin failure class** in issues **#1419 (Fyers/Zerodha), #1226 (Dhan), #1421 (Zerodha)**.

**This is distinct from — not a replacement for — the eventlet concurrency bug.** Token-refresh explains the *daily* feed-death class **across brokers**. **#1421 additionally contains a separate, real Zerodha eventlet/threading bug** — `greenlet.error: Cannot switch to a different thread` — where monkey-patched threading primitives are touched across the asyncio↔eventlet boundary and crash the socket under load. That is a *second, independent* root cause in #1421 and needs its own fix (eventlet-safe `_real_threading` primitives, already applied to Zerodha). The monkey-patched threading exists in both self-healing and failing adapters, so it is not the differentiator **for the daily token-refresh class** — but saying "#1421 is not eventlet" would be wrong: #1421 is *both* the eventlet crash *and* (for the next-morning symptom) the token-refresh gap.

## Original audit summary

| Category | Count | Brokers |
|---|---|---|
| ❌ **PRE-FIX FAILS** — reused stale token on reconnect, needed restart | **21** | aliceblue, definedge, deltaexchange\*, dhan, firstock, fivepaisa, flattrade, fyers, groww, iiflcapital, indmoney, motilal, mstock, nubra, paytm, pocketful, samco, tradejini, **upstox**, zebu, zerodha |
| ✅ **SELF-HEALS (DB re-read)** — re-reads `get_auth_token` on reconnect | **3** | angel, kotak, shoonya |
| ✅ **SELF-HEALS (env re-login)** — XTS/env market creds, re-login each reconnect | **7** | compositedge, fivepaisaxts, ibulls, iifl, jainamxts, rmoney, wisdom |
| ➖ **N/A** — mock adapter, no token | **1** | dhan_sandbox |

\* **deltaexchange** is crypto (24/7, no 3 AM IST rollover) and uses long-lived API key/secret HMAC, so it has the structural weakness but no daily trigger — practically unaffected.

**Pre-fix headline:** **21 of 32 broker adapters could not recover from the daily token rollover on their own.** Only **3** truly re-read the DB token on reconnect (angel, kotak, shoonya); another **7** sidestep it via static XTS/env credentials.

## Current working-tree fix status

The working tree now applies the durable fix to the 21 originally failing broker adapters:

- **DB token refresh on reconnect:** aliceblue, definedge, dhan, firstock, fivepaisa, flattrade, fyers, groww, iiflcapital, indmoney, mstock, nubra, pocketful, samco, tradejini, upstox, zebu, zerodha.
- **DB feed-token refresh on reconnect:** paytm, because Paytm stores its streaming public access token in `feed_token`.
- **Token-provider / client rebuild pattern:** applied where the broker client owns the reconnect loop; URL/header-baked clients rebuild the URL or `WebSocketApp` after refresh.
- **Samco reconnect lifecycle:** fixed so an unexpected `run_forever()` return clears `running`; otherwise the adapter-level reconnect would update the token but the client would refuse to build a new socket as "already connected or connecting".
- **Motilal:** a token provider is wired into the reconnect path. Current `motilal_websocket.py` does not put `auth_token` on the wire in the binary login packet, so the refresh is harmless but the protocol should be rechecked separately if Motilal later requires the auth token in its WS handshake.

With these changes, the original "21 FAILS" list is now a **pre-fix baseline**, not the current expected behavior.

### ⚠️ Original correction on Upstox (pre-fix)

An earlier read claimed Upstox self-heals because it "re-fetches the authorized URL" on reconnect. The deeper audit shows that is **misleading**: `upstox_client.py:159` does re-fetch the URL, but `_get_websocket_url()` signs that request with `Authorization: Bearer {self.auth_token}` (`:355`), where `self.auth_token` is the **construction-time** bearer set once at `upstox_client.py:44` (from `get_auth_token` in `upstox_adapter.py` `initialize()`), and is **never re-read from the DB**. After the rollover the stale bearer is rejected (401) and `_get_websocket_url()` returns `None`, so the reconnect cannot complete. **Upstox FAILS.** The real-world observation that "Upstox was fine while Zerodha failed" (issue #1419) is explained by that Upstox instance running in **Analyzer/sandbox mode**, which does not exercise the live broker WS path — not by adapter resilience.

## Full original audit table (pre-fix)

| Broker | Token delivery | Refresh on reconnect? | Stall watchdog | Verdict |
|---|---|---|---|---|
| aliceblue | auth_msg | NO — `aliceblue_adapter.py:977` reconnect→`connect()` reuses `self.session_id` | no | ❌ FAILS |
| angel | constructor | **YES** — `angel_adapter.py:240-241` `get_auth_token`/`get_feed_token` in `_recreate_ws_client` | no | ✅ SELF-HEALS (DB) |
| compositedge | url (XTS) | env re-login — `compositedge_websocket.py:168` `marketdata_login()` each reconnect | no | ✅ SELF-HEALS (env) |
| definedge | auth_msg | NO — `definedge_adapter.py:212` reuses construction-time `susertoken` | no | ❌ FAILS |
| deltaexchange | auth_msg | NO — `delta_websocket.py:255` reuses `api_key`/`secret` | no | ❌ FAILS\* (crypto, no 3 AM rollover) |
| dhan | url (`?token=`) | NO — `dhan_websocket.py:129` reuses URL baked at `:100` | **yes** (`:390` `_health_check_loop`, DATA_TIMEOUT=90) | ❌ FAILS |
| dhan_sandbox | N/A (mock) | N/A — synthetic tick generator, no token | no | ➖ N/A |
| firstock | url (`jKey=`) | NO — `firstock_websocket.py:178` reuses `self.auth_token` | no (ping/pong only) | ❌ FAILS |
| fivepaisa | url (`Value1=`) | NO — `fivepaisa_adapter.py:116` reuses baked URL | no | ❌ FAILS |
| fivepaisaxts | constructor (env) | env re-login — `fivepaisaxts_websocket.py:176` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| flattrade | auth_msg | NO — `flattrade_adapter.py:846-849` reuses `self.accesstoken` | yes (`flattrade_websocket.py:367`) | ❌ FAILS |
| fyers | auth_msg (header) | NO — `fyers_hsm_websocket.py:863` reuses `self.access_token`; recovery delegated to pool | yes (`fyers_hsm_websocket.py:945`, DATA_TIMEOUT) | ❌ FAILS (pool-dependent) |
| groww | auth_msg (Bearer) | NO — `nats_websocket.py:478→489` reuses `self.auth_token` | no | ❌ FAILS |
| ibulls | constructor (env) | env re-login — `ibulls_websocket.py:173` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| iifl | constructor (env) | env re-login — `iifl_websocket.py:176` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| iiflcapital | constructor (JWT) | NO — `iiflcapital_websocket.py:640` `_reconnect_loop` reuses `self.user_session` | no (MQTT keepalive) | ❌ FAILS |
| indmoney | constructor (header) | NO — `indWebSocket.py:287` / `indmoney_adapter.py:332` reuse `self.access_token` | no | ❌ FAILS |
| jainamxts | url (XTS) | env re-login — `jainamxts_websocket.py:123` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| kotak | constructor | **YES** — `kotak_adapter.py:729` `get_auth_token` in `_recreate_ws_client` | no | ✅ SELF-HEALS (DB) |
| motilal | constructor | NO — `motilal_websocket.py:825→112` reuses `self.auth_token` | no | ❌ FAILS |
| mstock | url (`ACCESS_TOKEN=`) | NO — `mstockwebsocket.py:193` reuses `self.ws_url`/`auth_token` | no | ❌ FAILS |
| nubra | constructor (Bearer) | NO — `nubrawebsocket.py:102` reuses `self.bt` (`__init__:67`) | no | ❌ FAILS |
| paytm | url (`x_jwt_token=`) | NO — `paytm_adapter.py:173` / `paytm_websocket.py:228` reuse `public_access_token` | no | ❌ FAILS |
| pocketful | url (`access_token=`) | NO — `pocketful_adapter.py:95` reuses `self.access_token` | no | ❌ FAILS |
| rmoney | url (XTS) | env re-login — `rmoney_websocket.py:340` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| samco | auth_msg (header) | NO — `samco_adapter.py:111` reuses `session_token` | no | ❌ FAILS |
| shoonya | auth_msg | **YES** — `shoonya_adapter.py:1007` `get_auth_token` in `_attempt_reconnection` | no | ✅ SELF-HEALS (DB) |
| tradejini | url (`?token=`) | NO — `tradejini_adapter.py:118` reuses `self.ws_token` | no | ❌ FAILS |
| upstox | url (authorized) | NO — `upstox_client.py:159` re-fetches URL but signs with stale `self.auth_token` (`:44/:355`) | yes (`:288` `_force_reconnect`) | ❌ FAILS |
| wisdom | url (XTS) | env re-login — `wisdom_websocket.py:175` `marketdata_login()` | no | ✅ SELF-HEALS (env) |
| zebu | auth_msg | NO — `zebu_adapter.py:781` reuses `self.susertoken` | no | ❌ FAILS |
| zerodha | url (`&access_token=`) | NO — `zerodha_websocket.py:186` reuses `self.ws_url` (`:119`) | yes (`:533` `_health_check_loop`) | ❌ FAILS |

## Key observations

1. **A stall watchdog does NOT fix this.** Dhan, Fyers, Zerodha, Upstox and Flattrade all have a data-stall / health-check watchdog that forces a reconnect on silent stalls — but the forced reconnect re-enters the same path with the **same stale token**, so it cannot recover a token rollover. A watchdog without token-refresh just produces a tight reconnect loop against a dead token (a "reconnect storm").

2. **Three correct reference implementations exist** — copy these:
   - `broker/shoonya/streaming/shoonya_adapter.py` `_attempt_reconnection` (`:1007`) — `fresh_token = get_auth_token(self.user_id)` then rebuild the client.
   - `broker/angel/streaming/angel_adapter.py` `_recreate_ws_client` (`:240-241`) — re-reads `get_auth_token`/`get_feed_token`.
   - `broker/kotak/streaming/kotak_adapter.py` `_recreate_ws_client` (`:729`) — re-reads `get_auth_token`.

3. **The XTS/env family self-heals for a different reason.** compositedge, fivepaisaxts, ibulls, iifl, jainamxts, rmoney, wisdom authenticate their market-data feed with `BROKER_API_KEY_MARKET`/`BROKER_API_SECRET_MARKET` (static env credentials) and re-run `marketdata_login()` on every reconnect. Those credentials don't roll at 3 AM, so they recover — but via env re-login, not a DB token re-read.

## Fixes

### Proxy-level (broker-agnostic; applied in working tree, uncommitted at time of writing) — partial mitigation
The WebSocket proxy evicts a disconnected/stale per-user adapter and purges its pool on re-auth, forcing a rebuild with the fresh DB token (`websocket_proxy/server.py` `authenticate_client`, connected-state check; plus `cleanup_pools_for_user` on cache invalidation). This is a **partial** broker-agnostic safety net — **mitigation, not a complete durable fix**. It only fires when a **re-auth / cache-invalidation / surfaced auth-error** event occurs (e.g. the dashboard/SDK re-authenticates after the morning login). It does **not** guarantee autonomous recovery: an adapter that **silently loops on a stale token** — never triggering client re-auth and never surfacing an auth error to the pool — is **not** rescued by it. Those adapters still require the per-adapter fix below.

### Per-adapter (the durable fix) — applied for the 21 original FAILS brokers
Each originally failing adapter now re-reads the token from the DB and rebuilds the client/URL/header with it, mirroring Shoonya:

```python
def _attempt_reconnection(self):
    fresh_token = get_auth_token(self.user_id, bypass_cache=True)
    if fresh_token:
        self.access_token = fresh_token
    # rebuild the WS client / URL using the fresh token
    self.ws_client = BrokerWebSocket(..., access_token=self.access_token, ...)
```

For URL-baked brokers (zerodha, dhan, fivepaisa, mstock, paytm, pocketful, tradejini, firstock), the URL is **rebuilt** from the fresh token on reconnect, not reused.

### Docker / Ubuntu / custom-domain deployment validation

Validated against the deployment assumptions in `install/install-docker.sh` and `install/install-docker-multi-custom-ssl.sh`:

- Docker publishes Flask and WebSocket only on host loopback (`127.0.0.1:<flask>:5000`, `127.0.0.1:<ws>:8765`); nginx terminates HTTPS and proxies `/ws` to the WebSocket port.
- The install scripts set `WEBSOCKET_URL='wss://<domain>/ws'`, `WEBSOCKET_HOST='0.0.0.0'`, and `FLASK_HOST_IP='0.0.0.0'` inside the container, which is correct for Docker port mapping behind nginx.
- `ZMQ_HOST` remains `127.0.0.1`; broker adapters and the WebSocket proxy run in the same container, so the raw tick bus is not exposed publicly.
- The WebSocket proxy runs as a separate process from gunicorn/eventlet in Docker (`python -m websocket_proxy.server` from `start.sh`), reducing eventlet cross-thread risk for the proxy process.
- The proxy shutdown path now uses the imported `asyncio` alias (`aio`) correctly, so Docker `SIGTERM`/restart cleanup does not fail with `NameError`.
- The Zerodha eventlet fix uses real threading primitives when eventlet is loaded; in Docker proxy subprocesses eventlet is not expected to be loaded, and normal OS threads are used.

## Method / caveats

- Original verdicts are **adapter-scoped** and record the pre-fix reconnect behavior. The current working tree adds per-adapter refresh paths for the originally failing brokers.
- `fyers` was originally marked FAILS at the adapter level; its HSM client now re-reads the DB token and re-derives the HSM key before reconnecting.
- `dhan_sandbox` is the active factory adapter for the sandbox broker and is a pure mock (no token); the sibling `dhan_adapter.py` in that dir is unused.
- Audit performed by reading each adapter's reconnect method directly (not inferred from method names).
