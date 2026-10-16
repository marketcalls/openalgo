# Dependent study inputs

Tracked scalar study inputs schedule calculations as a dependency graph without
changing source bars or the existing descriptor calculation signatures. The
initial built-in consumers are SMA, EMA and WMA; other descriptors opt in explicitly.

## Additive source contract

A stable reference contains `kind: 'indicator'`, `instanceId` and `plotKey`.
Source inputs opt in with `allowStudyOutputs`; existing string selections remain
unchanged. Only declared, opted-in inputs create graph edges. A context resolver
lets `sourceValues` read those inputs, while ordinary two-argument calls retain
their behavior. A reference without a resolver must fail clearly.

Values align by primary bar index, not painted coordinates. Require exact column
length, retain null/nonfinite gaps, and ignore visibility, plot offset, pane and
scale placement. An OHLC plot needs a separately declared scalar output before
it can be selected. Start with three moving-average descriptors and extend other
descriptors deliberately.

## Scheduling and mutation

Keep display order separate from stable topological calculation order. Producers
run before consumers once per flush, including settings changes and asynchronous
requested-data arrivals. Consumers read committed snapshots without recursively
calling the public `values()` accessor. Visual stacking and bar-color precedence
continue to follow display order.

Validate the proposed graph before changing settings, styles or subscriptions.
Reject cycles, self-links, malformed references and unsupported inputs atomically.
Clone accepted and returned reference objects so outside mutation cannot bypass
validation. Track instance generation in addition to persisted identity, source
identity, output revision, history revision and availability.

Only a proven unchanged prefix permits incremental downstream calculation. A full
upstream calculation, correction, settings change or external arrival initially
forces a full downstream pass. A successful upstream tail splice can establish
the narrower guarantee.

## Unavailability and persistence

Removal preserves the consumer's reference and marks it unavailable; it never
retargets another instance or falls back to price. A failed producer's retained
visuals are not fresh input. Clear dependent output, suppress dependent alerts,
publish an explicit error and propagate unavailability until recovery.

Restore validates the complete graph, reserves identities, creates studies in
dependency order and retains saved display order. Missing descriptors preserve
the existing skip behavior while their dependents remain unavailable. Templates
carry their dependency closure, allocate fresh IDs and rewrite internal references
before existing parsing discards copied IDs. Reject external template references
initially. Repeated copies create independent graphs, including after earlier
copies have been removed. A fresh random namespace prevents reuse of saved alert
anchors across reloads. Native automatic identities also reserve direct indicator
and drawing-input alert anchors before allocation.

## Independent verification

An average of an average over closes `[1, 3, 5, 7]` with both lengths two produces
`[null, null, 3, 5]`. Changing the final close to nine produces a final value of
5.5. On the original data, changing the producer length to three produces `[null, null, null, 4]` without
a price update. A diamond graph must calculate once per node regardless of display
order. Cover gaps, source correction followed by a coalesced tail update, atomic
cycle rejection, removal/error recovery, reverse-order restore and repeated
template copies. Check the unchanged companion adapter as well as the new native
capability; the adapter must opt in explicitly to consume these references.
