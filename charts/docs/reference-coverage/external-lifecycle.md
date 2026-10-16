# External point lifecycle

The existing raw-point helper remains useful for provider-owned analytics and
subscriptions. Its native lifecycle must refresh a forming observation even when
the primary bar's timestamp does not change. Raw bars remain a supported provider
format; this work adds no transport or datafeed facade.

## Identity and refresh

Use the optional native request-state and request-change hooks. Provider, market,
source, reset and correction changes invalidate old history and live callbacks.
Prepending unchanged history retains the established boundary and live-over-history
precedence when the prefix relationship is known. A history-only descriptor
refreshes the forming overlap on source revisions; a descriptor with a live
subscription does not refetch on every price tick. Explicit requested-data
invalidation refreshes the complete window for both kinds of descriptor.

An active request completes without being cancelled by each tick. Changes collapse
into the newest desired state afterward; extending both ends can require a prefix
page followed by a tail page. A synchronous style
reattachment inherits the same pending request. Settings listed in `refetchOn`
invalidate data; the other settings only recalculate and restyle.

Register a stable pending request before publishing loading or invoking provider
code. Clear ownership before aborting requests or stopping subscriptions. A
subscription returned after synchronous generation changes must be disposed
immediately. Removal releases all listeners and rejects late completions.
Calculation failures must not be overwritten by a successful fetch status. A
successful cached recalculation restores the explicitly published lifecycle
status, so it cannot settle a newer request that is still loading.

## Historical knowledge

`Tier2Context` exposes optional `requestState` and `asOf`. Native replay is
unsupported unless the descriptor declares `supportsReplay: true` and the replay
clock supplies a finite cutoff. Opting in promises that fetched points represent
the values known at that cutoff and that each point's timestamp represents when
its value is available. The helper cannot reconstruct historical versions from
today's revised values.

Replay entry, exit and backward movement clear the previous generation. Forward
clock changes refresh the complete window even within the same primary bar.
Each accepted replay snapshot replaces the previous points, including deletions
and revisions. Live subscriptions are stopped throughout replay and restored on
exit. Legacy handcrafted contexts without request state retain their established
range and alignment behavior.

## Verification sequence

1. Reproduce same-time stale output with an actual chart and a compiled expression.
2. Cover deferred history, latest catch-up, native provider and source replacement,
   reset/correction, prepend boundaries, error recovery and removal.
3. Exercise status, fetch, abort and subscription reentry, including style changes.
4. Prove historical version replacement, within-bar cutoff movement, backward seek,
   live restoration and explicit unsupported states.
5. Run unchanged custom-context tests, the compiled adapter integration and actual
   website controls with pixel inspection in three browser engines.
