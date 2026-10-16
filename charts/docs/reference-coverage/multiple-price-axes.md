# Multiple price axes

Scale identity and visible placement are independent. Existing `right`, `left`, empty and named overlay IDs stay valid. Named overlays remain hidden by default. A host may place any scale on either side and order the columns from the plot outward without changing its series, study resources, range, formatter, alerts or ratio lock.

`priceAxisPlacement` reads a detached placement, `setPriceAxisPlacement` changes it, and `priceAxisLayout` returns the active columns in pane CSS coordinates. Order zero is nearest the plot. An omitted order retains a scale's rank on the same side and appends it when switching sides. Invalid requests fail before mutation. Unused configured scales keep their placement but reserve no column. Attached series, including hidden series, and explicitly bound primitives occupy columns. An empty chart retains its default right column.

All panes share the maximum column count on each side so their time coordinates align. Each pane packs its active columns inward; unused outer cells have no price input target. Columns use the configured width, reduced equally on narrow charts to leave at least one column-width for the plot. Rendering, context menus, wheel input and axis dragging resolve the same column geometry. Tick and value labels are clipped to their own column. The primary crosshair price readout remains on the primary series' scale. Primitive lines retain plot coordinates while their axis labels receive their column's inner edge.

Full chart and workspace snapshots preserve placement with optional `PriceScaleState.placement` metadata. Old snapshots restore default placement. The subsequent [indicator template layouts](template-layouts.md) batch preserves column placement in templates with portable pane metadata and explicit copy and sharing policies.

Implementation and verification sequence:

1. Pure placement model and strict state parsing, with invalid, omitted, reordered and restored cases.
2. Pane slot geometry, independent rendering and primitive offsets.
3. Native chart APIs, persistence and exact pointer routing, including blank aligned cells and resized vector exports.
4. Packaged and example-host menus, API documentation and executable website example.
5. Unit tests, compiled-program compatibility, actual browser interactions and inspected screenshots in three engines. Retain the horizontal-pan autofit regression.

The legacy `movePriceAxis` method keeps its scale reassignment behavior. New placement APIs preserve IDs and permit multiple scales on the same side. No feed interface changes are needed.
