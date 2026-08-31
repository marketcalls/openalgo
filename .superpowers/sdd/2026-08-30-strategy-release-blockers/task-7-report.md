# Task 7 report: strategy and WebSocket contract alignment

## Scope and commits

Task 7 aligned the rewritten `/strategy` runtime, API pages, prompt references,
PRD, BDD and traceability, then completed two independent-review revisions.
Work stayed on `main`; nothing was pushed. The external QA workspace was not
modified.

- Original documentation implementation: `f0948a98`
- Revision round 1: `48a1cdcf`
- Revision round 2: `74a1306c`

## Original implementation (`f0948a98`)

The original pass added permanent documentation contracts and updated the
strategy API, prompt, PRD, BDD and traceability inventory to the confirmed-flat
runtime delivered by Tasks 1-6. It documented durable intent and
acknowledgement, exact `position_ref` ownership, pending stops, recovery and
P&L authority, broker-primary books, unavailable numeric truth and rejection
context.

Evidence captured before that commit:

- Documentation contracts: 6 passed.
- Focused strategy backend: 1064 passed, 1 xfailed.
- WebSocket mode contracts: 34 passed.
- Frontend strategy tests: 183 passed.
- TypeScript and affected Biome checks passed.
- Every BDD `# Source:` anchor resolved to a declaration.
- Inventory: 62 functional requirements, 7 non-functional requirements and 34
  strategy BDD scenarios.

## Revision round 1 (`48a1cdcf`)

### RED evidence

The first review found a real array-unsubscribe defect and seven documentation
inaccuracies.

```text
uv run pytest -q test/test_websocket_unsubscribe_contract.py
4 collected: 3 failed, 1 passed
```

Documented top-level `LTP` and `Depth` array requests reported success while
making no adapter call and leaving the exact subscription live. The internal
client also omitted the fallback mode from each symbol.

```text
uv run pytest -q test/test_strategy_module_docs.py
10 collected: 4 failed, 6 passed
```

Those failures pinned the stale depth/error wire examples,
heartbeat/reconnect claims, webhook preflight-audit claim, PRD
ordering/polling scope and signal quantity table.

### Changes and GREEN

- Array mode precedence is per-symbol mode, then top-level mode, then `Quote`.
- The client emits an explicit mode on every unsubscribe symbol.
- Depth frames use `data.depth.buy/sell`; invented depth fields/errors were
  removed.
- Webhook documentation distinguishes route preflight from the durably audited
  pipeline.
- Batch and signal ordering, bounded REST safety polling, signal quantities,
  heartbeat/reconnect ownership and strategy book service boundaries now match
  runtime.

```text
uv run pytest -q test/test_strategy_module_docs.py \
  test/test_websocket_unsubscribe_contract.py \
  test/test_mode_normalization.py \
  test/test_eventlet_cross_thread_locks.py
58 passed
```

```text
uv run pytest -q test/test_strategy_module_webhook.py \
  test/test_strategy_module_signal_api.py \
  test/test_strategy_module_signals.py \
  test/test_strategy_module_engine.py \
  test/test_strategy_module_tick_feed.py
252 passed
```

Mutation proof changed the server fallback back to unconditional Quote. Both
mode-specific cases failed; restoring the implementation made both pass.

## Revision round 2

### Transactional unsubscribe RED

The second review found that the server deleted final-owner registries before
the broker acknowledgement, acknowledgements did not identify canonical mode,
and the client correlated duplicate same-symbol modes by response order.

```text
uv run pytest -q test/test_websocket_unsubscribe_contract.py
17 collected: 13 failed, 4 passed
```

The failures covered error, malformed and exception responses for exact and
all-symbol unsubscription; lowercase canonicalization; mixed Depth/LTP
correlation; ambiguous legacy acknowledgements; and client
`unsubscribe_all` clearing without an acknowledgement.

The acknowledgement documentation contract also failed before an exact schema
was documented:

```text
uv run pytest -q \
  test/test_strategy_module_docs.py::test_websocket_unsubscribe_ack_identifies_the_exact_canonical_mode
1 failed
```

### Disconnect-lifecycle correction RED

The first round-2 implementation retained a failed owner for a second
`cleanup_client(client_id)` call. Production calls cleanup only once from
`handle_client(... finally)`, so that test described an unavailable retry and
would have leaked a dead client registry owner and adapter.

The corrected no-socket tests invoked production cleanup once and included the
special persistent brokers plus pooled acknowledgement propagation:

```text
uv run pytest -q test/test_websocket_unsubscribe_contract.py \
  -k "single_disconnect or explicit_refusal_remains or special_broker or connection_pool"
14 selected: 14 failed
```

Shoonya also cleared its adapter registries and returned success after a
broker-side batch refusal:

```text
uv run pytest -q \
  test/test_websocket_unsubscribe_contract.py::test_shoonya_unsubscribe_all_reports_broker_failure_and_retains_tracking
1 failed
```

### Final ownership behavior

- Explicit unsubscribe is transactional. A final owner remains in both proxy
  registries until an exact dictionary acknowledgement with `status: success`.
- Another client's exact ownership is removed locally without a broker call.
- A socket disconnect is terminal for that client session. One cleanup call
  removes every dead registry reference.
- A failed exact release with another live client is bounded by the adapter's
  symbol cap and reclaimed by the real last-client teardown.
- Last-client cleanup disconnects ordinary adapters. Flattrade and Shoonya keep
  their persistent connection only when `unsubscribe_all` explicitly succeeds;
  refusal, malformed response or exception falls back to disconnect and local
  adapter eviction.
- `ConnectionPool.unsubscribe_all` and `_PooledAdapterWrapper.unsubscribe_all`
  now propagate child success/error instead of discarding it. Pool tracking is
  cleared only after all children acknowledge success.
- Shoonya retains its local tracking on partial broker failure and returns an
  error, allowing the proxy to select authoritative disconnect teardown.
- Successful and failed server acknowledgement rows carry canonical `mode`.
  The client correlates by exact `(exchange, symbol, mode)` and accepts a legacy
  mode-less acknowledgement only for one unambiguous requested mode.
- Client `unsubscribe_all` waits through the existing request-id future and
  removes only acknowledged exact modes.

No lock, thread, task, socket or registry was added. The pool's existing lock
continues to serialize its existing adapter operations; client-side locks cover
only bounded in-memory snapshots and mutation.

### Manual-script collection and credential hygiene

An aggregate probe demonstrated that `test/test_websocket_service.py` was an
interactive CLI misclassified by pytest: six required function parameters were
reported as missing fixtures. This was a collection-harness defect, not a
product test failure. `test/test_websocket.py` is another live CLI using the
same `test_*.py` naming pattern.

Both scripts are now explicitly listed in `test/conftest.py:collect_ignore`.
Permanent tests prove their CLI entry points remain present. Both now read only
`OPENALGO_API_KEY`, fail closed before client/service/socket construction when
it is absent, and contain zero 64-hex credential-shaped literals.

```text
uv run pytest -q test/test_manual_script_collection.py
2 passed
```

The pre-existing committed credential-shaped values must be treated as
potentially exposed. Their validity cannot be established locally; the
operator should rotate the corresponding OpenAlgo API key.

The exact full-scope collection gate completed without collection errors and
did not collect either live WebSocket script:

```text
uv run pytest --collect-only -q test -p no:cacheprovider
3711 tests collected
```

Python 3.14 emitted a shutdown-only logging weak-reference traceback after the
successful collection summary. The pytest process exited zero; the message was
not a collection error.

### Final GREEN and mutation evidence

```text
uv run pytest -q test/test_websocket_unsubscribe_contract.py
39 passed
```

```text
uv run pytest -q test/test_manual_script_collection.py \
  test/test_websocket_unsubscribe_contract.py \
  test/test_strategy_module_docs.py \
  test/test_mode_normalization.py \
  test/test_eventlet_cross_thread_locks.py \
  test/test_strategy_module_tick_feed.py \
  test/test_flattrade_protocol.py
136 passed in 19.69s
```

Mutation evidence:

- Restoring pre-ack ownership deletion failed the refusal-preservation test;
  the restored transaction passed.
- Restoring the rejected early return after disconnect refusal failed the
  one-shot cleanup test; the authoritative teardown passed after restoration.
- Adding a synthetic 64-hex literal failed the manual-source contract.
- Bypassing the missing-environment gate failed the fail-closed CLI contract.
- Moving the BDD source line without refreshing its anchor failed source-anchor
  validation; the declaration anchor passed after refresh.

Ruff baseline/current counts did not increase:

| File | HEAD | Current |
| --- | ---: | ---: |
| `websocket_proxy/server.py` | 10 | 10 |
| `websocket_proxy/connection_manager.py` | 5 | 5 |
| `websocket_proxy/broker_factory.py` | 3 | 3 |
| `services/websocket_client.py` | 4 | 4 |
| `broker/shoonya/streaming/shoonya_adapter.py` | 0 | 0 |
| `test/test_websocket.py` | 0 | 0 |
| `test/test_websocket_service.py` | 2 | 2 |
| `test/conftest.py` | 0 | 0 |
| Both permanent contract files | 0 | 0 |

The full backend runtime suite was deliberately not rerun in Task 7; Task 8
owns that mandatory gate. Task 7 proved that its full test tree collects, then
ran the focused automated runtime and contract suites above.

## FD and memory audit

- Explicit failure retention reuses the existing bounded subscription rows; it
  creates no second registry or retry worker.
- Every disconnect path purges the dead client from `clients`, `subscriptions`,
  `subscription_index`, `user_mapping` and `order_subscribers`.
- Ordinary last-client teardown calls adapter disconnect and evicts the local
  adapter even if disconnect raises, preventing reuse of a stale owner.
- Persistent-broker failure falls back to the same disconnect path; pooled
  disconnect clears child adapters, subscription maps and the global pool.
- The only residual after a failed exact release while another client is live
  is inside the existing broker adapter, bounded by the configured 3,000-symbol
  pool cap and reclaimed at last-client teardown.
- Tests open no WebSocket, ZMQ socket, thread or broker connection.

This was verified behaviorally through refusal, malformed response, exception,
multi-client, last-client and disconnect-exception tests, plus static path
review. No unbounded descriptor or memory owner was introduced.

## Diff, commit and preserved files

- `git diff --check`: clean (Windows line-ending notices only).
- Revision-round-2 implementation commit: `74a1306c`.
- Preserved untracked user files:
  - `db/openalgo.db.bak-20260830-151659`
  - `test_editor_strategy.py`
