# Requested provider lifecycle

The native request path keeps existing raw-bar providers and adds optional
snapshots with explicit confirmation and availability. It adds no transport.
Requested expressions execute on their own observations before alignment to
chart bars. No source-language runtime or external API facade is involved.

## Provider and lifetime contract

`setBarsProvider` accepts the existing function or an object with `requestBars`
and optional `requestSnapshot`. `RequestedBarsSnapshot` is one shared base type,
also exported by the optional indicator tier. Raw bars cannot establish snapshot
capability or imply confirmation. Snapshot requests may carry `asOf`, a knowledge
cutoff independent of the requested opening-time bounds.

Every request combines caller cancellation with the instance lifetime. Native
hosts also bound it to their provider and market-context generation. Cancellation
rejects even when a provider ignores its signal. Replacing the provider cancels
pending requests before notification. Style-only changes retain managed work;
each managed helper owns cancellation for its data-setting key.

`requestState` exposes source identity/revisions, provider revision, explicit
requested-data revision and replay state. `subscribeRequestChanges` observes
those changes without altering the established data-change subscription.
`invalidateRequestedData` lets hosts announce an external update without
inventing a price tick or replacing their provider.

## Availability and replay

Timed replay publishes its availability clock even when the displayed primary
observation does not change. Snapshot requests are capped at that clock; an
explicit earlier cutoff remains earlier. Legacy replay has no known availability
clock and cannot provide strict requested snapshots.

Providers must supply the value version known at `asOf`, or reject that request.
Filtering today's revised values by availability cannot reconstruct past values.
Managed calculations receive only the confirmed, available prefix under an
explicit cutoff. Unknown or unconfirmed interior observations block later ones
without compaction. Callers choose alignment times explicitly when they need a
reading within the currently displayed primary bar.

## Managed calculations

`createRequestedIndicator` owns a snapshot and a pending request in the study's
store. A selector identifies the requested source and range, including expression
warmup. The expression runs before alignment; carry and missing-result policies
come from the existing pure helpers. A null selector or absent snapshot capability
publishes unsupported status rather than fabricated values.

Provider, source, market, history and data-setting changes cancel obsolete work
and clear the previous result. Tail updates, external invalidation and forward
replay movement allow one active request with one catch-up for the newest state.
Replay entry, exit and backward movement invalidate the previous generation.
Pending work survives a synchronous style reattachment when its data key is
unchanged. Removal cancels requests and releases subscriptions.

## Verification

The implementation passes 29 native request cases, 19 cancellation-helper cases
and 38 managed-expression cases. A compiled expression exercises requested
confirmation and provider replacement through the unchanged companion adapter.
Review reproductions cover custom-host method receivers, replay interruption,
initial source-state immutability, native calculation error handling and style
reattachment before or during a provider call.

Use deferred providers and actual chart mutations to prove cancellation, stale
completion rejection, same-time refresh, correction/reset invalidation, source
replacement, requested confirmation and replay clock changes. Preserve legacy
raw-bar behavior and existing managed style retention. Exercise a compiled
expression, runnable website controls and actual pixels in all three browsers.

The raw-point `createTier2Indicator` helper has its own
[external lifecycle](external-lifecycle.md). Native revisions now refresh its
forming overlap and invalidate provider, source and history generations. Replay
requires an explicit historical-value promise from that descriptor. Snapshot
capability does not manufacture metadata for raw points or raw bar requests.
