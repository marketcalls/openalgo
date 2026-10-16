# Bundling and tiers

*When to read this: picking an import specifier, loading the package from a plain HTML page, debugging a "type is not registered" error, or checking a size budget.*

Source of truth: `package.json` (`exports`, `sideEffects`, `files`), `rollup.config.js`, `.size-limit.json`, `src/all.ts`, `scripts/check-exports.mjs`.

## The nine entry points

`exports` declares exactly nine specifiers, each with `types`, `import` and `default` conditions, where `default` names the same `.mjs` file as `import`. There is no `main` and no CommonJS build: the package is ESM (`"type": "module"`, `module: dist/openalgo-charts.mjs`).

**No CommonJS build, and `require()` gets the ESM files.** A CommonJS copy of the code would carry a second set of registries, so a descriptor registered through one copy would be unknown to a chart created by the other (the same failure as a deep import, below). The `default` condition points `require()` at the ESM files themselves instead:

- Node 20.19 or later, 22.12 or later, and every later release line load them synchronously: `require('openalgo-charts')` and `require('openalgo-charts/indicators')` return the very modules `import` returns, one registry between them.
- An older Node throws `ERR_REQUIRE_ESM`, whose message says to use `import()`. A CommonJS module can always do that: `const { createChart } = await import('openalgo-charts');`.
- TypeScript compiling to CommonJS accepts the `require` from 5.8, with `module: "nodenext"`. A test runner working in CommonJS mode has to load this package as ESM (its ESM mode, or a transform for it).

`npm run check:exports` (in `verify`, after the build) requires every specifier under the running Node and fails if `require()` and `import` disagree.

| Specifier | Emitted file | Contents | Brotli measured / limit | Import has side effects |
|---|---|---|---|---|
| `openalgo-charts` | `dist/openalgo-charts.mjs` | engine, 13 chart types, indicator + chart-type registries, primitives, feeds, trading controller, shortcuts, TimeNavigator, `ReplayController`, comparison controller, appearance links, grouped timeline events, settings schema, chart timezone | 137.65 kB / 137.65 kB | no |
| `openalgo-charts/trade` | `dist/openalgo-charts.trade.mjs` | order/position/bracket primitives, DOM ladder, `OrderEngine`, `TradeController`, `FakeBroker` | 16.88 kB standalone; 154.53 kB limit for base + trade | no |
| `openalgo-charts/transform` | `dist/openalgo-charts.transform.mjs` | Renko, Range, Point & Figure, Kagi, Line Break, Heikin Ashi, `runTransform`, symbol arithmetic (`parseExpression`, `evaluateExpression`) | 6.23 kB / 6.23 kB | **yes**, registers the `point-figure` and `kagi` chart types and the six series transforms |
| `openalgo-charts/profile` | `dist/openalgo-charts.profile.mjs` | Volume Profile, TPO / Market Profile, Footprint, orderflow | 20.83 kB / 20.83 kB | no |
| `openalgo-charts/indicators` | `dist/openalgo-charts.indicators.mjs` | 112 Tier-1 built-ins plus the Tier-2 contract | 43.02 kB / 43.02 kB | **yes**, registers all 112 descriptors |
| `openalgo-charts/draw` | `dist/openalgo-charts.draw.mjs` | 87 drawing tools including Anchored VWAP and fixed-range Volume Profile, `DrawingController`, `DrawingLinkGroup`, `DrawingLayer` | 58.44 kB / 58.45 kB | **yes**, registers every built-in tool |
| `openalgo-charts/webgl` | `dist/openalgo-charts.webgl.mjs` | the WebGL2 series backend, `createWebGL2Backend`, `isWebGL2Supported`, `WebGL2Backend`, `GlDevice` | 6.97 kB / 6.97 kB | **yes**, registers the `webgl2` render backend |
| `openalgo-charts/widget` | `dist/openalgo-charts.widget.mjs` | `createWidget`, the chrome (top bar, rail, status line, toasts), the dialogs, event details, the keymap, the tokens and stylesheet; the only tier that ships DOM. Imports `openalgo-charts/draw` itself | 124.94 kB / 124.94 kB; first-use parts 21.00 kB / 21.00 kB | **yes**, registers the seven dialog mounts with the shell |
| `openalgo-charts/workspace` | `dist/openalgo-charts.workspace.mjs` | Validated workspace and template documents, `WorkspaceRepository`, revision conflicts and an IndexedDB adapter | 11.73 kB / 11.73 kB | no |

Types resolve per tier: `dist/index.d.ts`, `dist/trade/index.d.ts`, `dist/transform/index.d.ts`, `dist/profile/index.d.ts`, `dist/indicators/index.d.ts`, `dist/draw/index.d.ts`, `dist/webgl/index.d.ts`, `dist/widget/index.d.ts`, `dist/workspace/index.d.ts`.

## Never deep-import into `dist/`

**Import the bare specifier or a declared subpath. Never `openalgo-charts/dist/openalgo-charts.mjs`, never a relative path into `node_modules`, never a tier's internal module.**

The reason is registry identity, and it is a correctness bug, not a size problem. `rollup.config.js` builds each tier as its own bundle with the base marked external, so a tier's runtime imports of shared state survive as a real import rather than being inlined:

```js
const PKG = 'openalgo-charts';
const tierExternal = (id) => id === PKG || id.startsWith(`${PKG}/`);
```

Every `openalgo-charts/<tier>` specifier is external too, and `output.paths` maps each to its sibling file, because the widget tier builds on the draw tier and would otherwise inline a second `DrawingController`.

Every registry (chart types, indicators, drawing tools) is a module-level `Map` inside exactly one module instance. `createChart` reads the base bundle's copy. A deep import creates a second module instance with a second, empty `Map`:

- `import 'openalgo-charts/dist/openalgo-charts.indicators.mjs'` alongside `import { createChart } from 'openalgo-charts'` in a bundler that resolves the two to different graph nodes registers 112 descriptors into a Map nobody reads. `chart.addIndicator('macd')` then throws as if the tier were never loaded.
- The same failure for `openalgo-charts/transform` shows up as `series type "point-figure" needs the transform tier, import 'openalgo-charts/transform' first`, on a page that plainly did import it.
- For `openalgo-charts/draw` you get two `DrawingController` classes and two tool tables; `instanceof` checks and tool ids stop lining up across them.

Node and any bundler honouring `exports` will refuse a deep specifier outright, which is the good outcome. The failure mode appears when a bundler is configured to ignore `exports`, when a monorepo alias points at `dist/`, or when someone hand-writes a relative path.

`src/transform/index.ts`, `src/indicators/index.ts` and `src/draw/index.ts` all carry this rule in their header comments. Follow it in tier code too: import shared runtime values from `'openalgo-charts'`, never `'../index'` by path.

## What the tier bundles actually import

`npm run shake` checks this list against the built output (`TIER_IMPORTS` in `scripts/check-shake.mjs`), so a tier that starts or stops importing the base fails the build until this page says so:

- `dist/openalgo-charts.indicators.mjs`, `.transform.mjs`, `.trade.mjs`, `.draw.mjs`, `.webgl.mjs` and `.workspace.mjs` import from `"./openalgo-charts.mjs"`, a **relative** specifier, not the bare package name. Rollup rewrites it via `output.paths: { 'openalgo-charts': './openalgo-charts.mjs' }`. The draw tier takes the interval resolver and the indicator registry from the base at run time, so it cannot be loaded without it. The widget imports `./openalgo-charts.mjs` and `./openalgo-charts.draw.mjs`, and its parts that load on first use (`openalgo-charts.widget.<part>-<hash>.mjs`) import the same two, the widget file and, where they share code, each other.
- `dist/openalgo-charts.profile.mjs` emits no base import at all: it takes only *types* from `openalgo-charts`, which erase at compile time. The base `dist/openalgo-charts.mjs` imports nothing.

**Serving `dist/` directly over HTTP works with no import map.** A `<script type="module">` that loads `/dist/openalgo-charts.indicators.mjs` resolves `./openalgo-charts.mjs` as a sibling URL. Every example in `examples/` relies on this; none declares an import map. The `.d.ts` builds keep the bare specifier, which TypeScript resolves through `exports`.

## sideEffects and tree-shaking

```json
"sideEffects": [
  "**/transform/**", "**/indicators/**", "**/draw/**", "**/webgl/**", "**/widget/**",
  "./dist/openalgo-charts.transform.mjs",
  "./dist/openalgo-charts.indicators.mjs",
  "./dist/openalgo-charts.draw.mjs",
  "./dist/openalgo-charts.webgl.mjs",
  "./dist/openalgo-charts.widget.mjs"
]
```

An array, not `false`: the base, trade, profile and workspace bundles are declared side-effect-free and tree-shake normally; the five registering tiers are marked as having side effects so a bare `import 'openalgo-charts/indicators'` (or `'openalgo-charts/webgl'`, or the widget, whose import registers its dialogs) is never dropped.

Tree-shaking will remove unused named exports from any tier. It will **not** remove a registration that a bundler can see is reachable, the registration runs at module scope in the tier's `index.ts`.

If a bundler still eliminates a bare side-effect import (an aggressive config, an older `sideEffects` implementation, a re-export barrel that loses the marking), call the registrar explicitly. All three are idempotent and exported for exactly this case:

```ts
import { registerBuiltinIndicators } from 'openalgo-charts/indicators';
import { registerBuiltinDrawingTools } from 'openalgo-charts/draw';
import { registerTransformChartTypes } from 'openalgo-charts/transform';

registerBuiltinIndicators();
registerBuiltinDrawingTools();
registerTransformChartTypes();
```

**A named import from a tier already runs its registration.** `import { RenkoTransform } from 'openalgo-charts/transform'` executes the module, so P&F and Kagi are registered too. The explicit call is only for the bare-import case.

## Loading shapes

**Bundler (Vite, webpack, Rollup, Next.js), bare specifier.**

```ts
import { createChart } from 'openalgo-charts';
import 'openalgo-charts/indicators';
import { DrawingController } from 'openalgo-charts/draw';
```

Lazy-load a tier the user may never touch:

```ts
const { DrawingController } = await import('openalgo-charts/draw');
```

**Plain `<script>`, the script-tag build.** Every tier also ships as a classic script (`format: 'iife'`) that needs no module support. `dist/openalgo-charts.standalone.js` is the base, built with `name: 'OpenAlgoCharts'` and nothing external; it defines the `window.OpenAlgoCharts` global. Each tier's `dist/openalgo-charts.<tier>.standalone.js` adds itself to that global under the tier's name, so `import { X } from 'openalgo-charts/draw'` becomes `OpenAlgoCharts.draw.X`:

```html
<script src="/dist/openalgo-charts.standalone.js"></script>
<script src="/dist/openalgo-charts.indicators.standalone.js"></script>
<script src="/dist/openalgo-charts.draw.standalone.js"></script>
<script src="/dist/openalgo-charts.widget.standalone.js"></script>
<script>
  const chart = OpenAlgoCharts.createChart(document.getElementById('chart'));
  chart.addSeries('candlestick').setData(bars);
  chart.addIndicator('rsi');                                     // registered by the indicators file
  const draw = new OpenAlgoCharts.draw.DrawingController(chart);
  const widget = OpenAlgoCharts.widget.createWidget(document.getElementById('terminal'), { feed, symbol: 'INFY', exchange: 'NSE', interval: '5m' });
</script>
```

The rules of the script-tag build:

- **One base, shared.** A tier file leaves the base (and, for the widget, the draw tier) external exactly as its `.mjs` does, and reads them from the global, so it registers into the base the page loaded. Never load a tier's `.mjs` beside the classic base: that module imports its own base, with its own registries.
- **Order.** The base first, then any tier, with the draw tier before the widget. A tier file loaded too early throws before it runs, naming the files to load first: `openalgo-charts.widget.standalone.js needs openalgo-charts.standalone.js and openalgo-charts.draw.standalone.js loaded before it`. Load each file once.
- **A key per tier, not one flat object.** The base and the widget both export a `withAlpha`, with different code; `OpenAlgoCharts.withAlpha` and `OpenAlgoCharts.widget.withAlpha` keep both. Each key holds exactly the runtime exports of that tier's `.d.ts`, which `npm run check:exports` enforces after every build.
- **The widget's file carries its first-use parts.** A classic script cannot share a split chunk, and a part fetched as a module would bring the ESM base with it, so the script-tag widget bundles the shortcuts editor, the Layouts menu and the rest into its one file and fetches nothing more. It is correspondingly larger than `openalgo-charts.widget.mjs`.
- The `unpkg` and `jsdelivr` fields still name the base file, so the bare CDN URL serves what it always did.

Prefer native ESM where the page allows it: modules fetch the widget's parts only when used, and a bundler drops what the page never imports.

**Native ESM, concrete `.mjs` URLs.**

```html
<script type="module">
  import { createChart } from '/dist/openalgo-charts.mjs';
  import '/dist/openalgo-charts.indicators.mjs';
</script>
```

**A bare specifier does not resolve in a browser.** `import { createChart } from 'openalgo-charts'` in a `<script type="module">` is a resolution error: the browser has no `node_modules` lookup and no `exports` map. Either use a path/URL, or declare an import map:

```html
<script type="importmap">
{ "imports": { "openalgo-charts": "/dist/openalgo-charts.mjs" } }
</script>
```

An import map is optional here. Because the tier bundles reference `./openalgo-charts.mjs` relatively, serving `dist/` unmodified is enough.

## Size budgets

Enforced by `npm run size` (`size-limit`, Brotli, `@size-limit/file`), from `.size-limit.json`. Current measurements are from 2.6.3 and use decimal kB:

| Budget row | Files measured | Limit | Measured |
|---|---|---|---|
| Base engine | `openalgo-charts.mjs` | 137.65 kB | 137.65 kB |
| Base + trade layer | base + `trade.mjs` | 154.53 kB | 154.52 kB |
| Indicator tier | `indicators.mjs` | 43.02 kB | 43.02 kB |
| Draw tier | `draw.mjs` | 58.45 kB | 58.44 kB |
| Transform tier | `transform.mjs` | 6.23 kB | 6.23 kB |
| Profile tier | `profile.mjs` | 20.83 kB | 20.83 kB |
| WebGL2 tier | `webgl.mjs` | 6.97 kB | 6.97 kB |
| Widget tier | `widget.mjs` | 124.94 kB | 124.94 kB |
| Widget first-use parts | `widget.<part>-<hash>.mjs`, eight files | 21.00 kB | 21.00 kB |
| Widget terminal | base + `draw.mjs` + `indicators.mjs` + `widget.mjs` | 364.05 kB | 364.04 kB |
| Workspace tier | `workspace.mjs` | 11.73 kB | 11.73 kB |
| Everything | all nine bundles | 426.67 kB | 426.67 kB |
| Script tags | the nine classic-script files | 440.43 kB | 440.43 kB |
| Base classic script | `openalgo-charts.standalone.js` | 137.69 kB | 137.69 kB |
| Widget classic script | `openalgo-charts.widget.standalone.js`, first-use parts inlined | 138.54 kB | 138.53 kB |

Version 2.1.2 raises the full-package budget from 187 KB to 188 KB for the feed, indicator lifecycle and recovery fixes. Version 2.1.3 raises base, widget and widget-terminal ceilings to 68 KB, 37 KB and 157 KB for navigation controls, and the chart-only tree-shaking ceiling to 45 KiB. Version 2.1.6 raises the base, base-plus-trade, widget-terminal and total ceilings
to 73 KB, 81 KB, 165 KB and 197 KB for shared loading, resilient caching and
managed study status. Aggregate rows constrain the total independently of individual tier ceilings. The limits in `.size-limit.json` are the budget of record.

Version 2.1.7 budgets the shared object inventory and compact Objects panel at
74 KB base, 82 KB base plus trade, 40 KB widget, 168 KB widget terminal and 200 KB
for all tiers. The chart-only import keeps its 45 kB tree-shaking ceiling.

Version 2.1.8 budgets normalized gestures and touch controls at 75 KB base,
83 KB base plus trade, 42 KB widget, 170 KB widget terminal and 202 KB total.
The chart-only tree-shaking ceiling is 46 KiB; widget controls remain excluded.

**Nothing is excluded from these numbers.** The package has zero runtime dependencies (`dependencies` is absent; everything in `devDependencies` is build tooling), so the measured file *is* the shipped payload. There is no CSS to import, no peer dependency, no web-component registration.

`npm run verify` runs lint, typecheck, the import-cycle and unused-export gates, unit tests, endurance-harness tests, build, demo tests, declaration checks, the export checks (script-tag keys and `require()`), size budgets and tree shaking, and is the `prepublishOnly` hook.

## `src/all.ts` is not an entry point

`src/all.ts` re-exports the base plus transform, profile, indicators, draw, webgl and workspace into one module, built by the `allBundle` config with the `aliasSelf` plugin resolving `openalgo-charts` back to `src/index.ts`. Nothing is external, so every tier shares one registry instance.

It exists so the documentation site's live demos can run every tier from a single module. It is **not** published: `files` excludes it explicitly.

```json
"files": ["dist/**", "!dist/openalgo-charts.all.mjs", "!dist/openalgo-charts.all.mjs.map", "NOTICE"]
```

It has no `.d.ts` build and no `exports` entry. `openalgo-charts/all` does not resolve. Applications import the tiers they use. The trade tier is deliberately left out of the combined bundle because it shares type names with the base feed types.

## Related

[core-api](core-api.md) · [chart-types](chart-types.md) · [indicators](indicators.md) · [transforms](transforms.md) · [drawing-tools](drawing-tools.md) · [trade-tier](trade-tier.md) · [profiles-and-orderflow](profiles-and-orderflow.md) · [widget](widget.md) · [react-integration](react-integration.md) · [pitfalls](pitfalls.md)

## Tier identity constants

The registering and engine feature tiers export string constants naming themselves, so feature detection does
not depend on a bare string literal that a rename would silently break:

| Export | Value | From |
|---|---|---|
| `INDICATORS_TIER` | `'indicators'` | `openalgo-charts/indicators` |
| `DRAW_TIER` | `'draw'` | `openalgo-charts/draw` |
| `TRANSFORM_TIER` | `'transform'` | `openalgo-charts/transform` |
| `PROFILE_TIER` | `'profile'` | `openalgo-charts/profile` |
| `TRADE_TIER` | `'trade'` | `openalgo-charts/trade` |
| `WEBGL_TIER` | `'webgl'` | `openalgo-charts/webgl` |
| `WIDGET_TIER` | `'widget'` | `openalgo-charts/widget` |

Workspace instead exports `WORKSPACE_VERSION`, the document schema version, not a tier identity constant.

The tier constants are exported from each tier's own entry point, not from the base bundle, so
importing one to test for it defeats the purpose. Track what your own code loaded.

The 2.1.9 branding and optional watermark change uses 77 KB base, 85 KB
base plus trade, 173 KB widget terminal and 205 KB total budgets. The chart-only
import is 48.96 KiB (45.51 KiB in 2.1.8), with a 50 KiB ceiling for bundled vector
artwork, watermark settings and guarded logo input. The widget stays below 42 KB.

Version 2.2.0 adds 34 drawing tools, their geometry and labels, and complete host
rail coverage. The measured draw-tier increase over 2.1.9 is about 8.6 KB Brotli;
base-only hosts do not load it. The budgets are 36 KB draw, 43 KB widget,
183 KB widget terminal and 215 KB total. Other tier budgets remain unchanged.

Version 2.3.0 raises the transform budget from 5 KB to 6 KB for symbol arithmetic
and the total from 215 KB to 218 KB. Version 2.3.1 changes no budget; the base
engine and the three rows that include it move by hundredths. Version 2.3.2
raises the base budget from 77 KB to 78 KB and base + trade from 85 KB to
86 KB for stream-driven repair and provisional bars.

Version 2.4.0 raises the base budget from 78 KB to 79 KB (78.07 KB measured)
for the indicator recompute guard, the per-bar wick and border colour, the bar
offset, two marker glyphs and two edge positions, the drawing hit layer and the
bars-provider threading, and the widget terminal from 183 KB to 185 KB
(184.14 KB measured). The indicator tier grows to 29.05 KB for `securitySeries`
and the Tier-2 combiner, within its unchanged 30 KB budget. Every other budget
is unchanged.

Version 2.4.5 ships `openalgo-charts/workspace` as a non-registering tier.
Base-only and widget imports do not include workspace persistence. The current
measurements and budgets are listed above. The chart-only import measures
52.34 KiB against a 52.50 KiB tree-shaking ceiling (binary units). See [workspaces](workspaces.md) for the
storage contract.

Version 2.4.6 adds source actions, configurable legend controls and marker
anchor/scale corrections to the base engine. Compared with 2.4.5, measured base
Brotli grows from 91.00 to 91.55 kB and the chart-only import from 52.34 to
52.75 KiB; their ceilings are 92 kB and 53 KiB. Shared form metrics and chart-zone
expiry handling grow the widget from 48.30 to 49.00 kB. The widget terminal is
205.83 kB and all tiers total 245.21 kB. Their budgets are 49.25 kB widget,
206 kB terminal and 245.5 kB total. Other tier ceilings remain unchanged, and
optional tiers still must shake out of a chart-only import.

Version 2.4.7 adds owned alert drafts, guarded commits, scale-aware previews and
primitive start/cancel notifications. Measured base Brotli grows from 91.55 to
92.83 kB (1.28 kB), with a 93.5 kB ceiling. Base plus trade is 100.84 kB against
101.5 kB. The widget measures 49.03 kB within its unchanged 49.25 kB ceiling;
the terminal is 207.13 kB and all tiers are 246.52 kB, with ceilings of
207.75 kB and 247.25 kB. Core gesture support increases the chart-only import
from 52.75 to 53.00 KiB, with a 53.25 KiB ceiling. The alert controller and
all optional tiers still must disappear from a chart-only import.

Version 2.5.0 adds source-tick alert snapping, keyboard ownership and automatic
column measurement with cell clipping. Base Brotli is 93.45 kB with a 93.75 kB
ceiling; base plus trade is 101.46 kB with a 101.75 kB ceiling. The widget remains
within 49.25 kB at 49.06 kB. The terminal is 207.78 kB and all tiers total
247.17 kB, with ceilings of 208.25 kB and 247.75 kB. Table measurement and
clipping remain in the chart-only import: 53.36 KiB with a 53.5 KiB ceiling.
The alert controller and optional tiers must still disappear from that import.

Version 2.5.2 adds the grouped timeline-event contract and appearance-link
adapters to base; analysis-drawing math and drawing links stay in the draw tier,
and event details stay in the widget. Measured all-tier Brotli grows from
247.32 kB in 2.5.1 to 256.08 kB. The ceilings are 95.5 kB base,
103.5 kB base plus trade, 41 kB draw, 51.5 kB widget, 217 kB widget terminal
and 256.75 kB for all tiers. The chart-only import measures 54.67 KiB against
a 55 KiB ceiling. Optional tiers still shake out of that import, and the package
continues to have zero runtime dependencies.

Version 2.5.3 adds stable study movement and ordering, object groups and a shared crosshair readout in the engine, plus a Data/Objects dock, richer instrument search and compact colour controls in the optional widget. The measured base is 96.54 kB and the widget is 59.22 kB. Budgets are 97 kB base, 105.1 kB base plus trade, 42 kB draw, 60.5 kB widget, 229 kB terminal and 269 kB for all tiers. Widget controls remain excluded from base-only imports.

The 2.5.3 chart-only import measures 55.58 KiB, compared with 54.67 KiB at the 2.5.2 source commit. Stable study movement/order, provider capabilities and shared readout events add 0.91 KiB. The ceiling is 55.75 KiB; optional UI, adapters and controllers are still checked as absent.

Version 2.5.4 adds pane collapse, study output targets and drawing policies to the engine, go-to-date navigation (`DateNavigator` and its panel) and `createChartGrid` to the widget, together with CSV study export, navigation policies, typed study inputs, styled study text, smooth polylines, table cell details, primary-only fit and collapsible study legends. The measured base is 117.42 kB, the widget 71.33 kB and all tiers 310.09 kB. Budgets are 117.42 kB base, 125.43 kB base plus trade, 42.53 kB draw, 71.34 kB widget, 267.56 kB terminal and 310.09 kB for all tiers. The chart-only import measures 74.43 KiB under a 74.44 KiB ceiling; the grid, the go-to panel and every optional controller are still checked as absent from it.

Version 2.5.5 adds an opt-in movable price pane and the indicator gap recovery to the engine, viewport-pinned drawings to the draw tier, account state, order preview, durations and native position commands plus price tick schedules to the trade tier, named watchlists to the workspace tier, and Watchlist, News and account panels to the widget. The trade tier roughly doubles (8.01 to 16.64 kB standalone), which only a host that imports it pays. The measured base is 119.15 kB, the widget 82.30 kB and all tiers 335.15 kB; the chart-only import measures 75.07 KiB under a 75.08 KiB ceiling, and the widget tier, which holds the new panels, is still checked as absent from it.

Version 2.5.6 adds study policies, one draw order per pane, paired time and price inputs, background targets, conditional inputs, data variants, the session calendar and device-pixel pane layout to the engine, and the chart-wide undo timeline (`ChartHistory`) to the widget. The measured base is 125.39 kB, base plus trade 142.07 kB, trade alone 16.69 kB, indicators 36.44 kB, draw 48.42 kB, the widget 92.72 kB, the terminal 302.96 kB, the workspace tier 10.47 kB and all tiers 355.97 kB. The chart-only import measures 79.25 KiB (81148 bytes) under a 79.25 KiB ceiling: study policies, the draw order, device-pixel layout, resize paints, the session calendar, the layout event and the alert scope parser belong to every chart, while the undo history, the panels and forms, and the alert and loading controllers still shake out.

Version 2.5.7 is internal: the chart's logic moves out of `chart.ts` into collaborator modules behind the unchanged `Chart` class, with the same API and the same pixels. The measured base is 126.91 kB, base plus trade 143.60 kB, the terminal 304.49 kB and all tiers 357.50 kB; the trade, indicator, draw, widget and workspace tiers are unchanged. The chart-only import measures 80.87 KiB (82809 bytes) under an 80.87 KiB ceiling: the collaborators are part of every chart, and the optional controllers and the widget still shake out.

Version 2.5.8 is the rendering release: the level of detail on by default, frames that do not allocate per bar, a hit-test prefilter, plots written in place on a tick, pane-scoped repaints, glides inside the render loop, and a `calcTail` on sixteen built-ins. The measured base is 130.37 kB, base plus trade 147.06 kB, indicators 40.38 kB (the tails), the terminal 311.90 kB and all tiers 364.91 kB; the trade, draw, widget, workspace, transform, profile and WebGL2 tiers are unchanged. The chart-only import measures 83.87 KiB (85883 bytes) under an 83.88 KiB ceiling: all of the rendering work runs on every chart, and the optional controllers and the widget still shake out.

Version 2.5.9 is the drawing interaction and replay release: drawings per instrument, the drawing gestures, visibility per interval, the widget's drawing toolbar, templates and coordinates tab, replay's forming rule and simulated forming, lines across the edges of the view and the price axis fixes. The measured base is 131.68 kB, base plus trade 148.36 kB, draw 55.61 kB (the gestures, visibility per interval and the hit index), widget 99.64 kB (the toolbar, templates and coordinates tab), workspace 11.33 kB (the template catalog), the terminal 327.32 kB and all tiers 381.78 kB. The chart-only import measures 84.82 KiB: the edge-segment and axis work runs on every chart, and the drawing gestures, the widget UI and replay's simulated forming shake out.

Version 2.5.10 is the persistence, saved layouts and chart grid release: widget state in IndexedDB, saved layouts and indicator templates, the shortcuts editor, the bottom bar, market phases and session shading, the chart grid to sixteen charts with named link groups, link channels for the chart type and drawings, the chrome icon registry, marker lanes and the label pass. The measured base is 134.69 kB, base plus trade 151.38 kB, indicators 40.43 kB, draw 57.98 kB (the icon registry), profile 14.97 kB, widget 121.36 kB, workspace 11.53 kB (named link groups), the terminal 354.46 kB and all tiers 409.13 kB; the transform, WebGL2 and trade tiers are unchanged. The widget loads the UI a plain widget never opens from seven part files beside it, named by a content hash (`openalgo-charts.widget.<part>-<hash>.mjs`, 18.19 kB together), which a bundler emits as chunks of their own and a host serving `dist/` serves with the tier file from the same release. The chart-only import measures 85.73 KiB: the marker lanes run on every chart with text markers, and the session phases, the shading and the link channels shake out.

Version 2.6.0 is the analysis depth and stricter API release: transforms applied in the chart with studies on the underlying bars, seven built-ins and a timeframe input on 29 of them, symbol search through the OpenAlgo feed, rich event details, the typed event map, a classic script for every tier and `require()` of the ESM files. The measured base is 137.53 kB, base plus trade 154.41 kB, indicators 43.02 kB, transform 6.07 kB, widget 123.57 kB, the terminal 362.48 kB, all tiers 419.05 kB and the nine classic scripts 430.90 kB; the eight tier scripts ship without source maps. The transform runs are installed by `registerSeriesTransform`, so a chart-only import that registers none leaves them out; it measures 87.19 KiB.

Version 2.6.1 adds order flow analytics for the footprint (trade classification, a trade size filter, imbalance and delta views, zones, unfinished auctions, delta flips and session statistics), rows aligned on the even boundary, Renko and point and figure sizing from price or the ATR, and settings dialogs for both chart types in the widget and the reference host. It raises the profile budget to 19.54 kB, the transform to 6.23 kB, the widget to 124.09 kB with its first-use parts to 21.00 kB in eight files, the terminal to 362.89 kB, all tiers to 424.23 kB, the nine classic scripts to 437.85 kB and the widget classic script to 137.57 kB, each to its measured need; the chart-only import is unchanged at 87.19 KiB.

Version 2.6.2 fixes the bottom bar's ranges and Go to, which reported missing history across a gap no session trades in. It raises the widget budget to 124.13 kB, the terminal to 362.94 kB, all tiers to 424.28 kB, the nine classic scripts to 438.25 kB, the base classic script to 137.70 kB and the widget classic script to 137.78 kB, each to its measured need. The base classic script grows 180 bytes from the version string alone: one byte changes and Brotli encodes the file differently; the widget classic script carries the fix as well. The chart-only import is unchanged at 87.19 KiB.

Version 2.6.3 is a finish release: finer glyphs at one line weight, the rail that folds away behind a tab, a wheel zoom that chases one target per frame, a log scale padded in log space, the widget's drag and zoom defaults, and tooltips that leave the click to the control under them. It raises the base budget to 137.62 kB and base plus trade to 154.49 kB (the zoom chase and the log padding), the draw tier to 58.45 kB (the two size constants, the double chevrons and the cursor's own line), the widget to 124.94 kB (the fold, its tab and styles, the drag defaults and their restore), the terminal to 364.01 kB, all tiers to 425.35 kB, the nine classic scripts to 439.12 kB, the widget classic script to 138.54 kB and the base classic script to 137.72 kB, each to its measured need. The chart-only import rises 111 bytes to 87.30 KiB for the zoom chase and the log padding every chart carries.

Version 2.6.4 is an order flow release: an untraded row inside a footprint bar counts as zero for imbalances, a delta-shaded volume view, zone alerts, a choice of zone kinds and lookback, a colour for each part of a footprint and six named themes, all in the profile tier. It raises the profile budget to 20.83 kB (about 0.57 kB for the themes, 0.72 kB for the rest), all tiers to 426.67 kB and the nine classic scripts to 440.43 kB. The base engine, trade, draw and widget bundles differ from 2.6.3 only in their version string; Brotli moves the base budget to 137.65 kB, base plus trade to 154.53 kB and the terminal to 364.05 kB, and the base classic script's comes down to 137.69 kB. The chart-only import is unchanged at 87.30 KiB.
