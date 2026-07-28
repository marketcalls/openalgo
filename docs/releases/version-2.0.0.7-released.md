# Version 2.0.0.7 Released

**Date: 30th Apr 2026**

**Real-Time Performance Update: WebSocket Subscribe Batching across Dhan, Fyers & Upstox, Sandbox Event-Driven UI Updates, IIFL Capital Market Data Expansion & Flow Editor Stability**

This is a stability and performance update covering **26 commits** since v2.0.0.6. The headline change is a unified rewrite of WebSocket subscribe handling across three major brokers (Dhan, Fyers, Upstox) — instead of N per-symbol POSTs that hit broker rate limits and occasionally lost ticks for freshly-placed orders, subscriptions are now coalesced into batched grouped flushes. This closes a long-standing class of bugs reported across issues #1304 / #1314 / #1318 where ticks for newly-placed sandbox orders never reached the execution engine, manifesting as "price oscillates through the trigger but the order never fires." Combined with sandbox event-driven UI updates over the existing `analyzer_update` SocketIO channel, the OrderBook / TradeBook / Positions panes now refresh the moment a fill commits.

***

**Highlights**

* **WebSocket subscribe batching (Dhan, Fyers, Upstox)** — Per-symbol subscribe POSTs are now collapsed into single grouped flushes per broker. Closes the entire class of "freshly-placed order is invisible to the sandbox execution engine" bugs (issues #1304, #1314, #1318).
* **Sandbox event-driven UI updates** — Engine-internal fills, auto-square-off, and T+1 settlement now emit on the existing `analyzer_update` SocketIO channel. OrderBook / TradeBook / Positions refresh automatically the moment a fill commits.
* **IIFL Capital market data expansion** — Master contract optimization plus full historical data, quotes, depth, order, and margin API support (#1309, #1319). Brings IIFL Capital up to feature parity with the other Tier-1 brokers.
* **Fyers WebSocket overhaul** — Six separate fixes: HSM subscribe batching, positional-index → `brsymbol` mapping, shared dispatcher registry across reconnects, per-symbol OI gated to FNO-only with a >50-symbol skip, multiquote OI ceiling raised to 100, and index ticks fanned out to both Quote and Depth subscribers.
* **Dhan rate-limit hardening** — Minimum request interval bumped to 1.1s to stay under Dhan's "Order Received N in current second exceeds Limit 10" / 805 threshold.
* **Flow Editor stability** — Condition nodes honor their UI fields (and respect both `true/false` and `yes/no` edge handles), `{{var}}` interpolation supports list indexing, the Expiry node has a Futures/Options dropdown, the Config Panel scrolls on small viewports, and the Execution Log scroll is fixed.
* **Broker symbol normalization** — mstock `instrumenttype` normalized to `CE/PE/FUT` (Angel format), tradejini `expiry` stored as `DD-MMM-YY` (Zerodha format) — reduces broker-specific branching downstream (#1312).
* **Profile page UI fix** — Broker API secret no longer overflows the container or leaks the secret length through visual width.
* **Sandbox stale-field guard** — Drops `price` / `trigger_price` from order payloads based on `pricetype`, preventing leftover values from a previous order type from polluting the next placement.
* **Option chain exchange flip** — Underlying and expiry are now cleared atomically when the user flips the exchange dropdown, eliminating a transient mismatched state.
* **CI security scan resilience** — When `bandit`'s SARIF formatter crashes (a known upstream bug), the security scan no longer fails the entire CI run.

***

**Real-Time / WebSocket**

**Dhan**

* `1a80afb8` — `fix(dhan/ws): batch subscribes to collapse per-symbol WS messages into grouped flushes (#1314)`
* `5aa1156f` — `fix(dhan): bump min request interval to 1.1s to avoid 805 rate limit`

**Fyers**

* `671b8548` — `fix(fyers/ws): batch HSM subscribes to collapse N symbol-token POSTs into one`
* `5eb7baaa` — `fix(fyers/ws): join HSM<->OpenAlgo mapping through brsymbol, not positional index`
* `55129e6c` — `fix(fyers/ws): use shared dispatcher registry so multi-flush reconnects don't drop ticks`
* `15c2c63b` — `fix(fyers/multiquotes): per-symbol OI for FNO only, skip when >50 symbols`
* `81cecdbd` — `fix(fyers/oi-tracker): raise multiquote OI ceiling to 100, narrow OI tracker to 47 strikes`
* `b25bc931` — `fix(fyers/ws): fan out index ticks to both Quote and Depth subscribers`

**Upstox**

* `b9e44488` — `fix(upstox/ws): batch subscribe queue, LTPC carry-forward, larger reconnect budget`

The "price crosses trigger but pending sandbox order never fires" pattern reported across multiple brokers is fully resolved by these batching fixes. Ticks for freshly-placed orders now reliably reach the sandbox execution engine.

***

**Sandbox**

* `3ff65a3f` — `feat(sandbox): emit analyzer_update on engine-internal fills, square-off, T+1`
* `d3981b26` — `fix(sandbox): drop stale price/trigger fields by pricetype`

***

**Brokers**

**IIFL Capital (#1309, #1319)**

* `73857264` — Master contract optimization plus full market data API: historical, quotes, depth.
* `3ba5bf08` — Order API and margin API update.

**mstock**

* `df267180` — `instrumenttype` normalized to `CE/PE/FUT` to match Angel format.

**tradejini**

* `df267180` — Expiry stored in `DD-MMM-YY` format to match Zerodha.

**Dhan / Fyers / Upstox** — see Real-Time / WebSocket above.

***

**Flow Editor**

* `e16bb63c` — `fix(flow): condition nodes now honor their UI fields; respect both true/false and yes/no edge handles`
* `86f67310` — `fix(flow): support list indexing in {{var}} interpolation; fix Execution Log scroll`
* `b3d2ac11` — `fix(flow): make Config Panel scroll on small viewports`
* `193365f2` — `feat(flow): add Futures/Options dropdown to Expiry node`
* `5229c46e` — `docs(flow): document importer name field, fix node contracts, add 7 examples`
* `0f4f71f0` — `docs(flow): add prompt-style JSON import reference for the Flow Editor`

***

**UI / UX**

* `92b5c877` — `fix(ui): broker API secret no longer overflows / leaks length on Profile page`
* `975aafbc` — `fix(optionchain): clear underlying/expiry atomically on exchange flip`

***

**CI / Build**

* `3bdcd068` — `fix(ci): security scan no longer fails when bandit SARIF formatter crashes`

***

**Documentation**

* `d2baab90` — `docs(audit): add per-broker WebSocket keepalive/reconnect audit`
* `eb46e99c` — `docs(plans): expand GTT plan's Action Center coverage`
* `6f06329e` — `docs(claude): bump broker count from 24+ to 30+`
* `4a3b7861` — `chore(release): bump platform version to 2.0.0.7 and document bump procedure` — adds a Version Bumping section to `CLAUDE.md` clarifying the platform version (`utils/version.py` + `pyproject.toml`) is independent of the OpenAlgo Python SDK pin (`openalgo==1.0.49` in `requirements*.txt` and `pyproject.toml` dependencies).

***

**Contributors**

* **@marketcalls (Rajandran)** — release management, Dhan / Fyers / Upstox WebSocket subscribe-batching overhaul, sandbox event-driven UI updates, IIFL Capital market data expansion (#1309, #1319), Flow Editor stability fixes (condition nodes, list indexing, Expiry dropdown, scroll fixes), broker symbol normalization (mstock, tradejini #1312), Dhan rate-limit hardening, Profile UI fix, option chain exchange-flip atomicity, CI bandit SARIF resilience, and the per-broker WebSocket audit documentation.

***

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>

***


---

# Agent Instructions: Querying This Documentation

If you need additional information that is not directly available in this page, you can query the documentation dynamically by asking a question.

Perform an HTTP GET request on the current page URL with the `ask` query parameter:

```
GET https://docs.openalgo.in/change-log/release/version-2.0.0.7-released.md?ask=<question>
```

The question should be specific, self-contained, and written in natural language.
The response will contain a direct answer to the question and relevant excerpts and sources from the documentation.

Use this mechanism when the answer is not explicitly present in the current page, you need clarification or additional context, or you want to retrieve related documentation sections.
