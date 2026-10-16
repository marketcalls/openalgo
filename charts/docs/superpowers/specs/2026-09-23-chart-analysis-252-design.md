# Chart analysis and linked views, 2.5.2

Approved scope: interactive Anchored VWAP and fixed-range Volume Profile drawings,
drawing and appearance synchronization across linked charts, and grouped timeline
events with clustering and details. A packaged tabbed workspace is out of scope.
Source: master at 4bfe3897c8d309792b417a71cf2498345c9d1e7c.

## Analysis drawings

Add `anchored-vwap` (one time anchor) and `fixed-range-volume-profile` (two time
anchors) to the drawing registry. They use the owning pane's OHLCV bars, retain
time anchors across history changes, and participate in ordinary selection,
properties, drag, undo, deletion and JSON restore. Computation is independent of
screen coordinates. Missing volume must not masquerade as a valid measurement.
The profile estimates volume by distributing each candle's volume over its price
range; it is not exchange trade-by-trade volume. Limit histogram work and settings
to bounded values. Recompute a changed forming bar. Clip drawing output at the
plot edges. Expose useful source/band and row/value-area settings through the
existing drawing property schema. Ship no new runtime dependency.

## Linked drawings and appearance

Both channels are opt-in. Drawing synchronization requires a matching symbol and
exchange, and supports different intervals through time anchors. Missing instrument
identity cannot authorize replication. Keep drawing implementation in the draw
tier and use structural adapters where the base link group needs host cooperation.
New drawings and changes, including drag previews, deletion and undo/redo, should
reach peers without recursive broadcasts or shared mutable objects. Existing local
drawings remain local unless explicitly shared. Only price-pane drawings synchronize
by default; unrelated study panes have no safe shared identity. Preserve local
selection and local undo history, and clean up previews on cancellation, context
changes, unlink and destruction. Never replicate alerts or trading objects.

Appearance synchronization copies chart visual settings only. It does not copy
instrument identity, timeframe, indicators, event feeds, order state or data.
The reference host exposes independent Drawing and Appearance switches beside
the existing linking controls. Defaults retain current behavior.

## Timeline events

Extend the current event primitive compatibly with optional event details, groups,
group visibility and zoom-dependent clustering. Existing event data remains valid.
Group visibility includes descendants, with cycles rejected. Events need not match
an exact candle timestamp: anchor to chart time, including session gaps, without
changing stored timestamps. Cluster identity and hit results let a host show all
members. Keep all layout/filter/model logic DOM-free. The widget tier owns an
accessible details popup rendered as text, with Escape/close, focus handling and
pointer isolation. An optional host detail loader must ignore stale results after
selection changes or disposal. Neither the engine nor the example invents a live
calendar feed. Demonstration events are clearly labelled sample data.

## Delivery and proof

Use the yfinance reference host and website examples to exercise the public APIs.
Add regression tests before implementation, then real Chromium, Firefox and WebKit
checks and inspected screenshots. Verify the packed candidate in an isolated
consumer without changing the active OpenAlgo checkout. Update public API skill
references, API documentation, release notes, README and architecture measured
facts. Follow CLAUDE.md for complete checks, immutable tag, trusted npm publishing,
GitHub release, website deployment, tarball/provenance comparison and deployed
browser validation. Publication is already authorized by the user.
