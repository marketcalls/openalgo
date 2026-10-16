# Chart interface improvements for 2.5.3

## Approved outcome

Make the existing widget and yfinance reference host easier to use for traders who inspect many studies and drawings. The user approved six improvements: a docked data window, an organized object tree, richer symbol search, consistent colour controls, management of running studies in the indicator picker, and direct typing for symbol and interval entry. Keep the current compact terminal identity and nine-tier architecture. A packaged multi-chart workspace is outside this release.

## Compatibility and boundaries

- Base and non-widget tiers remain DOM-free. No new runtime dependencies.
- Preserve all existing public calls and stored records. Additive optional state must tolerate missing, malformed and stale values.
- Existing drawing shortcuts, text editing, order authority, alert scope, replay guards and symbol/exchange identity take precedence over convenience input.
- Active OpenAlgo source is owned by another developer and must not be edited. Validate the candidate in an isolated consumer only.
- Keep comparison names out of source, tests, comments and documentation. Use plain English and the existing design tokens.
- Version, documentation, examples and measured bundle facts must agree before publication.

## Interface design

### Shared colour controls and forms

Use a compact square trigger and a themed popover containing a fixed palette, a bounded recent-colours row, a custom colour input and an opacity control when the field supports it. Preserve the field's value contract: a separate opacity setting remains separate, while an alpha-bearing colour retains alpha. Opening and cancelling cannot mutate values. Live preview and release-only changes remain distinct. Keep paired bullish/bearish swatches in one row. Focus, Escape, disabled state, light/dark theme and CSP must work through existing mechanisms. Native custom colour selection may remain an explicit fallback inside the themed picker.

### Information panels

Desktop: one resizable right-hand panel, switched between Data and Objects, closed by default. Opening shrinks the plot rather than covering the price axis. Persist selected panel and width only when persistence is enabled. Narrow displays: use a full-width sheet with a close control and focus management, preserving a usable chart when closed. Custom hosts can mount panel contents without adopting the widget shell.

The data window follows the local or linked crosshair and returns to the last bar when it leaves. Show the instrument, timestamp in the chart timezone, OHLC, volume, optional open interest and each study's named plot values. Readings must respect gaps, finite values, chart context changes and source formatting. Missing data is explicitly unavailable, never zero or silently carried forward. Values remain selectable and copyable. Detach observers on closure/destruction and coalesce frequent updates.

### Object organization

Group rows by pane. Keep existing search, selection, visibility, lock, settings, focus and deletion. Add explicit ordering and movement only through supported public APIs, with drag-and-drop and equivalent buttons for keyboard/touch. Indicator movement must preserve the same instance and owned visuals; no remove/re-add shortcut that loses IDs or alert references. Drawing groups have a name and stable membership, support select/hide/lock/remove together, survive save/restore and drop missing members. Do not expose a control whose action cannot be supported. Preserve custom provider behavior and existing records. A reordering control must actually change renderer stacking order, not just row order.

### Symbol search and typing

Provide one reusable picker for widget and reference host. Existing `SymbolSearch(query)` callbacks stay valid. Add optional asset class, icon and contract-group metadata to results, plus optional category filtering in the UI. Display symbol, description and exchange clearly. Futures roots expand to concrete contracts; grouping is supplied by the host rather than guessed. Never infer an exchange from a name. Cancel or ignore stale searches after a newer query, category change, close, context switch or destruction. Render user/provider strings as plain text and validate icon URLs.

Typing a letter on the focused chart opens symbol search with that character; typing a number opens a small interval entry. Only recognized intervals can be applied; show a readable validation message otherwise. Preserve existing shortcut precedence, editable targets, composition input and modifier chords. Two charts cannot both consume a key. A host can disable this convenience.

### Indicator picker

Keep searchable category groups and repeated additions. Add a running-studies section with one row per actual instance and independent removal. Duplicate instances must remain distinguishable. Update the list when the chart changes outside the picker; close must detach listeners. No fabricated descriptions or unsupported controls.

## Validation and release

Additional approved website scope: replace periodic sample prices with deterministic stock-like candles, put simple examples first, and give rich timeline events their own demo separate from linked volume analysis. Use full-width chart layouts and the OpenAlgo website's neutral theme. The website social preview uses a real screenshot of linked anchored VWAP and volume profiles with Open Graph and Twitter image metadata. Refine the first two homepage feature illustrations while preserving the third chart-style illustration.

Write behavioral regressions before implementation and observe them fail. Test pure contracts and lifecycle handling with unit tests. Test real built widget and yfinance interactions in Chromium, Firefox and WebKit, including desktop, narrow screens, keyboard, dark/light and two widgets. Inspect screenshots. Run the full verification, TypeDoc without warnings, public skills coverage and website build. Measure sizes on the final candidate, updating budgets only for explained additions. Validate the packed candidate in an isolated consumer. Update docs, changelog, website, API references and screenshots where useful. Commit, push, wait for CI, and use the established release workflow for npm provenance, GitHub release and Pages. Verify published files and deployed interactions.
