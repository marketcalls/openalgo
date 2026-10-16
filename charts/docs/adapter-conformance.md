# Adapter conformance

Run the reusable history and lifecycle contract with:

```sh
npx vitest run tests/adapter-conformance.test.ts
```

The reference cases use production code with deterministic, authored transport
inputs. Every reference suite is labelled `synthetic transport` in test output.
These tests require no service, network access, account or credential.

## Reference boundaries

The broker reference runs `OpenAlgoLiveDataFeed` through
`DataLoadingController`. The controller is the normalizing host boundary:
the bare broker history adapter sorts rows, while the controller resolves
duplicates, validates candles, owns cancellation and merges repairs. Socket
frames enter the production authentication, subscription and candle-builder
paths through an injected socket factory.

The crypto reference runs the website's existing `createBtcUsdFeed` from
`website/lib/market-data/btc-usd.mjs`. It is a polling host, not an implementation
of the library's `DataFeed` interface. Its driver exposes the host's delivered
candles and maps the `connected` status to the shared runner's `ready` status.
It does not add parsing, correction, retry or cancellation behavior.

The shared runner therefore checks the history visible to a host. It does not
claim that both underlying transports have the same capabilities.

| Behavior | Broker reference | Crypto reference |
| --- | --- | --- |
| Sorted, unique UTC-second history | Controller consumes unsorted broker rows | Production tuple parser consumes newest-first millisecond rows |
| Duplicate winner | Last occurrence in the history response | First occurrence in the newest-first response |
| Authoritative repair | Closed candle values replace earlier values | A fresh polling snapshot replaces earlier values |
| Initial HTTP failure | Error with no invented history | Error with no invented history |
| Network, HTTP, provider and malformed-candle refresh failures | Previous history stays visible and stale, retry clears the error | Same contract |
| Obsolete history or repair response | Abort reaches fetch, late completion cannot change the new interval | Same contract |
| Destroy during load or repair | Abort and suppress later publications | Same contract |
| Repeated live observation | Repeated Quote cumulative volume does not increase bar volume twice | Polling snapshots, no tick subscription |
| Late quote | Existing `foldIntoBar` policy updates the current candle and emits no historical bar | Obsolete polling response is ignored |
| Reconnect | Reauthenticate, restore one subscription, request authoritative repair, buffer arriving quotes and reseed | Failed poll retries on its normal timer |
| Unsubscribe | Idempotent release preserves other consumers, final release detaches bar and resync listeners | Destroy removes the polling timer and prevents further delivery |
| Calendar and quantity reference | Fixed 15-minute bars at an Asia/Kolkata market opening | Weekend candles cross UTC midnight with fractional volume |

The late-quote case records the existing broker policy; it does not imply that
an older event is a newer trade. A consumer needing exchange-sequence ordering
must establish that policy in its feed. Likewise, repeated cumulative-volume
quotes are distinct from unnumbered trade events: these cases make no promise
that identical trade quantities in an `ltq-sum` stream can be deduplicated
without event identity.

During a broker repair, the production controller keeps the historical open,
widens high/low with buffered observations, keeps the buffered close and takes
the larger snapshot volume. It does not add overlapping history and live
volumes. Closed candles without concurrent observations take the authoritative
values, including corrections that reduce previous extremes or volume. This
is snapshot reconciliation, not reconstruction of every missed trade.

## Extending the contract

`tests/conformance/adapter-contract.ts` exports `AdapterHarness`,
`AdapterFixtures`, `AdapterReference` and `adapterContractChecks`. Add a factory
to `adapterReferences` in `tests/conformance/reference-adapters.ts` to run every
shared case and both negative controls against another source.

The factory supplies these boundaries:

1. `load(interval?)` and `refresh()` drive the real adapter or host and resolve
   after its operation settles.
2. `snapshot()` exposes delivered bars, interval, status and error. Normalize
   status vocabulary only; do not filter, sort, repair or deduplicate bars in
   the driver.
3. `publications` records each public delivery so stale callbacks and teardown
   can be checked even when the final values happen to match.
4. `transport` is a `ControlledTransport` whose injected fetch queues requests.
   The suite resolves or rejects each request explicitly. It intentionally
   completes aborted requests to exercise generation guards.
5. `fixtures` provides raw duplicate, corrected, invalid and provider-error
   payloads alongside independently stated expected bar values and two
   supported interval tokens. Encode the source's duplicate ordering clearly.
6. `destroy()` releases every owned request, subscription and timer and remains
   safe when called more than once.

Use fake timers and create a fresh factory instance per case, as the existing
test entry does. Its teardown requires zero remaining timers. Source-specific
checks belong beside the shared registration and must state which capability
they exercise. A polling retry must not be described as a socket reconnect.

The negative controls wrap the observed output to introduce duplicate candles
or discard authoritative repairs. The same shared assertions must reject these
deliberately nonconforming outputs for each reference. They guard against a
runner that accepts fixture output without actually checking the contract.

## Evidence and limits

| Evidence class | What this suite supplies |
| --- | --- |
| Authored deterministic transport | Yes. Deferred HTTP responses, synthetic socket frames and fake timers exercise the production implementations. |
| Sanitized captured market traffic | No. The fixtures were authored for the test cases. |
| Connected broker or public-market session | No. Network access is not part of the runner. |
| Real rendering, browser endurance or device measurement | No. These are separate verification gates. |
| Orders, fills or account authority | No. The references are market-data paths only. |

For a machine-readable report, create `artifacts/candidate` first, then run:

```sh
npx vitest run tests/adapter-conformance.test.ts --reporter=verbose --reporter=json --outputFile=artifacts/candidate/p2-conformance.json
```

Keep raw reports outside committed source. Include the tested source revision,
command, runtime and evidence class when recording a result. The synthetic
reference labels are present in the JSON test names. A green synthetic result
must not be relabelled as a connected-feed validation.

A separate connected-feed report should record the source and adapter version,
UTC observation window, instrument and interval, timezone/session policy,
transport and volume mode, observed disconnect/reconnect and unsubscribe
outcomes, and any case that could not be exercised. Keep authentication secrets
and account data out of the report. Captured fixtures need their capture
provenance and sanitization recorded separately from authored fixtures.

The existing detailed regressions remain useful alongside the shared contract:

```sh
npx vitest run tests/openalgo-rest-request.test.ts tests/hardening-live-feed.test.ts tests/data-controller.test.ts tests/data-controller-review.test.ts tests/data-controller-repair.test.ts tests/data-controller-lagging-refresh.test.ts
node --test scripts/check-btc-usd-feed.test.mjs
```

Those suites cover additional provider parsing, request deadlines, aggregation,
paging, repair windows and subscription ownership. They remain separate so a
provider-specific protocol change does not alter the generic contract.
