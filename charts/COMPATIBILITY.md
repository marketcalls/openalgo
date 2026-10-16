# Compatibility and maintenance

This page describes the public integration contract and release expectations.
It is not a service agreement or a guarantee of market-data or broker availability.
Security reports and supported fix branches follow [SECURITY.md](SECURITY.md).

## Public API and versions

Use the package's documented export entries and exported TypeScript declarations.
Deep imports into source files, generated bundle internals, underscored members,
demo globals and widget CSS/DOM structure are not stable extension points. The
widget owns its markup; hosts needing different chrome can use the headless APIs.
Descriptor hooks and registered extensions are public only where documented.

Within a major version, existing public options retain their defaults and new
features should be additive. Mark an API deprecated in its declaration and
documentation, provide the replacement and migration example, and keep the old
entry until the next major release. Numeric correctness, data ownership and
security fixes can change incorrect behavior within a patch; explain affected
inputs and the resulting behavior in release notes instead of silently preserving
a defect. Experimental or host-specific examples do not imply a permanent API.

A deprecated declaration carries a `@deprecated` tag, so editors strike the name
through and the API reference marks it. The tag names the release that removes
the API, which is the next major, and the replacement with the release it
arrived in:

```ts
/** @deprecated Removed in 3.0.0. Use {@link decodeOrder} (since 1.6.0). */
```

`npm run lint` enforces the tag in `src`, wherever the compiler reads one,
including the middle of a line. It fails a tag that names no removal release,
one whose removal falls inside the current major, and one outside a `/** */`
doc block, where neither the editor nor the reference reads it. It also
fails every tag whose removal release the package has reached, so a major
release cannot ship a deprecated API it promised to remove. The table under
[Deprecated APIs](#deprecated-apis) lists each deprecation, and a test keeps it
in step with the tags.

Saved chart, drawing, alert and workspace formats have their own version fields.
Do not rewrite them to the package version. Use their public validation/restore
APIs and inspect failures or partial-restore reports. Preserve the last good stored
document when a migration fails. Broker orders, positions, credentials and armed
state do not belong in portable layout files.

## Deprecated APIs

Each entry keeps working until the release in the "Removed in" column. The
`depth_level` wire key and the widget message keys have no declaration a tag can
sit on (a key the feed sends on the wire, and members of a string union), and an
event name reaches a host as a string, which an editor never strikes through, so
this table is where they are recorded.

| Deprecated | Declared in | Replacement since | Removed in | Use instead |
| --- | --- | --- | --- | --- |
| `mapOrder` | `src/feed/openalgo-trade.ts` | 1.6.0 | 3.0.0 | `decodeOrder`, which returns why a row could not be read, or `OpenAlgoTradeFeed.getOrderBook()`, which sets such rows aside as `quarantined` |
| `IndicatorHost.addIndicatorLevel` argument `level.dashed` | `src/model/indicator-instance.ts` | 1.7.1 | 3.0.0 | `level.lineStyle`, which a study always resolves and which also carries `'dotted'` |
| `depth_level` key in a depth subscribe frame | `src/feed/openalgo-ws.ts` (`formatSubscribe`), a wire key | 2.0.1 | 3.0.0 | `depth`, the key the OpenAlgo proxy reads, which is sent beside it today |
| Widget message key "Enter a valid expiry date and time in UTC" | `src/widget/localization.ts`, a union member | 2.4.6 | 3.0.0 | Nothing: the widget no longer shows it, so drop it from a translation catalog |
| Widget message keys "Dark" and "Light" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | Nothing: the theme button shows a sun or a moon, and its accessible name uses "Switch to the light theme" or "Switch to the dark theme", so drop them from a translation catalog |
| Widget message keys "Armed", "Keep tool armed", "On: the tool stays armed after each drawing", "Tools stay armed after each drawing", "{group}: chevron for the rest. Double-click keeps it armed" and "{name} stays armed until Escape" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | The same keys with "active" for "armed" ("Active", "Keep tool active" and so on), which the widget shows since 2.5.10; translate those instead |
| Widget message keys "{count} chart shortcut struck through: the same chord arms a drawing tool here and takes precedence." and "{count} chart shortcuts struck through: the same chord arms a drawing tool here and takes precedence." | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | The same keys ending "another shortcut uses the same chord here and takes precedence.", which the shortcuts panel shows since 2.5.10 |
| Widget message keys "Enter an expiry date and time in UTC", "Expires {time} UTC" and "Last fired {time} UTC" | `src/widget/localization.ts`, each a union member | 2.4.6 | 3.0.0 | The same keys without " UTC", which the alert editor and list show since 2.4.6, on the chart's own clock |
| Widget message key "Symbol search results" | `src/widget/localization.ts`, a union member | 2.5.3 | 3.0.0 | Nothing: the widget no longer shows it |
| Widget message keys "That side is already in use" and "other side taken" | `src/widget/localization.ts`, each a union member | 2.5.4 | 3.0.0 | Nothing: the widget no longer shows them |
| Widget message keys "Unlock drawing" and "Show drawing" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | "Lock drawing" and "Hide drawing": the rail keeps one name and its pressed state says locked or hidden |
| Widget message keys "Dark theme" and "Light theme" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | "Switch to the dark theme" and "Switch to the light theme", the words the top bar uses |
| Widget message key "Stay: {mode}" | `src/widget/localization.ts`, a union member | 2.5.10 | 3.0.0 | "Keep tool active: {mode}" |
| Widget message key "Edit on chart" | `src/widget/localization.ts`, a union member | 2.5.10 | 3.0.0 | "Edit text", as the right-click menu says |
| Widget message key "History is stale for {symbol} {interval}. Reload to retry." | `src/widget/localization.ts`, a union member | 2.5.10 | 3.0.0 | "History is stale for {symbol} {interval}", beside the Retry button |
| Widget message keys "Magnet weak: snaps when O/H/L/C is within a few pixels", "Magnet strong: every anchor lands on the nearest O/H/L/C", "Click for weak: snaps when O/H/L/C is within a few pixels" and "Click for strong: every anchor lands on the nearest O/H/L/C" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | The same keys with "a bar or study value" for "O/H/L/C", since the magnet snaps to study values too |
| Widget message keys "Ratio" and "Remove level" | `src/widget/localization.ts`, each a union member | 2.5.10 | 3.0.0 | "Level {level} ratio" and "Remove level {level}", which name the row |
| Widget message keys "From (UTC seconds)", "To (UTC seconds)" and "Enter finite UTC seconds or leave the bound blank" | `src/widget/localization.ts`, each a union member | 2.6.0 | 3.0.0 | "From", "To" and "Enter a date and a time on the chart clock": the chart data dialog asks for its bounds as a date and a time on the chart's clock |
| `ChartClickEvent` flags `shiftKey`, `ctrlKey` and `metaKey` | `src/core/chart.ts` | 2.0.0 | 3.0.0 | `modifiers.shift`, `modifiers.ctrl` and `modifiers.meta`, the same state, beside `alt` |
| `Chart.renderer` | `src/core/chart.ts` | 2.0.0 | 3.0.0 | `Chart.rendererKind`, the same value under its settled name |
| `Chart.movePriceAxis` | `src/core/chart.ts` | 2.5.4 | 3.0.0 | `Chart.setPriceAxisPlacement`, which moves the column and keeps the scale's id |
| `PriceAxisState.movable` | `src/core/chart.ts` | 2.5.4 | 3.0.0 | Nothing: `setPriceAxisPlacement` needs no such check |
| `priceAxisMoved` event | `src/core/chart-events.ts` (its `ChartEventMap` key; `movePriceAxis` in `src/core/chart.ts` alone emits it), an event name | 2.5.4 | 3.0.0 | `priceAxisPlacementChanged`, which `setPriceAxisPlacement` emits with the pane, the scale id and its new side |
| `Chart.on`, `Chart.once` and `Chart.off` given a name outside `ChartEventMap` (the `string` overload) | `src/core/chart.ts` | 2.6.0 | 3.0.0 | The same calls with a `ChartEventMap` name, which types the listener's payload; declare an event of your own by merging it into `ChartEventMap` |
| `TimeScaleOp`, `InvalidateMask.addTimeScaleOp` and `InvalidateMask.timeScaleOps` | `src/core/invalidate-mask.ts` | 2.5.8 | 3.0.0 | Nothing to queue: since 2.5.8 the frame reads no queued operation. Change the time scale directly with `chart.timeScale`, `chart.fitContent` or `chart.setVisibleLogicalRange` |
| `TradingController.updatePositionPnl` given the number first (`updatePositionPnl(id, unrealizedPnl, pnlText?, pnlPercent?)`) | `src/core/trading-controller.ts` | 2.6.0 | 3.0.0 | `updatePositionPnl(id, pnlText?, pnlPercent?)`, the same call without the number, which the pill never showed |
| `SeriesStyle.hollow` | `src/render/series-style.ts` | 1.0.2 | 3.0.0 | The `'hollow-candle'` series type, which draws up candles as outlines and down candles filled; the field itself never had an effect |
| `InvalidateMask.merge` | `src/core/invalidate-mask.ts` | 2.5.8 | 3.0.0 | Nothing: the chart raises one mask per frame, and a host raises levels on the mask `chart.invalidate` hands it |
| `Chart.emit` | `src/core/chart.ts` | 2.5.10 | 3.0.0 | `setDataContext` to announce an instrument, `LinkGroup.setSymbol`, `setInterval` and `setChartType` to drive a link group, and an emitter of your own for events of your own |
| `VolumeProfileOptions` | `src/profile/volume-profile.ts` | 1.0.1 | 3.0.0 | Nothing takes this type: pass `computeVolumeProfile(bars, tickSize, valueAreaPercent)` its arguments as before, or use `computeVolumeProfileSessions` with `VolumeProfileFamilyOptions` for an options object |
| `TradeFeed` | `src/feed/types.ts` | 1.0.0 | 3.0.0 | `OrderFeed` from `openalgo-charts/trade`, which `OrderEngine` writes through and `OpenAlgoTradeFeed` implements; nothing in the library ever called a `TradeFeed`, so hand the book to the chart with `chart.trading.syncState` |
| `PlaceOrder` | `src/feed/types.ts` | 1.0.0 | 3.0.0 | `PlaceRequest` from `openalgo-charts/trade`, the order `OrderEngine` and `OrderFeed.place` take |

Migration, for the five a host is most likely to hold:

```ts
// before
const order = mapOrder(raw);
// after: a row with no honest order form is reported, not disguised
const result = decodeOrder(raw);
if (result.ok) use(result.order); else report(result.issue);

// a custom IndicatorHost, before
addIndicatorLevel(level, pane) { draw(level.price, level.dashed ? 'dashed' : 'solid'); }
// after
addIndicatorLevel(level, pane) { draw(level.price, level.lineStyle); }

// a click handler, before
chart.on('click', (e) => { if (e.shiftKey || e.ctrlKey) addToSelection(e.id); });
// after
chart.on('click', (e) => { if (e.modifiers.shift || e.modifiers.ctrl) addToSelection(e.id); });

// an axis moved to the other strip, before: the scale's id became 'left'
if (chart.priceAxisState(0, 'right')?.movable) chart.movePriceAxis(0, 'right', 'left');
// after: the scale keeps the id 'right' and draws in the left column
chart.setPriceAxisPlacement(0, 'right', 'left');

// an event of the host's own, before: any string, an unknown payload
chart.on('myapp:signal', (p) => mark((p as { price: number }).price));
// after: declared once, then typed everywhere
declare module 'openalgo-charts' {
  interface ChartEventMap { 'myapp:signal': { price: number } }
}
chart.on('myapp:signal', ({ price }) => mark(price));
```

The host-emitted names a link group follows (`symbol`, `interval`,
`chartType`) are in `ChartEventMap` already. Until 3.0.0, `chart.emit` still
puts any of these on the bus.

### Kept on purpose

These older forms are supported, not deprecated, and no major is scheduled to
remove them:

- **The `dashed` shorthand** on `PriceLineOptions` and on an indicator level.
  `dashed: true` is `lineStyle: 'dashed'`, and `lineStyle` wins when both are
  set. It is the common case and the form the built-in study levels use.
- **`magnet: true | false`** on `DrawingController`, meaning `'strong'` and
  `'off'`. A boolean is the obvious form of an on/off magnet.
- **The IST helpers**: `IST_OFFSET_SECONDS`, `istStringToUtcSeconds`,
  `utcSecondsToIstParts`, `utcSecondsToIstDateString`, `formatIstTime`,
  `formatIstTimeSeconds`, `formatIstDate`, `formatIstCrosshairLabel`,
  `isNewIstDay` and the `IstParts` type, public since 1.x. IST is the shipped
  default zone and OpenAlgo's history API takes IST date strings, so these stay
  as the named form of that default. The zone-aware functions
  (`utcSecondsToZonedParts`, `formatZonedTime` and the rest) are the general
  form, for any IANA zone.
- **`levels(settings)` descriptors.** The context a study's `levels` hook
  receives spreads the settings onto itself beside `bars` and `values`, so a
  descriptor written against the original one-argument form still reads
  `ctx.overbought`. The built-in studies are written that way.
- **The `topic` field on an inbound market-data frame.** `parseMessage` reads
  the symbol and exchange from the frame first and falls back to `topic`, the
  form an older proxy sends. A reader of a wire format stays while a server can
  still send it.
- **The `draw:*` events beside `drawing:*`.** They are two granularities of one
  model, not an old and a new form. `draw:add`, `draw:update` and `draw:remove`
  fire once per drawing and carry it; `drawing:change` fires once per mutation,
  after them, and lists the ids. `draw:select` names the primary selection and
  `drawing:select` the whole of it; both fire together, only when the selection
  changed. A host showing one drawing's properties listens to the first family,
  one refreshing a list or an undo control to the second.
- **The event names that predate the naming rule.** New names are
  `namespace:action`, lower case, hyphen-joined, in the present tense. The
  camelCase pane and indicator events, the single words, the snake case of
  `trading:*` and the past tense of `branding:changed`, `timezone:changed`,
  `alerts:changed` and `alerts:restored` keep their spelling: a rename breaks
  every listener on the old name, and the names cost nothing as they are.
- **Readers of older saved documents**: a 1.9.x drawings array given to
  `fromJSON` or `migrateDrawings`, a version 1 clipboard body, an unversioned
  alert list, a cache entry without a version and a partial pane state. A
  reader stays as long as such a document can still be in someone's storage,
  and follows the document's own version field rather than the package version.

### Not decided yet

- **What the tiers' structural hosts require once `Chart.emit` goes.**
  `AlertChartHost`, `ReplayChartHost`, `DrawingChartHost`, `PickHost`,
  `TradingHost` and `IndicatorHost` each name `emit(event: string, payload:
  unknown)`, which a `Chart` satisfies with the deprecated method. They keep that
  member through 2.x. 3.0.0 changes it, to a member typed by `ChartEventMap` or
  to a dispatch the base exports for its tiers, and a host that implements one
  of them for an object that is not a `Chart` will change with it.

### Planned for 3.0.0

- **Visibility option names.** A switch that shows or hides part of the chart
  is named two ways: `xVisible` in the style bags that mirror a series property
  (`bodyVisible`, `wickVisible`, `borderVisible`, `priceLineVisible`,
  `lastValueVisible`, a primitive's `lineVisible`) and `showX` in the profile
  primitives (`showPoc`, `showValueArea`, `showLastPrice`, the footprint's
  `showCandle`) and in `PaneOptions` (`showTimeAxis`, `showVertGrid`). Both
  forms are public and saved in chart settings, so 2.x renames neither. Until
  3.0.0 settles on one, with the other kept as a deprecated alias, a new option
  follows its neighbours: `xVisible` in a style bag that mirrors a series
  property, `showX` on a primitive or profile toggle.

## Runtime boundary

The published package is ESM, with a script-tag build of every tier for a page
that loads no modules, and no runtime dependencies. The script-tag build is one
`OpenAlgoCharts` global with a key per tier; the global's name, its tier keys and
the names under them are public in the same way as the export entries they mirror,
and `npm run check:exports` holds them to the declarations.

There is no CommonJS build: a second copy of the code would carry a second set of
registries. Each export's `default` condition resolves `require()` to the same ESM
file instead, so Node.js 20.19 or later and 22.12 or later return from `require()` the
module `import` returns. Earlier Node.js versions throw `ERR_REQUIRE_ESM` and load the
package with `import()`. The build toolchain requires Node.js 20 or later, as declared in
`package.json`. Construct charts only where the required browser canvas/DOM APIs
exist; rendering on a server needs a host-owned environment and is not implied by
successful server-side module resolution.

Browser regression projects exercise Chromium, Firefox and WebKit. Record actual
versions, operating system, viewport, device-pixel ratio and rendering backend with
release evidence. WebKit automation does not prove every Safari/device combination.
Canvas2D is the general rendering path; the WebGL2 tier draws the standard series
types on the GPU, with the documented fallback. Its frame time has not been
measured against Canvas2D. Clipboard, fullscreen and downloads also depend
on browser permissions and embedding policy. Surface those failures to the user.

## Host and adapter responsibility

The host supplies authenticated transport, current instrument/session metadata,
provider timestamp conversion, symbol resolution, supported intervals, cancellation
and persistence namespaces. Read [instrument rules](docs/instruments.md),
[adapter conformance](docs/adapter-conformance.md) and the integration API reference.
OI capability is separate from a missing or zero reading. Alert evaluation happens
in the chart; durable background scheduling and notification delivery belong to
the host. A closed browser is not a server-side alert service.

Broker state remains authoritative for execution, risk and permissions. Chart
capability checks and quantity validation improve interaction but do not replace
server enforcement. Reconcile ambiguous results with the broker rather than
assuming a rejected network request means no order exists. Replay and selection
must lock every host order-entry route, including controls outside the chart.

## Upgrade and release evidence

Pin the version used by a financial portal. Test an upgrade in its real host before
rolling it out: source changes and reconnects, layout migration, multiple panes,
drawings/studies, replay, OI gaps and all enabled trading routes. Keep the prior
application deployment available for rollback; never replace an immutable package
version with different files. Downgrading does not guarantee that newer saved
documents can be read by an older host.

Every release is checked against the previous release and the version OpenAlgo
pins, before it is tagged: `npm run check:compat` fails a public name removed or a
type narrowed in any tier unless the table under [Deprecated APIs](#deprecated-apis)
lists it for the next major, and `tests/saved-documents.test.ts` loads the chart
states, drawings, widget layouts, workspaces and alert lists those releases saved and
saves them again, naming every field that changes. [CONTRIBUTING.md](CONTRIBUTING.md)
describes both.

Release evidence separates unit tests, deterministic adapter/browser fixtures,
endurance workloads and connected-provider observations. A synthetic feed passing
conformance is not a broker certification. Report the workload and machine for
performance results, and retain failing reports alongside corrected runs. See
[browser endurance](docs/browser-endurance.md) for reproducible measurements.

Prepare release notes, migration guidance, measured package facts, generated API
docs and the website before publishing. Publish the verified immutable tag through
the release workflow, verify npm provenance and package contents, and check the
deployed website independently. [CONTRIBUTING.md](CONTRIBUTING.md) lists the gates.

## Reporting and support

For ordinary defects, open a repository issue with package and host versions,
browser/OS, affected public API, expected/actual behavior and a minimal synthetic
reproduction. Include sanitized logs or screenshots when useful. Report security
issues through the private channel in the security policy. Do not attach account
credentials or private order history to a public issue.

Community maintenance does not promise continuous exchange coverage, a response
SLA, compatibility with every embedding framework or indefinite support for older
minor versions. Provider changes and production operations remain responsibilities
of the adopting host. Any additional support arrangement must be agreed separately.
