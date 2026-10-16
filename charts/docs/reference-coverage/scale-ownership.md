# Whole-study scale ownership

The existing series reassignment API intentionally rejects indicator plots. Moving
one plot would leave its fills, levels, drawings and legend on another scale.
This capability now moves those resources in one indicator transaction.

## Verified implementation

The native host implements the contract below. Twenty-six whole-study cases,
22 range-ownership cases, 19 binding cases, five drag cases and 21 workspace
cases pass. Six real-browser cases cover the transaction and exact documented
example across all three engines. Browser pixels check fills, levels, drawings,
markers and overlays; vector checks verify left-axis bounds. Nine existing scale
cases and three example autofit cases also pass against the same built bundle.

Manual view overrides retain their range when a study changes its declared
default; explicit autofit uses the updated default. Calculated fill columns need
not have visible plot series. Native renderer changes retain the plot handle.

Whole-axis moves currently reject mixed local assignments and explicit price-pane
overlays atomically. One saved whole-study override cannot represent a partial
transfer. Per-plot placement and multiple visible axes remain additional work.

## Public contract

Add `IndicatorApi.priceScaleId(): PriceScaleId | null` and
`setPriceScale(scaleId: PriceScaleId | null): boolean`. An explicit ID overrides
all local plot assignments. `null` restores descriptor assignments. Retain the
override separately from calculation settings and accept it when creating or
restoring an indicator. Invalid, removed and unchanged requests return false
before mutation. Existing hosts may omit the new internal ownership hooks.

Explicit price-pane overlays keep their placement and descriptor scale. Markers
anchored to price keep their primary-series binding. Tables and background shading
remain screen-space resources. A fill must not silently span endpoints in different
coordinate systems; validate mixed pane/scale endpoints before moving anything.

## Foundation and transaction

1. Bind owned price primitives to a scale in `Pane`. Use that binding for every
   paint layer, hit-testing, autoscale, SVG export and pane transfer. Unbound host
   primitives retain their existing right-scale behavior.
2. Give price lines enough axis-placement context to label a left scale or omit
   their axis tag on a hidden scale. Bind fills and free-standing drawings without
   detaching their lifecycle.
3. Resolve plots through the same override on creation, settings-driven renderer
   recreation and pane movement. Format legend readings with each actual plot scale.
4. Replace pane-wide range cleanup with owned, scale-specific range claims. Removing
   one study must not clear another source's fixed range, manual range or ratio lock.
5. Validate every affected handle and binding, then update records, primitive
   bindings, the override and range ownership before repaint or public notification.
   Emit one object-change event and refresh the legend/layout. Do not recalculate,
   reattach providers or evaluate alerts merely because the scale changed.

Configured target scales retain their options and range. Explicit plot formatting
applies in descriptor order: price format followed by style precision, matching
creation behavior. A shared scale has one formatter; the last explicit assignment
wins. A descriptor fixed range is a default for an eligible unconfigured scale,
not permission to replace host-owned configuration. Runtime custom formatters are
not serialized or delegated through the old scale's mode-dependent formatter.

## Persistence

Add optional `priceScaleId` to indicator state, workspace validation and templates.
Omission preserves legacy descriptor assignments. Validate before restoration
mutation, initialize the override before calculation/attachment, and restore saved
scale configuration after rebuilding studies. Template copies retain the override
while continuing to discard copied instance identities.

## Acceptance

Move a multi-plot study right, left, hidden and back without changing instance,
plot, marker or data identities. Check fills, gradients, levels, drawings, legend
formatting and alert references against the same scale. Cover overlays, shared and
configured empty targets, settings recreation, pane moves, hiding, source updates,
removal, state/workspace/template restoration, invalid requests and synchronous
notification reentry. Verify actual browser pixels and SVG clipping.

[Multiple visible scales](multiple-price-axes.md) now use ordered columns, shared
rendering and input geometry, independent label collision resolution, and saved
placement. Scale IDs remain stable when an axis moves. Indicator templates still
need axis metadata and an explicit copy-versus-sharing policy; their saved scale
IDs alone cannot preserve column placement.
