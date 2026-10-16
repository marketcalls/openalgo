# Widget tier

*When to read this: the user wants a chart with a toolbar, a drawing rail, dialogs or shortcuts without writing that chrome; or asks whether the library "has a UI"; or is embedding one of the widget's dialogs in a host of their own.*

Source of truth: `src/widget/index.ts` (the export list), `src/widget/widget.ts` (options, handle, state), `src/widget/widget-persist.ts` (the saved layout, per-instrument drawings, `restoreState`, the debounced save and the pagehide flush), `src/widget/widget-keys.ts` (the shell's key scopes and bindings), `src/widget/storage.ts` and `src/widget/storage-idb.ts` (the IndexedDB store, its change announcements, the one-time copy from `localStorage` and the default store; the store's code loads when the first store is created), `src/widget/mobile.ts` (responsive chrome), `src/widget/context.ts` (the context, the bus, storage, the overlay stack, the dialog registry), `src/widget/keymap.ts`, `src/widget/keymap-editor.ts`, `src/widget/rail.ts`, `src/widget/topbar.ts`, `src/widget/statusline.ts`, `src/widget/toast.ts`, `src/widget/tokens.ts`, `src/widget/styles.ts`, `src/widget/form.ts`, the dialog modules under `src/widget/dialogs/`, and `dist/widget/index.d.ts` once built. Packaging: `rollup.config.js`, `package.json` (`exports['./widget']`), `.size-limit.json`, `scripts/check-dts.mjs`, `scripts/check-shake.mjs`.

## What it is

`openalgo-charts/widget` is one of nine tiers and the only one that builds DOM. `createWidget(container, options)` returns a `Widget` that owns a `Chart`, a `DrawingController`, and the chrome around them: top bar (symbol box, interval pills, chart type, indicators, capture, settings, theme), drawing rail, status line, the settings dialog, the indicator picker and per-indicator settings, drawing properties, a level editor for the fib and gann family, an in-place text editor for the text tools, a right-click menu, a keymap with a `?` shortcuts panel, toasts, one injected stylesheet, and optional layout persistence.

**The engine still ships no DOM.** Rule 12 of the hub skill stands for `openalgo-charts` and the seven other DOM-free tiers. The widget is the exception by design: it is a host, packaged, and it drives the engine only through the public API (`createChart`, `DrawingController`, `chartSettingsSchema`, `drawingSettingsSchema`, the `contextmenu` event, the registries). Enforced by the ESLint tier ACL (nothing under `src/` except `src/widget/` may import it; the widget reaches the engine and the draw tier only through `openalgo-charts` and `openalgo-charts/draw`), by `npm run shake` (a chart-only import is asserted free of the `oac-widget` CSS scope), and by the size rows.

## Setup

From 2.5.2, chart-owned event markers open `EventDetailsPopup` automatically.
Use `WidgetOptions.eventDetails` for its detail loader, labels and formatter, or
`eventDetails: false` for host-owned event UI. The default formatter uses the
chart's current timezone and widget locale. Event data is supplied through
`widget.chart.setEvents()`, with optional groups and clustering controls.
Symbol changes, replaced events and widget disposal close the popup and cancel
pending detail loading. Details may carry rich `blocks`, rendered as
text with vetted links, and `eventDetails.actions` adds host buttons (the type is
`EventDetailAction`). The widget's popup takes its words from the widget's
`translate` (message keys `Event details`, `Close`, `Events`, `Loading details...`,
`No additional details.`, `Unable to load additional details.`); `eventDetails.labels`
still wins, one label at a time. See the timeline section in `primitives-and-plugins.md`.

```ts
import { createWidget } from 'openalgo-charts/widget';
import 'openalgo-charts/indicators';                 // the picker lists what the registry holds
import { OpenAlgoDataFeed } from 'openalgo-charts';

const widget = createWidget('#terminal', {
  feed: new OpenAlgoDataFeed({ baseUrl: 'http://127.0.0.1:5000', apiKey: 'YOUR_KEY' }),
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '5m',
  theme: 'dark',
  persist: true,
});
```

`container` is an `HTMLElement`, a CSS selector, or an element id and must exist before the call. Give it a real height for rendering; since 2.1.3 an initially hidden chart can receive data and apply its pending initial view when layout reports a usable width. See [host-integration](host-integration.md#hidden-charts-and-preferred-views). The widget imports `openalgo-charts` and `openalgo-charts/draw` itself; the indicator tier is the host's import because not every terminal wants 112 indicators.

Importing the module touches no DOM; only `createWidget` does (it injects the stylesheet and builds the root then). Import it anywhere, call it once the container exists. `npm run skills:coverage` imports the built tier under Node and fails on a module-scope `document` access.

## Exports

### Translation contract (`localization.ts`)

`widgetText(ctx, key, values?)` resolves typed English source messages, interpolates
named values once and falls back for missing, blank, malformed or throwing host
translations. `WidgetBuiltinMessage`, `WidgetMessageKey`, `WidgetMessageValues`,
`WidgetMessageParameters`, `WidgetTranslator` and `WidgetTranslationOptions` are
the exported types. `WidgetOptions.translate`, `WidgetContext.translate` and
`AlertUiOptions.translate` share the optional synchronous callback. The callback
receives `(key, fallback, values)` and returns a translated template or undefined.

Generated metadata uses `schema.*` keys with descriptor text as fallback.
`FormTranslationOptions` adds a stable `scope` for `controlsFromInputs` and
`controlsFromFields`; `FormOptions.translate` localizes form furniture. Symbol and
interval codes, user alert/drawing text, object names, configured branding and
provider errors remain literal. `locale` independently formats status-line
numbers. Recreate a widget to change every mounted control's language.
See [widget localization](../../../../docs/widget-localization.md) for key shapes,
fallback rules and async persistence guidance.

The existing `WorkspaceRepository`/`WorkspaceStorage` API supplies asynchronous
account persistence. Keep each repository's namespace fixed, create another for
an account change, and fence stale restores in the host. Widget `persist` is local
preference storage for one browser (IndexedDB by default since 2.5.10, see the state
paragraph below), not an account adapter. Do not put credentials in portable documents.

`WidgetOptions` and `ContextMenuHooks` also accept `tradingCapabilities?:
TradingCapabilitySource`, `tradingMode` and `tradingLocked`. Unsupported order
routes are hidden; replay and host selection locks disable placement. Callbacks
recheck capabilities, replay and chart context immediately before `onOrder`.
Throwing capability/lock providers refuse the action. Execution remains host-owned.

Everything `src/widget/index.ts` exports at runtime. The shell (`createWidget` and the handle) is what a host uses; the rest is exported so a host that wants one piece of the chrome and its own for the rest can have it, or so a dialog module of the host's own can register with the shell.

### The shell (`widget.ts`)

| Export | Kind | Purpose |
|---|---|---|
| `createWidget(container, options?)` | function | The one call. Returns a `Widget`. |
| `WIDGET_TIER` | const `'widget'` | The tier's identity constant, like `DRAW_TIER`. |
| `stripView(state)` | function | A detached `WidgetChartState` view patch without viewport, manual ranges or ratio locks on any scale. It enables auto-fit while retaining formatting and declared fixed ranges when the layout lands on another symbol or interval. |
| `resolveTheme(t)` | function | `'dark'`, `'light'`, a `ChartTheme` or `undefined` to `{ theme, name }`. |
| `loadWindow(interval, lookback, nowSec)` | function | The `{ from, to }` the feed is asked for: `lookback` bars back from now, or five years for a non-time bucketing. |
| `DEFAULT_INTERVALS` | const | `['1m', '5m', '15m', '1h', '1d', '1w']`, with every other registered code appended when the host names none. |
| `DEFAULT_LOOKBACK_BARS` | const `500` | Bars per load when `lookbackBars` is not given. |
| `SAVE_DEBOUNCE_MS` | const `250` | Debounce on writing the persisted layout. |
| `STATE_KEY` | const `'state'` | The storage entry the layout lives under. |
| `DRAWINGS_KEY_PREFIX` | const `'drawings:'` | (since 2.5.9) With `persist`, each instrument's drawings live beside the layout under this prefix and the instrument key: `oac-widget:<namespace>:drawings:NSE:INFY`. |
| `WIDGET_STATE_VERSION` | const `1` | `WidgetState.version`. |
| `Widget`, `WidgetOptions`, `WidgetState`, `WidgetChartState`, `WidgetRestoreReport`, `WidgetEventName` | types | See the sections below. |
| `mountMobile(ctx, options)` | function | Mount the narrow header, bottom bar and sheets against an existing `WidgetContext`. Returns `MobileHandle`. |
| `MobileMode`, `MobileOptions`, `MobileHandle` | types | Responsive mode, mount contract and handle for custom widget composition. |

### The context, bus, storage and overlays (`context.ts`)

| Export | Kind | Purpose |
|---|---|---|
| `WidgetBus` | class | Typed `on` / `off` / `emit` / `clear`; the widget's own events ride it. |
| `WidgetStorage` | class | Namespaced `get` / `set` / `remove` over a `StorageLike`, straight through, or (since 2.5.10) over an `AsyncStorageLike` through a copy of the namespace in memory. `load()` reads it once. Changes are written behind, coalesced per key and in order. `flush()` sends them now and journals them. `loaded` says whether reads answer from the store. Over a store with `subscribe`, the copy follows the writes other tabs land until `close()`, which the widget calls on destroy. `new WidgetStorage(namespace, store, { onError })` reports each `WidgetStorageError`. `enabled` is false when `persist` is off, and a throwing store reads as "nothing saved". |
| `STORAGE_PREFIX` | const `'oac-widget:'` | Every key the widget writes sits under it. |
| `defaultStorage()` | function | The page's `localStorage` when it exists and works, else null. |
| `createIndexedDbWidgetStorage(factory, name?, options?)` | function | (since 2.5.10) The widget's key-value store over IndexedDB (`name` default `'openalgo-charts-widget'`): one object store of JSON texts, one transaction per call, `close()`. The first read of a namespace the database has never held copies the `oac-widget:<namespace>:` keys from `localStorage` (`options.migrateFrom`; null copies nothing) and leaves them there. Each write that lands is announced to `subscribe` listeners, and to other tabs over a broadcast channel. `options.journal` (default `localStorage`, null for none) keeps the writes still pending when a page goes away. |
| `registerWidgetDialog(name, mount)` | function | Make a dialog's mount known to every shell. Returns a disposer. |
| `registerWidgetDialogs(mounts)` | function | Several at once, from a module's exports. |
| `unregisterWidgetDialog(name)` | function | Remove one; false when nothing was registered. |
| `widgetDialog(name)` | function | The registered `DialogMount` for a name, or null. The top bar reads this on every refresh, which is how its settings and indicators buttons light up. |
| `registeredWidgetDialogs()` | function | The names registered so far. |
| `createOverlayStack(root, doc)` | function | The layer dialogs, popovers and menus open on: positioned from an anchor or centred, focus-trapped, one Escape per layer, focus returned on close. |
| `createTipController(root, layer, doc)` | function | Hover labels for controls, shown after `TIP_DWELL_MS`. |
| `TIP_DWELL_MS` | const `600` | Pointer dwell before a tip appears. |
| `esc(s)` | function | HTML-escape the four characters that matter. |
| `h(doc, tag, className?, attrs?)` | function | `createElement` with a class and attributes. |
| `glyph(doc, svg, kind)` | function | A span holding trusted `<svg>` from the draw tier's icon registry (`'tool'` or `'chrome'` sizing). |
| `inTextField(target)` | function | Whether a key event came from a text control, where chords stay out of the way. |
| `focusable(n)`, `focusables(root)` | functions | Focus-trap helpers. |
| `placeBeside(anchor, size, bounds, gap?, pad?)`, `placeBelow(...)`, `placeTip(...)` | functions | Pure placement maths in root coordinates, flipping when there is no room. |
| `boxIn(root, el)` | function | An element's box in the widget root's coordinate space. |
| `historyPress(ctx, 'undo' \| 'redo')`, `historyReady(ctx, 'undo' \| 'redo')` | functions | One undo or redo press through `ctx.history`, and whether it would do anything; a custom context without a history falls back to `ctx.draw`. Every widget undo control calls these. (2.5.6) |
| `WidgetContext`, `WidgetBusEvents`, `BusHandler`, `StorageLike`, `AsyncStorageLike`, `WidgetStorageOptions`, `WidgetStorageError`, `IndexedDbWidgetStorage`, `IndexedDbWidgetStorageOptions`, `DialogMount`, `DialogHandle`, `WidgetDialogName`, `OverlayOptions`, `OverlayStack`, `TipSpec`, `TipSource`, `TipSide`, `TipController`, `Box`, `Size` | types | |

### The keymap (`keymap.ts`)

| Export | Kind | Purpose |
|---|---|---|
| `Keymap` | class | One capture-phase keydown listener on the document; `register(combo, action, scope, opts)` returns a disposer (`opts.command` names a binding a user may move, `opts.rebindable: false` fixes it); `handle`, `attach`, `list`, `conflicts`, `onConflict`, `format`, `activeScopes`, `destroy`. Since 2.5.10: `rebind(command, combo, { replace? })` and `reset(command, { replace? })` return a `KeyRebindResult` (`ok`, a `reason` of unknown, fixed, invalid, reserved or taken, and the `conflicts`); `resetAll()`, `chord(command)`, `conflictsFor(combo, scope?)`, `overrides()` and `applyOverrides(record)` (replaces rather than merges, drops what it cannot use, keeps a command not registered yet), `onChange(fn)`, and `capture(fn)` with `capturing` for a control that records a chord (while it records, every other keymap attached to the same document claims nothing). Engine commands are `chart:<command>` in the engine's code grammar. |
| `openShortcutsPanel(ctx, opts?)` | function | The `?` panel: every binding by group, a shadowed one struck through, and Change, Reset and Reset all unless `opts.edit` is false or the widget was built with `shortcutsEditor: false`. The editor refuses a browser-reserved chord, a bare letter or digit, and Space alone. Returns the closer. Since 2.5.10 the panel loads on first use (see Packaging facts): the first call opens it once it has arrived, the closer cancels one still on its way, and a panel that cannot load says so in a toast. |
| `KEYMAP_KEY` | const | `'keymap'`, the widget-storage key the user's chords are saved under when `persist` is on. |
| `parseKeyCombo(spec)` | function | A human spec (`'Ctrl+Shift+Z'`, `'Mod+Z'`) to the canonical chord. |
| `eventKeyCombo(e)` | function | The canonical chord an event stands for, or `''` for a bare modifier press. |
| `formatKeyCombo(combo, isMac?)` | function | A chord as a user reads it (`Cmd` on a Mac). |
| `fromChartCombo(combo)` | function | The engine's `ShortcutManager` spelling to the widget's. |
| `KeyScope`, `KeyEventLike`, `KeyAction`, `KeyBinding`, `KeyBindingOptions`, `KeyConflict`, `KeymapOptions`, `KeymapGroup`, `KeymapRow`, `KeyChordUse`, `KeyRebindResult`, `KeymapOverrides`, `KeymapChange`, `ShortcutsPanelOptions`, `ChartShortcutSource` | types | |

Scopes resolve narrowest first: `['overlay']` alone while any overlay is open (nothing else fires; the stack's own listener handles Escape and Tab), otherwise `rail` (focus in the rail), `chart` (pointer or focus on the chart), `widget` (pointer or focus in the root), `global`. A binding's action may return `false` to decline the key, in which case the next scope is tried and finally the engine sees it. A claimed chord is prevented and stopped, so the engine's `ShortcutManager` never sees it. Conflicts with the engine's own table are reported through `conflicts()` and the `keymap:conflict` bus event; the nudge arrows are registered layered and excluded from the report, while `Alt+H` and `Alt+V` (draw-tier tool chords) genuinely shadow the chart's grid toggles and are listed.

### The rail (`rail.ts`)

| Export | Kind | Purpose |
|---|---|---|
| `mountRail(ctx, host, opts?)` | function | The drawing rail into `host`. Returns a `RailHandle` (`sync`, `refresh`, `prefs`, `restorePrefs`, `magnetMode`, `setMagnetMode`, `cycleMagnet`, `stayMode`, `setStayMode`, `setDrawLock`, `collapsed`, `setCollapsed`, `destroy`). `collapsed` and `setCollapsed` (since 2.6.3) are optional members, so a handle a host wrote for `mountMobile` before them still fits. |
| `RAIL_GROUPS` | const | The group table: lines, channels, fib and gann, shapes, cycles, marks, text, measure, and the ids in each. The rail's order comes from here, not from `rail.tools`. |
| `MAGNET_MODES` | const | `['off', 'weak', 'strong']`, the cycle the magnet button walks. |
| `RAIL_PREFS_KEY` | const `'rail'` | The storage entry the rail's pins, last-picked tools, magnet and stay modes, and the fold (`collapsed: true`, since 2.6.3) live under. |
| `toolGlyph(doc, id)` | function | A tool's glyph from the draw tier's sprite; a tool without an icon still gets its name. |
| `toolName(id)` | function | A tool's display name from the registry, or the id itself. |
| `sanitizeRailPrefs(raw, groups, toolsOf)` | function | Validate a stored preference object field by field, dropping what this build cannot honour. |
| `RailOptions`, `RailHandle`, `RailPrefs`, `RailGroup`, `RailGroupItem` | types | |

The sprite is injected once per document on the body (`id="oac-rail-sprite"`), so it outlives any one widget.

Since 2.6.3 the last button of the controls block (chevrons pointing left) folds the rail away. The rail takes `.is-collapsed` (hidden), the chart widens into its column, and a small tab (`.oac-rail-tab`, chevrons pointing right) appears at the stage's bottom left; pressing it brings the rail back. Focus follows the control that replaces the one pressed. The fold is a rail preference: it persists with the pins and the magnet, travels in `getState().rail`, and is restored by `restoreState`. The tab stops `pointerdown` so the chart's pointer capture cannot take the press, and it is hidden on the phone layout and in a dense grid cell, where the rail already is. Tools that scroll under the controls block fade out above it instead of being cut through. Tool glyphs show at `ICON_SIZE` (20px) and chrome glyphs at `CHROME_ICON_SIZE` (16px), each at its tier's stroke; the magnet in the controls block is the chrome glyph, so the block is one size.

### The top bar (`topbar.ts`)

| Export | Kind | Purpose |
|---|---|---|
| `mountTopbar(ctx, host, opts)` | function | Symbol box with search, interval pills, chart type menu, Indicators, Go to (with `onGoTo`), Objects, capture, settings, theme. Returns a `TopbarHandle` (`refresh`, `destroy`). |
| `openMenu(ctx, anchor, rows, opts?)` | function | A popover menu under `anchor`, with an optional filter box; the chart type menu and the symbol results share it. A row's optional `icon` (a chrome icon id, since 2.5.10) draws that glyph before its label; once one row has one, every row keeps the column, and an id the registry does not carry leaves the slot empty. `opts.placement: 'beside'` opens it beside the anchor instead, clearing `opts.edge` too (the rail's right-click menus use it). The first parameter needs only `document`, `openOverlay` and `translate`, so a bottom bar context serves. Returns the closer. |
| `chartTypeChoices()` | function | The registered chart types a user can pick for the instrument (the registry minus histogram-family internals), then every transform the chart applies, point and figure and Kagi listed once, there. |
| `chartTypeLabel(id)` | function | A label from `CHART_TYPE_LABELS`, else the id. |
| `CHART_TYPE_LABELS` | const | Labels for the built-in chart types. |
| `intervalLabel(code)` | function | `'1d'` as `D`, `'1w'` as `W`, minute and hour codes as written, a registered calendar code upper-cased. |
| `downloadText(doc, filename, text, mime)` | function | Hand text to the browser as a file; false when the runtime cannot. |
| `captureName(symbol, interval, now?)` | function | `SYMBOL-5m-2026-01-31-09-15`, filename-safe. |
| `SEARCH_DEBOUNCE_MS` | const `150` | Quiet before `symbolSearch` runs. |
| `TopbarOptions`, `TopbarHandle`, `TopbarState`, `SymbolMatch`, `SymbolSearch`, `MenuRow`, `MenuOptions` | types | `SymbolMatch` is the base package's type, re-exported. The results panel keeps focus in its field while a row is pressed, and a failed lookup shows "Search unavailable" (`schema.ui.symbolSearchFailed`) with typed entry still committing. Enter in the top bar, the phone header and the watchlist's add box waits for a search that is still running (its debounce or the host lookup), as the typing-navigation box already did, so it picks the result the user was about to see; typed text commits once a search finishes without matches or fails (`SymbolPickerHandle.canCommitRaw`). |

The Capture menu includes **Download chart data (CSV)**, using the base
`exportChartDataCsv` API. It captures source identity when opened and refuses a
changed, empty or loading source. The widget supplies source readiness; custom
`mountTopbar` hosts can supply `TopbarOptions.dataAvailable()` for their own loading
boundary. Active replay exports only installed rows. File failures surface in
the status line and download resources are released after handoff or failure.
The dialog asks for its From and To bounds as a date and a time on
the chart's clock (the chart's timezone, named under the fields), not as UTC
seconds; a To written to the minute takes in every bar that opens inside it, and
the captured visible range fills both to the second.

### The bottom bar (`bottombar.ts`, `ranges.ts`) (since 2.5.10)

| Export | Kind | What |
|---|---|---|
| `mountBottombar(ctx, host, opts?)` | function | The strip under the chart: preset ranges and Go to on the left; on the right the market status (from `marketStatusAt` on the chart's calendar, in a `role="status"` region so a change of phase is announced; hidden without a calendar, or with the "Session state" switch off), a clock in the chart's zone that opens a searchable timezone menu, and the Auto, Log and Percent price scale toggles, which follow the scale (an axis drag, an undo, a reset). `opts.target` is read at every use, so one bar can serve whichever chart has the focus; `ranges`, `onGoTo`, `now`, `timezones` and `onTimezone` are optional. `ctx` is a `BottombarContext`: a `WidgetContext` is one, and a custom host builds one from `createOverlayStack` and `createTipController` over an `.oac-widget` root. One timer a second, stopped while the page is hidden. Returns a `BottombarHandle` (`el`, `controls`, `refresh`, `destroy`); `controls` are the same actions without the markup, which the phone layout's More sheet lists. |
| `BOTTOMBAR_HEIGHT` | const `28` | The strip's height in CSS px. |
| `BOTTOMBAR_CSS` | const | Its rules, part of `WIDGET_COMPONENT_CSS`. A widget root carrying the bar (`.has-bottombar`) takes a fourth grid row for it, between the stage and the status line; `.is-mobile` hides it, except a bar marked `is-kept` (a widget with `topbar: false`, which has no More sheet), which stays above the phone footer. On a narrow bar the ranges scroll; the status, the clock and the toggles keep their size. |
| `DEFAULT_RANGES` | const | `1D` (`1m`, one session), `5D` (`5m`, five sessions), `1M` (`30m`), `3M` (`1h`), `6M` (`1d`), `YTD` (`1d`), `1Y` (`1d`), `5Y` (`1w`), `All` (`1w`). |
| `rangeWindow(range, { end, zone?, calendar?, bars? })` | function | The `{ from, to }` a range covers, ending at `end`. A `session` range walks back through the calendar's sessions (a weekend or a closed date is skipped, a date with a midday break counts once, its pre-open belongs to it), so one NSE day at `1m` is the 375 bars from 09:15, not 1,440 minutes; without a calendar it counts the dates the `bars` fall on, or weekdays. Months and years run from midnight on the same date that far back in `zone`, `ytd` from 1 January, `all` from the first bar (or 30 years back without `bars`). |
| `rangeInterval(range, offered)` | function | The range's own interval when offered, else the nearest time-based one by ratio, the longer on a tie. |
| `WidgetRange`, `WidgetRangeUnit`, `WidgetRangeWindow`, `RangeWindowOptions`, `BottombarContext`, `BottombarTarget`, `BottombarOptions`, `BottombarControls`, `BottombarHandle`, `BottombarScaleToggle`, `BottombarScaleState`, `MarketStatusReading`, `WidgetBottombarOptions`, `WidgetSessionCalendar` | types | |

### Status line, toasts, tokens, styles

| Export | Kind | Purpose |
|---|---|---|
| `mountStatusline(ctx, host, opts?)` | function | Symbol, interval, O H L C, change, volume and time of the hovered bar, or of the latest bar while the pointer is away (reread on every data update); timezone; a transient message slot (the widget puts the bar count there after a load). Returns a `StatuslineHandle` (`setSymbol`: the first title names the bars already there, a later different title clears the readings until the next full data replace; `setBar`: hold a bar, null follows the latest again; `setMessage`, `refresh`, `destroy`). |
| `priceDigits(chart)` | function | Decimals for the readout: the pane's own precision floored at `MIN_PRICE_DIGITS`. |
| `mountAccountSummary(ctx, host, { source, locale? })` | function | Account summary: the selected account (a menu switches it), an Analyzer tag for the sandbox ledger, equity, margin used and available, and a Stale or error state. `source` is an `AccountStateSource`, usually the trade tier's `AccountManager`. Read-only apart from switching; it has no order controls. An `unsupported` source renders disabled (`aria-disabled`, class `is-disabled`) with the provider's reason visible. Mounted before `.oac-statusline__tz` when the host has one. In a narrow status line (a container query on the row) the hover time yields first, then margin used, equity and available drop out, and below 860 px the summary moves beside the title so the account and its tag are never the part that is clipped; the picker's tooltip keeps the figures. Returns an `AccountSummaryHandle` (`el`, `refresh`, `destroy`). |
| `ACCOUNT_SUMMARY_CSS` | const | The summary's rules, part of `WIDGET_COMPONENT_CSS`. |
| `MIN_PRICE_DIGITS` | const `2` | |
| `mountToasts(host, doc?)` | function | The toast stack. Returns a `Toaster` (`toast(message, kind?)`, `destroy`). |
| `TOAST_MS` | const | `{ info: 4000, success: 3500, error: 0 }`; 0 stays until dismissed. |
| `TOAST_MAX` | const `5` | Beyond this many the oldest goes. |
| `TOAST_LEAVE_MS` | const `160` | Leave transition. |
| `widgetTokens(theme, mode?)` | function | Every chrome custom property derived from a `ChartTheme`. |
| `applyTokens(el, tokens)` | function | Write a token set inline on an element. |
| `themeMode(theme)` | function | `'dark'` or `'light'`, judged from the theme background. |
| `token(name)` | function | `var(--oac-name)`. |
| `parseColor(input)`, `formatColor(c)`, `luminance(color)`, `mix(a, b, t)`, `withAlpha(color, alpha)` | functions | The colour maths the tokens are built from; exported for a host deriving its own. This `withAlpha` is not the base package's: it writes a CSS token value, `#rrggbb` when the result is opaque and `rgba()` otherwise, with the alpha clamped to 0..1, where the base one always writes `rgba(r,g,b,a)` with the alpha as given, for canvas. Use this one for chrome styles and the base one for anything the chart paints; alias one when a module imports both. |
| `contrastRatio(a, b)`, `readableOn(color, surfaces, pole, min?)`, `TEXT_CONTRAST` | functions, const `4.5` | (since 2.5.9) The WCAG ratio of two colours, and a colour stepped toward `pole` by the least amount that reads at `min` on every one of `surfaces`. The text tokens (`mut`, `faint`, `up`, `down`, `amber`, `danger`) are built with it, so they read at 4.5 to 1 in both built-in themes and in a host theme. |
| `TOKEN_PREFIX` | const `'--oac-'` | |
| `WIDGET_FONT`, `WIDGET_MONO` | consts | The UI and monospace font stacks. |
| `RAIL_WIDTH`, `TOPBAR_HEIGHT`, `STATUSLINE_HEIGHT` | consts | `42`, `40`, `24` CSS pixels, shared by the stylesheet and the placement maths. |
| `WIDGET_CSS` | const | The shell stylesheet text. |
| `DIALOG_CSS` | const | The dialog rules, appended to the same sheet by `createWidget`. |
| `OBJECTS_PANEL_CSS` | const | Object list rules, included in the widget stylesheet; custom hosts append it alongside `WIDGET_CSS` and `DIALOG_CSS`. |
| `WIDGET_STYLE_ID` | const `'oac-widget-css'` | Id of the injected `<style>`, one per document. |
| `injectWidgetStyles(doc, extra?, nonce?)` | function | Inject or fill an empty sheet once per document; `extra` is appended when filling it. Assigns the nonce before filling/insertion, preserves an existing nonce and leaves populated host CSS untouched. |
| `AccountSummaryOptions`, `AccountSummaryHandle`, `StatuslineOptions`, `StatuslineHandle`, `Toaster`, `ToastHandle`, `ToastKind`, `ToastOptions`, `WidgetThemeName`, `WidgetTokens`, `Rgba` | types | |

### Dialogs and forms (`dialogs/`, `form.ts`)

Every mount takes the context and an optional anchor element (so it satisfies `DialogMount`), plus an options object, and returns a `PanelHandle` (`el`, `close()`, `isOpen()`). A mount that cannot act (no selection, an unknown instance) toasts and returns a closed handle rather than throwing. Anchored, a picker or properties panel opens as a popover below the anchor; without one, dialogs are centred and modal.

| Export | Kind | Purpose |
|---|---|---|
| `mountSettingsDialog(ctx, anchor?, { tab?, unavailable?, onApply?, onClose? })` | function | Chart settings, generated from `chartSettingsSchema(chart)`; Cancel and Escape revert the dirty keys. |
| `mountIndicatorPicker(ctx, anchor?, { onAdd?, closeOnAdd?, templates? })` | function | Searchable, grouped list of every registered indicator. (since 2.5.10) With a template store (`templates`, default the widget's `workspaces`; null for none) that has `planIndicatorTemplateState`, a Templates button bottom left lists the saved indicator templates: Replace, Append, delete (asks first), and Save studies as template. |
| `mountIndicatorSettings(ctx, anchor?, { instanceId?, tab?, onChange?, onClose? })` | function | Inputs and styles for one indicator, from its descriptor. `instanceId` falls back to `anchor.dataset.instanceId`, then the chart's only indicator. |
| `mountDrawingProperties(ctx, anchor?, { ids?, tab?, onClose? })` | function | The selected drawings' fields, from `drawingSettingsSchema`, on a Style tab, and (since 2.5.9) every anchor as a date, a time and a price on a Coordinates tab (`tab: 'coordinates'` opens on it). Bottom left: Restore defaults, and (since 2.5.9) Templates when the context carries `drawingTemplates`. |
| `mountDrawingCoordinates(ctx, host, ids, why)` | function | (since 2.5.9) The Coordinates tab on its own, for a host's own dialog: `ids()` names the drawings and `why()` is the reason they are read-only, or null. Returns a `DrawingCoordinatesHandle` (`el`, `refresh()`, `destroy()`). |
| `DRAWING_COORDINATES_CSS` | const | (since 2.5.9) Its rules, part of `WIDGET_COMPONENT_CSS`. |
| `mountLevelEditor(ctx, anchor?, { ids? })` | function | Per-level ratio, colour and visibility for the fib and gann tools. |
| `mountTextEditor(ctx, anchor?, { id?, onDone? })` | function | In-place editing laid over the painted text. Returns a `TextEditorHandle` with `commit()` and `cancel()`; an outside press commits, Escape cancels. |
| `mountContextMenu(ctx, anchor?, { event?, hooks? })` | function | The right-click menu for the chart's `contextmenu` payload: trade rows when `onOrder` is given (limit and stop rows only over the price pane, where the pointer's price is the instrument's; a study pane offers the market rows alone), drawing actions on a drawing, scale modes on a price axis, `Move pane up` and `Move pane down` (row ids `pane-up`, `pane-down`, greyed at an edge, and greyed with the note "price pane stays on top" where a chart built without `movablePrimaryPane` would refuse the swap) over any pane when there are two or more, the price pane included, `Collapse pane` or `Expand pane` (row id `pane-collapse`) over a study pane in any slot, paste, fit, indicators, settings. A menu raised from a button names no pane and has no pane rows. A move or a collapse is saved with the layout and emitted as a `layout` event with reason `paneMoved` or `paneCollapsed`. |
| `mountAlertEditor(ctx, anchor?, opts?: AlertEditorOptions)` | function | Draft editor seeded by `source` or editing `alertId`. Save validates source identities, finite bounds and expiry in the labelled chart timezone. Cancel never arms an alert. |
| `mountAlertsPanel(ctx, anchor?, opts?: AlertsPanelOptions)` | function | Live alert list with lifecycle, scope, timing, availability, last delivery, edit, enable/disable and delete. Both options types accept `onClose`. |
| `attachContextMenu(ctx, hooks?)` | function | Subscribe to the chart's `contextmenu`, `preventDefault`, mount the menu. Returns the unsubscriber. `createWidget` does this itself. |
| `contextMenuEntries(ctx, event, hooks)` | function | The `MenuEntry[]` the menu is built from, for a host composing its own. |
| `WIDGET_DIALOGS` | const | Registry mounts: `settings`, `indicatorPicker`, `indicatorSettings`, `drawingProperties`, `contextMenu`, `levelEditor`, `textEditor`, `alertEditor`, `alerts`. Registered on import. |
| `renderForm(host, controls, opts)` | function | One control renderer for every generated form: switch column, label, control column; `colorPair` on one row. Returns a `FormHandle`. |
| `controlsFromInputs(inputs, translation?, intervals?)` | function | `ChartSettingsInput[]` (the engine's settings schema) to `FormControl[]`. An `interval` input becomes a select: `Chart` (the empty value), then `intervals` in order, or the built-in tokens and every registered code without it. The study settings dialog passes `WidgetContext.intervals`, which the widget sets from `WidgetOptions.intervals` when the host names them. |
| `controlsFromFields(fields)` | function | A drawing tool's `SettingsField[]` to `FormControl[]`. |
| `mountIndicatorInputControls(ctx, options)` | function | Adds symbol lookup and chart picking to an existing indicator form. Returns `IndicatorInputControlsHandle` with `cancelPick`, `refresh` and `destroy`. An action beside a disabled field is disabled with the field's reason; call `refresh()` after the form re-reads its conditions. |
| `inputStates(inputs, values)` | function | (2.5.6) `Map<key, InputState>` of `{ visible, active, dependsOn }` from each input's `visibleWhen` and `activeWhen`, cascading through inputs a condition reads. A colour pair's `enabled`, `up` and `down` keys, on the input or under a form control's `pair`, count as the pair. For a host that renders its own form. |
| `inputConditionMet(condition, values)` | function | (2.5.6) Whether one `IndicatorInputCondition` holds for a settings bag. Reads own keys only; a malformed condition counts as met. |
| `InputState` | type | (2.5.6) One input's `visible`, `active` and the `dependsOn` keys its `activeWhen` reads. |
| `IndicatorInputControlsOptions`, `IndicatorInputControlsHandle` | types | Native typed-field host actions. |
| `SettingsDialogOptions`, `IndicatorPickerOptions`, `IndicatorSettingsOptions`, `IndicatorSettingsTab`, `DrawingPropertiesOptions`, `DrawingCoordinatesHandle`, `LevelEditorOptions`, `TextEditorOptions`, `TextEditorHandle`, `ContextMenuHooks`, `ContextMenuOptions`, `MenuEntry`, `MenuItem`, `OrderRequest`, `PanelHandle`, `FormControl`, `FormKind`, `FormOptions`, `FormHandle` | types | |

`OrderRequest` is `{ side: 'BUY' | 'SELL'; type: 'MARKET' | 'LIMIT' | 'SL'; price: number | null; paneIndex: number }`; `price` is null for a market order. Otherwise it is the pointer's price, not snapped to the instrument's tick or `TickSchedule` (the widget knows neither), so round it, for example with `validatePrice`, before sending.

`FormKind` includes `symbol`, `session`, `multiline`, `price` and `timestamp`.
`FormHandle.validate()` checks drafts and `setError(key, message)` reports a
field error without committing invalid settings. Prices and timestamps preserve
their numeric value; timestamps are absolute UTC seconds, including fractions.
An ordinary `time` field retains its existing clock-string contract.

From 2.5.6, `FormControl` carries an input's `activeWhen`, `visibleWhen` and
`inline`; `controlsFromInputs` threads them. `renderForm` re-reads them, and
`FormOptions.unavailable`, after every edit and every `sync(values)`, so the host
callback can depend on values too; its reason wins over "Depends on ...". A
hidden control keeps its draft, `values()` still reports it, and `validate()`
and `focusFirst()` skip hidden and disabled controls. A form with a condition
adds a polite `role="status"` live region (`.oac-sr`) that says "Shown: ...",
"Hidden: ...", "Available: ..." or "Unavailable: ...". Inline rows are
`.oac-row--inline` with one `.oac-inline__item` per member; a dimmed member is
`.oac-inline__item--off`. The new messages are localization keys:
`Depends on {inputs}`, `Not used with the current settings`, `Shown: {inputs}`,
`Hidden: {inputs}`, `Available: {inputs}`, `Unavailable: {inputs}`.

`IndicatorInputControlsOptions` provides `instance`, `inputs`, `panel`,
`field(key)` and atomic `onPatch(patch): boolean`. Optional `current()` fences
stale dialogs; `suspend()` lets a custom host hide its modal while picking.
The built-in `OverlayStack.suspend(panel)` releases the focus trap and scrim
until its idempotent resume callback runs. Destroy the controls with the form.
Configured lookup is available as `WidgetContext.symbolSearch`. A selected
symbol and its `exchangeKey` commit together; a missing exchange defaults to
an empty string. Without lookup, manual symbol entry remains available.
Price picks resolve the study's actual pane and scale, including hidden scales;
a mixed-scale study needs an explicit target. Drawing placement blocks picking.
A price paired with a timestamp (`timeKey`) gets **Pick point on chart** instead:
one click through `chart.beginPick('point')` fills both fields and reaches
`onPatch` as one patch holding both keys, and cancelling writes neither. The
hint reads "Pick {time} and {price} on the chart" (message keys
`Pick point on chart` and `Pick {time} and {price} on the chart`). The target is
`studyInputTarget` from the draw tier, the same one the chart's anchor uses. The
widget's `DrawingController` draws an `anchor: true` pair's handle, and Mod+Z,
the rail's Undo and the phone bar take a drag of it back, once: the widget's
`ChartHistory` holds the step, and a pick in the settings dialog is part of the
dialog's step on the same timeline. With the history destroyed, the same presses
walk the drawing controller's own history, which holds the pick as a step of its
own: the first undo takes it back, never a drawing made before it.
Context changes, study removal and chart destruction cancel pending controls.

Alert panels use optional `WidgetContext.alerts`, supplied automatically by
`createWidget`. Custom contexts without a controller show an unavailable reason.
Draft numeric forms set `FormOptions.preserveInvalidNumbers` so an empty field
stays empty and Save can report it. Live settings forms retain their previous
behavior of restoring the last valid numeric value. Alert expiry is entered in
the chart timezone captured and labelled when the editor opens; changing the
chart timezone does not reinterpret the draft. New alerts default to two chart
calendar months ahead, clamped to the last day of the target month. Clearing the
field means no expiry. Editing another field preserves the stored UTC instant,
including its seconds. Programmatically added alerts retain their existing
defaults; the two-month prefill belongs to the editor.
Context changes or removed anchors prevent stale drafts from being saved.

Text, number, select and date fields share one control column. Their height
uses `--oac-ctl-h`, and their outer corners and button corners use `--oac-radius`.
Color swatches stay compact. Theme overrides should target these tokens.

## `WidgetOptions`

`ChartOptions` (minus `theme`) plus:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `feed` | `DataFeed` | none | `getBars` is called for the current symbol and interval at start and on every `setSymbol` / `setInterval` / `reload`; `subscribeBars` when the feed has it. Without a feed, put data on `widget.series` yourself. |
| `symbol` | `string` | `''` (or the saved one) | Upper-cased. With a feed and a symbol, the first load starts in the constructor. |
| `exchange` | `string` | `''` | Passed to the feed with the symbol. |
| `interval` | `string` | `'1d'` (or the saved one) | Must be a code the interval registry knows; an unknown code throws the engine's `UnknownIntervalError` at the call site. A saved code this build does not know falls back to `'1d'`. |
| `intervals` | `readonly string[]` | `DEFAULT_INTERVALS` plus every registered code | The pill list. Each is validated the same way. A list the host names is also what a study's timeframe select offers (`WidgetContext.intervals`). |
| `variant` | `DataVariant` | the feed's default series (or the saved one) | Which of the feed's series to show: `{ session: 'extended' }`, `{ adjustment: 'raw' }`, a currency or a unit. A malformed one throws a `TypeError` at the call site. The feed must declare it through `dataVariants`, or the data status reads "Not available from this source: ..." with no retry. Since 2.5.6. |
| `chartType` | `string` | `'candlestick'` | The primary chart type: a registered renderer or a transform the chart applies (`heikin-ashi`, `renko`, `range-bars`, `line-break`, `point-figure`, `kagi`). |
| `theme` | `'dark' \| 'light' \| ChartTheme` | `'dark'` | Drives the canvas and the chrome tokens. Note the engine's own default is light; the widget's is dark. |
| `navigation`, `zoomAnchor` | engine options | `{ mousePan: 'horizontal' }`, `'right'` | (since 2.6.3) The widget's own defaults for the engine's navigation: a drag pans time alone, so the price scale keeps fitting what is in view, and the wheel zooms about the latest bar (Ctrl or Cmd: the cursor). A host's own values win; the engine defaults stay `'both'` and `'cursor'`. |
| `rail` | `boolean \| RailOptions` | on | `false` hides it. `RailOptions.tools` restricts which ids appear (order still follows `RAIL_GROUPS`); `favorites` seeds the pins when nothing is stored. |
| `topbar` | `boolean` | on | |
| `statusline` | `boolean` | on | With `bottombar: false` it also shows the market status from the chart's calendar (since 2.5.10). |
| `bottombar` | `boolean` | on | (since 2.5.10) The strip under the chart (see The bottom bar). `false` leaves it out and puts Go to back in the top bar. |
| `ranges` | `readonly WidgetRange[]` | `DEFAULT_RANGES` | (since 2.5.10) The bar's range buttons and the ids `setRange` takes; `[]` leaves the buttons out. |
| `sessionCalendar` | `SessionCalendarSource \| ((instrument) => SessionCalendarSource \| null)` | none | (since 2.5.10) Trading hours, applied with `chart.setSessionCalendar` for the first symbol and on every symbol change. They size a range in sessions and give the market status and the shading their hours. Without it the chart's calendar is left to the host. |
| `sessionShading` | `boolean` | on | (since 2.5.10) `attachSessionShading` on the chart: a faint wash behind pre-open, post-close and extended-hours bars. Nothing is shaded without such hours in the calendar. |
| `mobile` | `'auto'` \| `'always'` \| `'never'` | `'auto'` | Compact widget controls. Auto activates when the widget container is at most 640 CSS px wide, or, with a coarse primary pointer, at most 960 px wide and under 600 px tall; tablets and touch laptops keep the desktop chrome. |
| `indicators` | `boolean` | on | The Indicators button. |
| `persist` | `boolean \| string` | off | `true` uses the `default` namespace; a string names one, so two widgets on a page keep separate layouts. |
| `storage` | `StorageLike \| AsyncStorageLike \| null` | IndexedDB (since 2.5.10), else the page's `localStorage` | The store behind `persist`. A synchronous one (`localStorage`) restores before `createWidget` returns, as before 2.5.10; an asynchronous one restores when `ready` settles. |
| `drawingScope` | `'instrument' \| 'chart'` | `'instrument'` | (since 2.5.9) Whose drawings the chart shows. `'instrument'`: each symbol and exchange keeps its own, swapped by `setSymbol`, a restored layout or a watchlist pick. `'chart'`: one set that stays whatever symbol is loaded, as before; `widget.instrumentDrawings` is then null. See Drawings per instrument, below. |
| `drawingTemplates` | `DrawingTemplateStore` | none | (since 2.5.9) Saved drawing looks: a tool's default and named templates, from `openalgo-charts/workspace` (`DrawingTemplateRepository`). Without one no template control is shown. See Drawing toolbar, style templates and coordinates, below. |
| `drawingToolbar` | `boolean` | on with the rail | (since 2.5.9) The floating toolbar over the selected drawings on a desktop layout. |
| `workspaces` | `WorkspaceStore` | none | (since 2.5.10) Saved layouts and indicator templates: a `WorkspaceRepository` from `openalgo-charts/workspace`, or a host's own store, taken as a type only. Adds the Layouts menu (a top bar button, and a More sheet row on a phone) and templates in the indicator picker, and reopens the layout that was active when the page last closed. See Layouts menu and indicator templates, below. |
| `layouts` | `LayoutsController \| false` | a controller over this widget | (since 2.5.10) What the Layouts menu drives. A chart grid gives its charts `false` (no chart saves a layout of its own there) unless the host passes one controller for the whole grid, which every chart's menu then drives. `false` keeps `workspaces` for templates only. |
| `drawingStore` | `DrawingDocumentStore` | beside the layout with `persist`, else in memory | (since 2.5.9) Where each instrument's drawings are kept in `'instrument'` scope. Not a `ChartGridOptions` field: the grid gives each cell its own. |
| `locale` | `string` | the runtime's | BCP 47 tag for the numbers on the status line. |
| `symbolSearch` | `(query, { signal }?) => SymbolMatch[] \| Promise<SymbolMatch[]>` | the feed's `searchSymbols`, when it has one; else none | Called as the user types in the symbol box, after `SEARCH_DEBOUNCE_MS`. The second argument's `signal` aborts once a newer query or a closed picker makes the answer stale; a one-argument callback still works. Without a callback, a feed with `searchSymbols` (both OpenAlgo feeds) serves every picker: the top bar, the phone layout, typed entry, the watchlist and study symbol inputs. That lookup lists the exact symbol on the chart's exchange first, because Enter takes the first result. |
| `lookbackBars` | `number` | `DEFAULT_LOOKBACK_BARS` | Bars per load. |
| `now` | `() => number` | `Date.now` | The widget's wall clock in epoch milliseconds: the load window, the loading controller (unless `loading.now`, in UTC seconds, gives it its own), the status line and the bottom bar's clock and ranges. It shadows `ChartOptions.now`, the monotonic animation clock, which the widget does not pass to its chart. |
| `onOrder` | `(order: OrderRequest) => void` | none | Order entry from the right-click menu. Without it the menu draws no trade rows. |
| `movablePrimaryPane` | `boolean` | `false`, as in the engine | Pass `true` to let a trader move the price pane below its studies; the widget's own chrome (pane menu, status line, alerts, Objects panel) follows it wherever it sits. Leave it off while host code drives `widget.chart` with an explicit pane `0` for the price, or drop those zeros first. `createChartGrid` hands it to every chart it builds. See [scales-and-panes](scales-and-panes.md#moving-the-price-pane-opt-in). |
| `account` | `AccountStateSource` | none | Account summary in the status line (see `mountAccountSummary`). Omitted shows nothing; a source whose provider declares no accounts shows disabled with the reason. Hidden with the status line (`statusline: false`, and the compact mobile controls, which hide the status line). It only reads and switches accounts. |
| `styleNonce` | `string` | none | Response CSP nonce for the shared widget and dialog stylesheet. Style-attribute policy remains the host's responsibility. |
| `keyboardRoute` | `() => boolean \| undefined` | none | For hosts with several widgets: false silences this widget's chords and chart shortcuts, true sends them here, undefined keeps the usual rule (pointer or focus, or always for a `shortcuts` scope of `global`). Applies to a `ShortcutManager` instance too, shared or not. The chart grid sets it per cell. |
| `shortcutsEditor` | `boolean` | true | (since 2.5.10) The `?` panel lets the user change the widget's and the chart's chords, saved under `KEYMAP_KEY` when `persist` is on and applied at mount (over an asynchronous store, once it has answered). False lists them only and applies no saved chords. Leave the engine's `shortcuts.persist` off on a widget. |
| `captureRows` | `() => ReadonlyArray<MenuRow \| string>` | none | (since 2.5.10) More rows at the end of the capture menu, read each time it opens; a string starts a group. The chart grid fills it with Every chart rows; not a `ChartGridOptions` field. |

Confirm defaults against `WidgetOptions` in the typings rather than assuming.

## Mobile controls

`createWidget` always mounts one mobile handle. Mode `'auto'` observes the widget
container and the primary-pointer media query. It activates at 640 CSS px or less for
any pointer, and when `(pointer: coarse)` matches, also up to 960 px wide while the
container is under 600 px tall; a tablet in either orientation or a touch laptop keeps
desktop chrome. A container that drops to 0 wide or 0 tall keeps its last layout, an
unmeasured one starts on desktop, and a switch waits while a form field in the widget
(dialogs included) has focus. `'always'` stays active, and `'never'` keeps desktop
chrome. Size is read from the container, not the viewport.

The compact header provides symbol entry and intervals. The bottom bar provides Draw,
Studies, Objects and More according to the same `topbar`, `rail` and `indicators` options
as desktop chrome. More contains theme, chart settings and chart type (each type beside its
`chart-<type>` glyph since 2.5.10), and (since
2.5.10), while the widget's bottom bar is on, the market status and clock, the ranges, the
scale toggles and the timezone the hidden bar would show. A selected drawing
adds Properties, Lock or Unlock, and Delete. An active drawing tool adds Finish, Cancel,
Undo, Magnet and Stay in the Drawing sheet.

Both layouts share `ctx.draw`, `ctx.objects`, widget events, dialogs and the overlay stack,
so resizing does not copy or reset selection, drawings or undo state. `RailOptions.tools`
filters the mobile Drawing sheet to the same allowed tool ids as the desktop rail.

If `prefers-reduced-motion: reduce` matches, `createWidget` supplies `animZoom: false` and
`animAutoscale: false` only when the host omitted those options. Explicit values win.
`mountMobile` is public for custom composition and returns `{ el, active, refresh, destroy }`;
ordinary hosts should let `createWidget` wire and destroy it.

## The `Widget` handle

```ts
widget.chart;                        // Chart
widget.draw;                         // DrawingController
widget.instrumentDrawings;           // InstrumentDrawings, or null with drawingScope 'chart' (since 2.5.9)
widget.root;                         // the .oac-widget element
widget.context;                      // the WidgetContext every mounted piece was handed
widget.objects;                      // the owned base-tier ChartObjects inventory
widget.alerts;                       // the owned AlertController, including drawing anchors
widget.history;                      // the ChartHistory every undo control walks (2.5.6)
widget.series;                       // the primary SeriesApi, retained by setChartType
widget.symbol(); widget.exchange(); widget.interval(); widget.chartType(); widget.theme();
widget.variant();                    // the DataVariant in use, undefined for the feed's default series
widget.setSymbol(symbol, exchange?);
widget.setInterval(code);            // throws UnknownIntervalError for a code the registry lacks
widget.setDataVariant(variant);      // a new source: aborts, clears, reloads; undefined is the default
widget.setChartType(id);             // registered renderer or transform; retains handle, data, styles, scale and markers
widget.setTheme('dark' | 'light' | theme);
widget.openSettings();               // false when no dialog is registered under 'settings'
widget.openIndicatorPicker();
widget.openObjects();                // false after destruction; focuses the existing panel when open
widget.openAlerts();                 // desktop Alerts and mobile More use the same live list
widget.openDateNavigation();         // the Go to panel; false after destruction
await widget.goTo({ from, to? });    // DateNavigationResult; loads older history first
await widget.setRange('1D');         // a preset range: interval, fetch sized in sessions, view (since 2.5.10);
                                     // wider than the plot, it keeps its latest bars (clipped); All loads all history
widget.range();                      // the range in force; null once the interval is changed by hand
widget.getState();                   // WidgetState; rejects nonportable alert payloads
widget.restoreState(state);          // WidgetRestoreReport
await widget.reload();               // fetch again for the current symbol and interval
widget.on(event, cb);                // returns the unsubscriber
widget.off(event, cb?);
widget.destroy();                    // saves if persisting, removes the chrome, destroys the chart
widget.isDestroyed;
await widget.ready;                  // (since 2.5.10) the persisted layout applied and the first load started
```

**Transformed chart types.** With the transform tier imported, the chart type menu lists Heikin Ashi, Renko, Range bars, Line break, Point and figure and Kagi under a Transforms heading, and picking one has the chart transform the bars the widget loads, live (`chart.setSeriesTransform`); `chartType()` and the saved `chartType` are the transform's id, its options ride in `chart.series[].transform`, and a layout restores them. A widget whose host feeds `widget.series` itself (no `feed`) keeps point and figure and Kagi as renderers over the elements that host prepares, the 2.5.x contract, so nothing is transformed twice; the other four transform there too. A study's settings lead with a Compute on row (chart bars or underlying bars) while the chart transforms.

`getState()` returns `{ version: 1, symbol, exchange, interval, chartType, theme, variant?, chart: chart.getState(), rail: RailPrefs | null, panels?, savedBy? }`; `savedBy` (since 2.6.3) is the library version that wrote it, and a state without it, restored by `restoreState` or by `persist` on a reload, keeps the drag the widget was built with (its default or the host's `navigation.mousePan`) instead of the `mousePan: 'both'` every 2.6.2 state recorded by default; `variant` is present only for a non-default series, so a state without one (including every record saved before variants) restores onto the feed's default series, whatever variant the widget shows at the time, while one this build cannot read is refused before anything is applied. A persisted record whose variant this build cannot read opens on the default series without its saved view. The variant is part of the dataset, so a saved viewport lands only on the same variant too, and a `variant` bus event announces a change. The status line names a non-default variant (`.oac-statusline__variant`: localized "Regular hours", "Extended hours", "Adjusted prices", "Raw prices", then the provider's currency and unit names). `restoreState` validates field by field and returns `{ applied, reason?, chart?: RestoreReport }`; a saved viewport is applied only when the state was captured on the same symbol and interval, otherwise `stripView` drops it and the indicators and panes still land, and the drawings land on the state's own symbol (see Drawings per instrument). With `persist`, the state is written under `oac-widget:<namespace>:state` (debounced by `SAVE_DEBOUNCE_MS`, flushed on `pagehide` and on `destroy`) and the rail's preferences under `oac-widget:<namespace>:rail`. Since 2.5.10 those keys live in IndexedDB unless the host passes a synchronous `storage`. The widget is then built on its defaults, kept out of sight, and asks the feed for nothing until the store has answered. Then the saved symbol, interval, variant, chart type, theme, rail preferences, panels, layout and drawings are applied, and the first load goes out for the saved instrument only. `ready` settles at that point and never rejects. Options the host passed win, as before, and so does a symbol, interval or whole `restoreState` set before the store answered. A listener that throws on what the restore announces cannot stop it. Tabs on one namespace keep each other's saved drawings: the copy in memory follows the writes other tabs land, as `localStorage` reads did. A hidden page writes its layout only when a change is pending. A store that cannot be read within 4 s runs the session on memory and says so on the status line and in a toast. A refused write is reported on the status line and sent again with the next change. The writes pending when the page hides, on `pagehide` or on `destroy` are copied to a `localStorage` journal (`oac-widget-journal:<namespace>`) and replayed at the next load, because IndexedDB may not commit a transaction started while a page unloads. A page that offers IndexedDB but cannot open it stays on `localStorage`.

### Objects panel

`mountObjectsPanel(ctx, anchor?, opts?: ObjectsPanelOptions)` returns `PanelHandle`
(`el`, `close()`, `isOpen()`). `ObjectsPanelOptions` contains optional `objects:
ChartObjects` and `onClose`. The explicit model overrides optional
`WidgetContext.objects`; one must be provided, otherwise the mount throws a clear
missing-model error. Closing the panel releases only its subscription, and calls
`onClose` once. The host retains ownership of the model.

```ts
import { mountObjectsPanel } from 'openalgo-charts/widget';

const panel = mountObjectsPanel(widget.context, openButton, {
  objects: widget.objects,
  onClose: () => updateToolbarState(false),
});
panel.close();
```

Search matches name, kind and pane labels (displayed starting at 1, with the price
pane named **Price pane** in any slot, in the section headings and the move targets alike). Live updates
preserve search and action-button focus. Rows show visibility, drawing lock and
selection, and external-indicator data status. Only supported actions appear; an
action returning `false` or throwing reports through the existing toast. No primary
source removal control is offered. Settings reuse the widget's current chart,
indicator and drawing editors. Drawing actions use existing undo history.

Each pane section lists its stack in draw order, back to front (`objects.stack(pane)`),
a group at its first member's place and rows outside the stack after. A drawing row
notes **Behind the series** or **Above** and the row it sits on. Dragging a row onto the
upper half of another puts it under that row in paint order, the lower half over it;
`dragover` accepts only a drop `objects.canPlace` allows, marking the row
`is-drop-before` / `is-drop-after`, so an unpaintable drop is refused before release.
**Earlier** and **Later** step through the same order with `objects.place` (a source or
study steps between whole slots); rows outside the stack keep `reorder`. A drop onto a
row of another pane moves the row there first. A custom `objects` model without `stack`
keeps the list order.

Study policies reach the panel the same way: an unlisted study has no row, and a
protected one offers only the actions its policy allows. Elsewhere the widget greys the
context menu's settings and remove rows with the note "protected", greys the indicator
picker's remove button, declines the settings dialog with a toast ("{name} settings are
protected"), and leaves unlisted studies out of the picker's running list and the alert
source lists. See [study policies](core-api.md#study-policies).

Drawing policies reach the panel through the inventory: an unlisted drawing
(`policy.listed: false`) has no row, a read-only one (`policy.editable: false`)
has no Hide, Lock or Remove, and an unselectable one no select. Elsewhere in the
widget a read-only selection keeps its copy and duplicate actions while every
edit control is drawn disabled with the note "read-only": context menu rows, the
properties dialog (fields, lock, visibility, delete, restore defaults), the rail's
lock, eye and trash, and the mobile selection bar. The text and level editors
decline to open on it. In a selection that mixes the two, Cut, Delete and the trash
tooltip count only the drawings they take. **Group selected** is off for a
selection of read-only drawings only, and the alert editor's drawing picker leaves
unlisted drawings out. See [drawing policies](drawing-tools.md#drawing-policies).

The panel uses the shared overlay for pointer containment, focus trapping, Escape
and focus restoration. Its scrollable list fits the actual container, including
350 px and short hosts; search and footer remain reachable. All controls are text.
`createWidget` already includes `OBJECTS_PANEL_CSS`; a custom stylesheet must include
it along with the shared widget and dialog rules.

`widget.objects` is a base-tier `ChartObjects`, detailed in
[core-api](core-api.md#object-inventory-and-management). Custom profiles register
explicit operations there. `widget.destroy()` disposes its inventory; custom
hosts dispose their own. Indicator visibility persists in chart/widget layouts,
with omitted legacy visibility defaulting to visible. Host provider state and
callbacks require separate persistence and registration after replacement.

### Events

`on` takes a `WidgetEventName`; payloads are `WidgetBusEvents[K]`:

| Event | Payload | When |
|---|---|---|
| `symbol` | `{ symbol, exchange }` | The user picked one in the top bar or `setSymbol` was called. Also emitted on `widget.chart` so a link group can follow. |
| `interval` | `{ interval }` | Likewise. |
| `theme` | `{ theme, chartTheme }` | `setTheme` or the top bar's toggle. |
| `layout` | `{ reason, chartType? }` | Something `getState()` would now return differently: the chart type, a restored layout, a pane change. |
| `data` | `{ symbol, interval, bars, error? }` | A load finished, or failed (then `error` is the message and `bars` is 0). |
| `status` | `{ text, kind }` | The status line's transient message changed. |

Chart events stay on `widget.chart`, drawing events on `widget.draw`. The bus also carries `keymap:conflict` for `widget.context.bus.on`.

## Live history and reconnect recovery

The widget passes `BarSubscriptionOptions` to `feed.subscribeBars`: `seedFrom` continues the last loaded bar, and `onResync` requests authoritative history after a stream interruption. On resync it pauses display updates while buffering live bars, loads the current window with `BarsRequest.noCache: true`, merges the buffered observations, replaces the series with `setData`, restores the visible logical range, and seeds the replacement subscription from the merged last bar. Monitoring stays active during the fetch; a repeated reconnect starts a newer request and supersedes the earlier one. `withBarCache` forwards subscription options and honors `noCache`; custom wrappers must preserve both. Never replay older gap-fill bars through the tail-only `series.update` path.

For overlapping timestamps the merge preserves the history open, combines high/low extrema, uses the latest buffered close, and takes the maximum of the volume snapshots. Bars without buffered updates retain authoritative history. The overlap merge is conservative: a buffered whole candle may retain a seed extreme corrected by history, and does not establish exact snapshot/tick ordering or reconstruct unseen trades. The replacement seeded subscriber is installed before releasing the previous subscription.

An automatic refresh that fails or returns no bars keeps the previous chart visible, reports stale history in the status line and emits a `data` error. Display updates remain paused while buffering and reconnect monitoring continue. `widget.reload()` is the manual retry; requests keep bypassing the cache until a current load succeeds. Same-context manual reload and automatic recovery preserve the visible time anchor. Stale results and callbacks are guarded after symbol/interval changes or destruction. The host owns closing the feed itself.

## `WidgetContext`

What the shell hands every mounted piece, and what a host's own panel wants: `chart`, `draw`, `root`, `document`, `theme` (`'dark' | 'light'`), `chartTheme`, `keymap`, `bus`, `storage` (a `WidgetStorage`), `locale`, `toast(message, kind?)`, `openOverlay(el, opts?)` (returns the closer), `status(text, kind?)`, `tips`, `overlays`, `symbol()` (`{ symbol, exchange }`), `interval()`, and optionally `objects`, `alerts` and `history` (the chart-wide `ChartHistory`; a dialog that previews live wraps its session in `ctx.history?.group(label)`).

A dialog module of your own: build the panel with `createElement`, hand it to `ctx.openOverlay(el, { anchor, placement: 'below' })` or `{ placement: 'center', modal: true }`, stop propagation of its own `keydown` (except Escape and Tab) and `pointerdown` so the chart's pointer capture does not eat a click, and register chords in scope `'overlay'` if it wants any while open. Register it with `registerWidgetDialog(name, mount)` to have the shell open it by name.

## Tokens and styling

One `<style>` element per document (`WIDGET_STYLE_ID`), every rule scoped under `.oac-widget`. Colours, spacing, radius and font are `--oac-` custom properties produced by `widgetTokens(theme)` and written inline on the widget root by `applyTokens`; the colours derive from the active `ChartTheme` (`background` stepped for panels, `axisLine` / `paneSeparator` for borders, `axisText` for text, `lineColor` for the accent, `upColor` / `downColor` for buy and sell), so the chrome and the canvas cannot disagree, and `setTheme` rewrites them. Names: `bg`, `panel`, `panel-2`, `elev`, `elev-2`, `elev-3`, `bd`, `bd-soft`, `bd-hover`, `tx`, `tx-strong`, `mut`, `faint`, `acc`, `acc-2`, `on-bg`, `on-bd`, `ring`, `ring-soft`, `buy`, `sell`, `amber`, `danger`, `scrim`, `shadow`, `sb-thumb`, `sb-thumb-hover`, `font`, `mono`, `fs`, `radius`, `rail-w`, `topbar-h`, `status-h`, `ctl-h`. Because the tokens are inline declarations, a host stylesheet override needs `!important` (`#terminal .oac-widget { --oac-font: ... !important; }`); override tokens, never internal class names. Icons come from the draw tier (`iconSprite`, `iconUse`, `chromeIconSvg`, `chartTypeIcon`), so the rail, its flyouts, the active tool's cursor, the menus and the dialogs share one glyph source; since 2.5.10 no widget file draws a picture of its own. The chart type menu and button show each type's glyph, and the theme button is a sun (on the dark theme) or a moon, its tip and accessible name saying the theme a click switches to. The chrome meets the UI standard in [themes-and-styling](themes-and-styling.md#host-chrome-the-ui-standard) by construction.

### Content Security Policy

Pass the host's fresh response nonce as `createWidget(container, { styleNonce: requestNonce })`. The widget and dialogs use one sheet per document, with the `.nonce` IDL property assigned before CSS is filled or the element is inserted. The helper is `injectWidgetStyles(doc, extra?, nonce?)`; existing two-argument calls still work.

An illustrative style policy is `style-src-elem 'nonce-RESPONSE_NONCE'; style-src-attr 'unsafe-inline'`, where `RESPONSE_NONCE` is the same unpredictable value generated for this response. The nonce authorizes the stylesheet; inline theme/layout styles need a separately considered attribute policy. This is not a complete policy for scripts or other resources. The first-use parts (Packaging facts) are module scripts beside the tier file: `script-src` allows them by origin or by a path ending in `/`, never by file name, since each name carries a content hash that changes from release to release.

An empty or whitespace-only SSR `<style id="oac-widget-css" nonce="...">` is filled in place, retaining the existing nonce even if the option differs. Put its nonce in the original HTML to avoid a parser CSP violation before hydration. Populated host CSS and its nonce are preserved unchanged; if supplying that sheet yourself, include `WIDGET_CSS`, `DIALOG_CSS` and `OBJECTS_PANEL_CSS`. Read a connected element's `.nonce`, since the browser can hide its content attribute.

## Custom rail tools

`registerDrawingTool` from `openalgo-charts/draw` **before** `createWidget`, then name the id in `rail.tools` (and `rail.favorites` to pin it). The rail reads the registry once when it builds: an id it cannot find is not shown, and an unknown favourite is dropped. A custom id appears in the rail only where `RAIL_GROUPS` places it, so a tool outside every group is reachable by pin, chord or `draw.setTool`. The rail labels the button with the tool's `name`; a glyph is drawn when `DRAWING_TOOL_ICONS` has the id. A tool's `shortcut` is bound through the widget keymap and listed in the `?` panel; a conflicting binding is reported, not silently overridden. Its `settings` schema decides what the properties dialog shows, so a control exists only for a field the tool's `draw` reads.

## Packaging facts

`createAlertUi(container, options: AlertUiOptions): AlertUi` mounts the shared
alert editor and list over an existing chart. Supply the host-owned `chart`,
`draw` and `alerts` controllers and a positioned container with a real size.
It exposes `openList`, `openEditor`, `close`, `isOpen`, `setTheme` and `destroy`.
`onOpenChange` follows the whole nested dialog stack, so capture-phase host
shortcuts can stay suspended until every dialog closes. `theme`, `chartTheme`,
`locale` and `styleNonce` are optional. Destroying this UI leaves its chart and
controllers alive; destroying the chart disposes the UI automatically.
Delivery and persistence remain the host's responsibility. Observe
`alert:triggered` for delivery and `alerts:checkpoint` plus lifecycle events for
persistence. Restore the complete chart document once, with the drawing and
alert controllers already attached. Do not restore drawings again afterward.

- `package.json` `exports['./widget']`: `types: ./dist/widget/index.d.ts`, `import` and `default`: `./dist/openalgo-charts.widget.mjs`. Listed in `sideEffects` (importing registers the dialogs).
- `rollup.config.js`: `openalgo-charts` and every `openalgo-charts/<tier>` are external for tier builds and emitted as sibling paths (`./openalgo-charts.mjs`, `./openalgo-charts.draw.mjs`), so `dist/` serves with no import map. The widget must never inline the base or the draw tier; `check-dts.mjs` fails a build whose `dist/widget/index.d.ts` declares `Chart` or `DrawingController`.
- `.size-limit.json`: `Widget tier` row (the bundle alone), `Widget first-use parts` row (every part, by the glob `dist/openalgo-charts.widget.*.mjs`, since a part's name changes with its content) and `Widget terminal` row (base + draw + indicators + widget); `Everything` includes the widget. Read the budgets there and measure with `npm run size`; never quote either from memory.
- A page with no module support loads the widget from the script-tag build: `openalgo-charts.standalone.js`, `openalgo-charts.draw.standalone.js`, then `openalgo-charts.widget.standalone.js`, and calls `OpenAlgoCharts.widget.createWidget`. That file bundles the first-use parts below rather than fetching them, since a classic script cannot share a split chunk. See [bundling-and-tiers](bundling-and-tiers.md).
- Parts that load on first use (since 2.5.10, `src/widget/lazy.ts`): UI a plain widget never opens is not in `openalgo-charts.widget.mjs` but in files beside it, `openalgo-charts.widget.<part>-<hash>.mjs`, fetched with `import()` the first time it is needed. A part resolves against the tier's own URL, so `dist/` or a CDN path needs nothing more and a bundler splits it the same way; under CSP, `script-src` allows the tier's origin as it already must. Once a part has arrived it opens synchronously; a part that cannot load says so in a toast each time it is asked for (a browser keeps a failed module fetch until the page reloads). While a part loads, a control pressed again asks once, the last control pressed is the one answered, and a request the user has moved on from by the time it arrives (a press elsewhere, Escape, or typing into another field) opens nothing (`usePart` and `PartAsk` in lazy.ts). Its rules join the widget's one stylesheet (`addWidgetStyles`), keeping that sheet's nonce. The `Widget tier` size row measures the tier file, which keeps everything a widget loads before a user opens a part (`preserveEntrySignatures: 'allow-extension'`); the file then also exports, under minified names, the shell helpers the parts import. Those are no API: no declaration names them, and `npm run skills:coverage` counts declared exports only. Because those names change from build to build, a tier file works only with the parts built with it; the hash in a part's name is of its content (`chunkFileNames` in rollup.config.js), so a new tier file asks for its own parts and never meets one a cache kept. A host serving `dist/` itself serves the tier files (names unchanged across releases) with revalidation and may cache the hashed parts for a long time; a CDN URL pins the exact version, never a range. Never refer to a part by its full file name: a test route or a size row matches it by glob, and a CSP allows its directory. `npm run build` empties `dist/` first, so no part from an earlier build is packed or measured.

## Pitfalls

- **Expecting the engine to have grown a UI.** Only `openalgo-charts/widget` has one. `createChart` still returns a bare canvas chart.
- **Deep-importing the widget or the draw tier.** Two `DrawingController` classes, two tool tables, `widget.draw` not assignable to your variable. Package specifiers only (hub rule 6).
- **An indicator picker that is empty.** The indicators tier was not imported. `import 'openalgo-charts/indicators'`.
- **Container with no size.** Same as `createChart`: give it a height before the call.
- **Two widgets sharing one persistence namespace.** Pass a distinct string to `persist` for each.
- **An interval code the registry does not know.** `interval`, `intervals` and `setInterval` throw `UnknownIntervalError`; register the code first.
- **Rendering the widget from framework state.** Create in a mount effect, hold in a ref, `destroy()` on cleanup.

## Related

[core-api](core-api.md) · [drawing-tools](drawing-tools.md) · [settings-and-menus](settings-and-menus.md) · [indicators](indicators.md) · [themes-and-styling](themes-and-styling.md) · [bundling-and-tiers](bundling-and-tiers.md) · [react-integration](react-integration.md) · [pitfalls](pitfalls.md)

## Shared loading in 2.1.6

`WidgetOptions.loading?: DataLoadingOptions` configures the base controller.
`Widget.dataController` is `DataLoadingController | null`, null without a feed.
The widget binds history/paging/stream updates, observable chart and study statuses,
Retry controls and context propagation. Same-context reload preserves the visible
time anchor; only source changes reset to the preferred initial window.
`dataController.setPaused(true)` fences display writes for a custom replay owner.
See [host-integration](host-integration.md) for unmount and replay ordering.

## Branding and watermark defaults (2.1.9)

The widget inherits `ChartOptions.branding` and `ChartOptions.watermark`. Its existing
symbol/interval changes update `chart.setDataContext`, which supplies automatic watermark
text. No second text store or manually attached logo is needed. The default corner mark
is visible on both layouts, while the background watermark starts off. Appearance settings
operate through the same chart schema and chart state used by bare-chart hosts. See
[primitives-and-plugins](primitives-and-plugins.md#chart-branding-and-optional-text-watermark-219)
for the APIs, migration and interaction checks.


## Chart controls added in 2.5.3

`WidgetOptions.panels` defaults to true: Data and Objects share a closed-by-default
resizable dock, switching to an overlay sheet on narrow hosts. `panels: false`
keeps the Objects popup and omits Data. `Widget.openDataWindow()` opens readings;
`openObjects()` opens its neighbour. Optional `WidgetState.panels` saves selected
view and width; old records stay valid. No saved-state version bump is needed.

- `readDataWindow(chart, time?, options?)` returns `DataWindowSnapshot` with
  `DataWindowSection` and `DataWindowRow` records. `DataWindowOptions` carries locale
  and translation. Values are exact-time OHLC/volume/OI and plot readings, including
  plot offsets and candle-plot close columns. Absence is null, formatted Unavailable.
- `mountDataWindow(context, host)` returns `DataWindowHandle` with refresh/destroy.
  It observes `crosshair:readout`, data, object and timezone changes without replacing
  a host's crosshair callback; hover does not copy the whole history each time.
- `mountPanelDock(context, stage, options)` returns `PanelDockHandle`. Types are
  `PanelDockId`, `PanelDockState`, `PanelDockContent`, `PanelDockOptions` and
  `PanelDockHandle`. Content factories mount into their host and return destroy().
  `sanitizePanelDockState` accepts unknown stored input and bounds the width.
- `createObjectsPanelContent` returns `ObjectsPanelContent` (element, initialFocus,
  destroy) for a host panel without popup furniture. `mountObjectsPanel` is retained.
- `mountSymbolPicker` uses `SymbolPickerOptions` and returns `SymbolPickerHandle`.
  The existing `SymbolMatch` adds optional assetClass, iconUrl and contractGroup
  with explicit contract SymbolMatch records. `SymbolSearch` stays query-only.
  `safeSymbolIconUrl` accepts HTTPS and root-relative URLs, rejects credentials.
  Async queries are fenced by query, chart context and mounted lifetime.
- `mountQuickEntry` uses `QuickEntryOptions` and returns `QuickEntryHandle`. The
  host's enabled() decides chart ownership. `typingNavigation: false` opts a widget
  out. Existing shortcuts, overlays, drawing placement, editors, modifiers and IME
  retain precedence. Bare numeric input means minutes; invalid intervals stay open.
- `createColorPicker` uses `ColorPickerOptions`, returns `ColorPickerHandle`, and
  preserves existing alpha. Pass openOverlay from the context inside a dialog.
  `FormOptions.openOverlay` threads the same opener through generated forms;
  `FormHandle.destroy()` disposes child controls. Destroy before removing a form.
- The indicator picker lists running instances and removes only the chosen ID.
- `AlertUi.context` exposes the context for hosts reusing other widget controls.

`DATA_WINDOW_CSS`, `PANEL_DOCK_CSS`, `SYMBOL_PICKER_CSS`, `QUICK_ENTRY_CSS` and
`COLOR_PICKER_CSS` can be included individually. `WIDGET_COMPONENT_CSS` combines
all component styles, including dialogs and indicator-picker additions. Include it
beside `WIDGET_CSS` when managing styles yourself; apply widget tokens to the root.
createWidget/createAlertUi inject the complete component styles automatically.

## Date and range navigation (2.5.4)

`widget.goTo({ from, to? })` shows a date, or an explicit range, in UTC seconds.
It waits for a load in flight, loads older history through
`dataController.loadMore(until)` until the request is covered, then places it
with `chart.setVisibleLogicalRange`. Since 2.6.2 a gap before the first loaded
bar that no session trades in (a weekend, a holiday, the hours before another
venue opens) does not count as missing history when the chart has a session calendar
(`chart.setSessionCalendar`, or an instrument's hours): it sets no `history` on
the result, and no older page is loaded for it. The status still follows the
rest of the rules (`no-data` for a range wholly inside the gap, `partial` with
`clipped` for one wider than the plot). Without a calendar, or when the calendar
finds no session at all, any gap before the first bar is loaded or reported as
short history, as before. A date is centred at the current zoom, and
kept left of the newest bar's normal margin; a range fills the plot, centred at
the widest bar spacing when short. Placement runs after the accepted load, so
later live bars and refreshes keep its anchor. A newer request, a symbol or
interval change, `restoreState` onto another context, or `destroy` settles the
promise `{ status: 'cancelled' }` without moving the view, and so does closing the
panel while its request loads. So does a pan or zoom while an older page loads,
whether it comes from a gesture, a key, a linked chart or the host's own
`setVisibleLogicalRange`: the view is wanted elsewhere, and the older bars still
arrive without moving it. The widget's own move that keeps the bars in view still
when a refresh lands does not count; nor does a move of the blank chart during a
first load, which that load's arrival resets. The bottom bar's **Go to** button (the top
bar's with `bottombar: false`, since 2.5.10) and the mobile **More** sheet open the
panel (`openDateNavigation()`); on a tick or volume interval each is greyed with the
reason and `openDateNavigation()` returns false. Daily and longer intervals show date fields only, since a time cannot change
which bar a date names. The panel closes when the interval or the chart timezone
changes under it, since its fields and hint were built for both, and it clears its
loading line when its request is cancelled.

`DateNavigator` is the DOM-free coordinator behind it, for custom hosts:

```ts
import { zonedStringToUtcSeconds } from 'openalgo-charts';
import { DateNavigator, openDateNavigation } from 'openalgo-charts/widget';

const navigator = new DateNavigator({
  chart: () => currentChart,                  // or a Chart; re-read after each load
  // Prepend bars reaching `time` and say what happened. loadMore never rejects:
  // it records a failure in the state, so read the state rather than assume progress.
  loadHistory: async time => {
    const first = controller.bars()[0]?.time;
    await controller.loadMore(time);
    const state = controller.getState();
    if (state.historyStatus === 'error') throw state.historyError;
    if (state.historyStatus === 'limited') return 'limited';
    if ((controller.bars()[0]?.time ?? Infinity) < (first ?? Infinity)) return 'loaded';
    return state.hasMore === false ? 'exhausted' : 'empty';
  },
});
// A date typed on the chart's own clock (IST unless the host set another zone).
const from = zonedStringToUtcSeconds('2024-01-15', currentChart.timezone());
const result = await navigator.goTo({ from });
openDateNavigation(ctx, anchor, {
  navigate: target => navigator.goTo(target),
  cancel: () => navigator.cancel(),           // the panel was closed while loading
});
```

The navigator cannot tell the host's own view moves from the user's, so a custom
host that wants a pan or zoom to drop a loading request watches for it around its
loader, as the widget and the reference host do, and skips the moves it makes
itself for arriving bars:

```ts
loadHistory: async time => {
  const moved = () => { if (!keepingViewForData) navigator.cancel(); };
  const offs = [chart.on('pan', moved), chart.on('zoom', moved)];
  try { await controller.loadMore(time); } finally { for (const off of offs) off(); }
  // ...then read the state as above
},
```

| Export | Kind | Purpose |
|---|---|---|
| `DateNavigator` | class | `goTo(target)`, `cancel()`, `destroy()`. One request at a time; a new one cancels the previous. |
| `DateNavigatorOptions` | type | `chart` (a `Chart` or a getter), optional `loadHistory(time, signal)`, optional `interval()` (default: the data context). |
| `DateNavigationTarget` | type | `{ from, to? }`; `to` is inclusive (bars opening at or before it, a bar a day or longer counted from its local midnight). |
| `DateNavigationResult` | type | `{ status, from?, to?, history?, clipped?, error? }`; `from`/`to` are the placed bars' open times. |
| `DateNavigationStatus` | type | `placed`, `partial`, `no-data`, `unsupported`, `invalid`, `cancelled`, `error`. |
| `HistoryReach` | type | What one loader call achieved: `loaded`, `empty`, `exhausted`, `limited`, `unavailable`. |
| `openDateNavigation(ctx, anchor, options)` | function | The compact panel (Date or Range, date and optional time in the chart timezone). Returns `PanelHandle`; closes once placed and keeps any other outcome's reason in place. |
| `DateNavigationDialogOptions` | type | `navigate(target)`, optional `cancel()` (the panel was dismissed, or closed by an interval or timezone change, while its request loaded; not called when its chart was destroyed), optional `pending: { target, result }` (show and report a request already under way, for a host whose load rebuilt the chart and closed the panel that started it), and `onClose()`. A closed panel reports nothing. |
| `DATE_NAVIGATION_CSS` | const | The panel's styles; part of `WIDGET_COMPONENT_CSS`. |

Rules the coordinator applies:

- Bars of a day or longer count from the local midnight of their first day, so a
  date lands on its own daily bar whether the feed stamps midnight or the session
  open. They end at the local midnight after their last day, so a day of 23 or 25
  hours around a clock change keeps its own bar. Shorter bars keep their stamp; an
  instant in an overnight or weekend gap moves to the next session; a range with
  no bar inside it is `no-data`.
- A date names the bar the axis labels with that date. West of UTC a daily bar
  stamped at UTC midnight is the previous evening on the chart's clock, so the
  axis, crosshair and data window label it with the previous date, and that is
  the date that names it. Set the chart timezone to `UTC` for such a feed when its
  bars should read, and be found, by their UTC date.
- Only time-bucketed intervals navigate (fixed and calendar); tick, volume and
  unknown codes are `unsupported`. The view never moves for `no-data`,
  `unsupported`, `invalid`, `cancelled` or `error`.
- `partial` with `history` means the source stopped before the requested start:
  `exhausted` (nothing older), `empty` (inspected windows held nothing; older
  history may exist), `limited` (retention) or `unavailable` (no loader, replay,
  a paused controller). `partial` with `clipped` means the range is wider than the
  plot at its narrowest spacing; its start is in view.
- History is never loaded during replay (`isReplaying(chart)`), and a date beyond
  the replay cursor is `no-data`. A chart linked through `createLinkGroup` follows
  the placement by time, like any other viewport change.
- A loader that reports `loaded` without adding older bars stops the loop as
  `empty`, so a misbehaving host cannot keep it spinning.

## Chart grid (2.5.4)

`createChartGrid(container, options)` returns a `ChartGrid`: one widget per cell on a
rows by columns grid, with splitters, one active cell, linking through the base
`LinkGroup`, and the portable `WorkspacePayload` of `openalgo-charts/workspace`. It is
part of the widget tier, not a new one. Source of truth: `src/widget/grid.ts`. Its cells
carry no bottom bar of their own (since 2.5.10). `bottombar: true` puts one under the grid,
acting on the active chart.

```ts
import { createChartGrid } from 'openalgo-charts/widget';
import { parseWorkspacePayload } from 'openalgo-charts/workspace';

const grid = createChartGrid('#desk', { feed, symbol: 'RELIANCE', exchange: 'NSE', interval: '5m',
  preset: '2x2', links: { crosshair: true, viewport: true }, persist: 'desk' });
grid.setPreset('1x3');
const report = grid.applyWorkspace(parseWorkspacePayload(fileText)); // { applied, reason? }
```

- `ChartGridOptions` is `WidgetOptions` (every cell's options) minus `keyboardRoute`,
  `drawingStore` and `captureRows`, with its own `feed` (below), plus `preset` (any
  `ChartGridLayoutId`, default `1x1`), `links` (`LinkOptions`: the first group's channels
  and every new group's), `compactWidth` (default 640 CSS px, 0 off), grid-level
  `persist`/`storage`, and (since 2.5.10) `toolbar` (the grid bar, default false) and
  `presets` (the layout ids its picker offers, in order; default every `CHART_GRID_LAYOUTS`
  entry; an empty list leaves the Layout control out), `bottombar` (one bar under the grid
  for the active chart, default false; the charts then leave Go to and the market status to
  it) and `workspaces` and `layouts`: with the grid bar the grid keeps one layouts controller
  over the whole desk, or drives the one `layouts` passes, from a Layouts control at the end
  of the bar, and no chart has a Layouts button; without the bar it keeps none, `workspaces`
  gives the charts templates only and a `layouts` controller drives each chart's own
  button. No chart saves a layout of its own. Under the grid's bottom bar the charts also
  leave Go to out of the phone More sheet. `symbol`, `exchange`, `interval` and `chartType` seed
  the first cell. Cells default to `mobile: 'never'`, because a cell in a split is often
  narrower than the phone threshold.
- `feed` is one `DataFeed` for every chart, or a function
  `(chart: { id, historyPeriod? }) => DataFeed` called once per chart as it is built, for a
  source that answers by period: the grid keeps each pane's `historyPeriod` (from an
  applied payload, or copied from the active chart when a preset adds charts) and writes
  it back in `getWorkspace()`, but only such a function honours it. Return the same feed
  object for charts that should share one request pool.
- Layouts (since 2.5.10): `CHART_GRID_LAYOUTS` maps each `ChartGridLayoutId` to a
  `ChartGridLayoutSpec` (`rows`, `columns`, `slots` of `ChartGridLayoutSlot` in reading
  order, `rowWeights`, `columnWeights`), 26 layouts from 1 to 16 charts: the uniform `1x1`
  to `4x4` (also `CHART_GRID_PRESETS` as `[rows, columns]`, 16 entries, the 2.5.9 six
  first) and the uneven `left-2`, `right-2`, `top-2`, `bottom-2`, `left-3`, `top-3`,
  `left-4`, `top-4`, `corner-5`, `corner-7` (`ChartGridUnevenLayout`).
  `CHART_GRID_LAYOUT_NAMES` gives each English name, which is also its message key.
  `setPreset(id)` keeps surviving cells in reading order (same widget instances); in an
  uneven layout the active chart takes the large slot, and stays even when it sat past
  the charts that fit. It builds new cells on the active chart's instrument in its link
  group, destroys the rest and resets weights to the layout's; an unknown id throws. Spans
  from a saved payload are drawn and splitters stop where a span crosses.
- `ChartGridCell` (`id`, `widget`, `element`, `row`, `column`, `rowSpan`, `columnSpan`,
  `historyPeriod`, `linkGroup`); `cells()`, `active()`, `setActive(id, { focus })`,
  `layout()` (`ChartGridLayout`), `linkOptions()` (the active chart's group),
  `setLinks(patch)` (the active chart's group, or every group when it is in none;
  switching symbol, interval or chart type on adopts the active chart's), `maximize(id?)`,
  `restore()`, `maximized()`, `swap(a, b)`, `linkGroups()`, `setLinkGroup(cell, group |
  null)`, `addLinkGroup(cell, { name?, links? })`, `setGroupLinks(group, patch)`,
  `renameLinkGroup(group, name)`, `shareDrawings(cell)`, `takeScreenshot()`,
  `downloadScreenshot(filename?)`, `theme()`, `setTheme()`, `compact()`, `restored()`,
  `ready` (since 2.5.10), `destroy()`.
- Events (`ChartGridEvents`, `ChartGridEventName`): `active` (from `setActive`, and when
  a preset or an applied workspace moves the active chart), `layout` (`preset`,
  `weights`, `workspace`, `compact`, `maximize`, `swap`), `links` (the active chart's
  channels after a link, group or active chart change), `theme`.
- Persistence (`persist`): preset, link, group, theme, active chart, instrument, swap,
  keyboard splitter and drawing add or remove changes are written before the task ends.
  (since 2.5.10) The user's chords are the desk's: a change in one chart's shortcuts
  editor is applied to every chart and kept under `KEYMAP_KEY` in the grid's storage. Pans,
  zooms and drags are debounced (`SAVE_DEBOUNCE_MS`) and flushed when the page hides
  (`visibilitychange`), on `pagehide` and on `destroy`. A stored desk that fails to
  restore (a study or chart type registered later, say) is not overwritten: the grid
  falls back to `preset`, toasts the reason on the active chart, and `restored()`
  returns `{ applied: false, reason }` (null when nothing was stored). The stored desk
  stays until the user changes the grid; data loads and focus do not count. Since 2.5.10
  the default store is IndexedDB, as for one widget, and `storage` takes an
  `AsyncStorageLike`. The grid is built from `preset` out of sight and loads nothing until
  the store answers, then applies the desk (or loads the preset's charts on `symbol`) with
  the desk's chords. `ready` settles then and never rejects, and `restored()` is null until
  it has. A workspace applied before `ready` wins over the stored one. A desk 2.5.9 left in
  `localStorage` is copied in once and left there. `storage: localStorage` keeps it
  synchronous. A hidden page writes the desk only when a change is pending; `pagehide` and
  `destroy()` always write it.
- Keyboard: only the active cell answers. Pointer down or focus inside a cell makes it
  active. A key pressed with the focus on the page body, while the pointer is over the
  grid, goes to the active chart; a focused splitter or tab keeps its arrow keys.
- `WidgetOptions.keyboardRoute` is the hook behind that: `() => boolean | undefined`.
  False silences the widget's chords and its chart's shortcuts, true routes them there,
  undefined keeps the usual rule: pointer or focus, or always when the host's
  `shortcuts` scope is `global`. A `ShortcutManager` instance is routed too; one
  instance shared by several widgets (every grid cell gets the same options) is wrapped
  per widget, so rebinding it still reaches them all. A host with several plain widgets
  can use it.
- `getWorkspace()` returns a JSON `WorkspacePayload` that `parseWorkspacePayload` accepts:
  slots, weights, preset, active pane, sync, per-pane chart state, `settings['widget.theme']`,
  rail magnet/stay and `historyPeriod` when the chart has one. `volume` is written false
  and `comparisons` empty: a widget draws neither. `applyWorkspace` checks the whole
  payload first (size, slots, overlap, weights, intervals, chart types, studies, text
  history periods, no comparisons, within each link group, linked symbols, intervals and
  chart types that agree),
  builds and restores every new cell off screen, and on the first failure destroys them,
  aborting their history requests, and returns `{ applied: false, reason }` with the old
  cells untouched. Pass untrusted input through `parseWorkspacePayload` first.
- Linked viewports ignore moves caused by freshly loaded bars, so a follower on another
  interval is not squeezed; views converge on the next pan or zoom. The linked window is
  kept as times, read from the chart last navigated, and moves with that chart's new
  bars. After a linked navigation a resize keeps each chart on the window it showed: the
  engine keeps the right edge, so a chart following new bars keeps following, and the
  grid puts the span back rather than the bar width, so charts of different widths still
  agree. A chart shown from behind the compact tabs takes the linked window. The window is
  forgotten when its chart changes instrument or is removed, and when viewport linking
  is switched on, which starts without one until the next pan or zoom. A linked symbol
  is the symbol and exchange together, so a change of exchange alone (one ticker on NSE
  and BSE) reaches the followers.
- Below `compactWidth` only the active cell shows, with a tab strip to switch; splitters
  hide. `CHART_GRID_CSS` is part of `WIDGET_COMPONENT_CSS`.
- Grid bar (since 2.5.10, `toolbar: true`; it loads into a strip laid out at its height,
  and its menus load when one first opens, see Packaging facts): Layout picker (tiles
  from `layoutIconPath` over each layout's slots, one row per chart count, arrows, Home, End, a caption naming
  the focused tile), Maximize, Link menu (groups, Not linked, New group, Rename group,
  channel toggles including Nearest bar, Share this chart's drawings) and Capture
  (download, copy), and with `workspaces` a Layouts control at its end: the widget's
  Layouts menu over the whole desk, naming the held layout, with a dot and a spoken status
  while it is unsaved or failing. Menus live in an overlay layer over the whole grid with
  the widget's own controls.
- Maximize is a view, not saved: other cells stay alive, the maximized chart keeps its
  window through the resize, and a preset or applied workspace restores. `swap` trades
  places and spans and keeps the page order equal to the reading order. Drag a cell's bar
  background onto another cell to swap; double click it to maximize. Chords on each
  cell's keymap (group Chart grid): Alt+Enter maximize or restore, Escape restore
  (layered), Alt+Shift+Arrow activate the neighbour, Mod+Shift+Arrow swap with it.
- Link groups: up to 16, each a `LinkGroup` plus a `DrawingLinkGroup`; a chart is in one
  or none. Letters A to P are kept for life and across save and restore. Each cell's bar
  shows a mark with the letter on a hue once more than the starting group exists. Saved
  as `sync.groups` and `pane.linkGroup` only when groups say more than the flat flags; the
  flat flags are then those of a group holding every chart, else all off. A group nobody
  named is saved under the name it shows and reads back unnamed. Drawings made before the
  switch stay private until `shareDrawings`.
- Capture: `takeScreenshot()` composes each chart's own screenshot at its place at the
  device ratio and returns null while one chart is shown; `downloadScreenshot()` returns
  false on no image or a tainted canvas.
- Dense cells: below 560 by 340 CSS px, in any layout, a cell hides its rail and keeps a
  one-row top bar; maximize brings the full chrome back.
- Saved desks (since 2.5.10): a desk layout is `getWorkspace()` with each chart as
  `widgetLayoutTarget` writes one (no view, no alert bookkeeping) and without the focus,
  so an opened desk makes its first chart active. Changes are heard per chart and again
  after `preset` or `workspace` layout events; a change in the quiet period is written on
  hide and `pagehide`; the layout that was active reopens once `ready` settles, unless
  `applyWorkspace` was called first (a hand-off, a file), whose desk stays; a stopped
  autosave or a conflict is said once on the active chart's status line; the grid
  destroys only its own controller.
- Bottom bar (since 2.5.10, `bottombar: true`): `mountBottombar` in a strip under the
  charts, its menus in the grid's overlay layer, targeting `active().widget`, read again on
  `active`. Go to opens the go-to panel over the whole grid, above the bar.

## Layouts controller (since 2.5.10)

`createLayoutsController(store, target, options?)` holds one saved layout for one widget or
one chart grid. It is DOM-free: a menu drives it and renders its state. Source of truth:
`src/widget/layouts.ts`. `store` is a `WorkspaceStore` (`WorkspaceRepository` from
`openalgo-charts/workspace`, or a host's own); the widget tier imports that tier as types
only, so the workspace bundle loads only in a host that passes a store.

```ts
const layouts = createLayoutsController(repository, {
  capture: () => grid.getWorkspace(),
  apply: payload => grid.applyWorkspace(payload),
}, { autosaveDelay: 1000 });
const catalog = await layouts.reload();
if (catalog.activeWorkspaceId) await layouts.open(catalog.activeWorkspaceId);
```

- `LayoutTarget`: `capture(): WorkspacePayload`, `apply(payload): LayoutApplyReport`
  (`{ applied, reason? }`; a refused apply must change nothing), an optional
  `subscribe(listener)` for the user's changes (without it the host calls `changed()`), and
  (since 2.5.10) an optional `suspended()`: while it is true (a replay) autosave waits, `open`
  rejects and `state().suspended` is true; the listener announces when it turns false. A
  save the user asks for still goes through. For one widget, `widgetLayoutTarget(widget)`
  (since 2.5.10) captures its state in the one-chart form without the viewport, bar spacing,
  pinned price ranges or the alerts' bookkeeping (last bar judged, last touch and trigger;
  an alert's `state` stays), applies a one-chart layout through `restoreState` (the rail's
  `magnet` and `stay` too; it clears the undo history as loading any layout does), refuses
  up front a layout of several charts, with comparisons, or naming an interval, chart type
  or study the page cannot show, and is suspended while a replay runs.
- `LayoutsController`: `store`, `state()`, `subscribe(listener)`, `reload()`, `open(id)`,
  `save()`, `saveAs(name)`, `overwrite()`, `rename(id, name)`, `duplicate(id, name)`,
  `remove(id)`, `setAutosave(enabled)`, `changed()`, `flush()`, `destroy()`. Operations run
  one at a time, in call order. `reload()` resolves with a copy of the catalog.
- `LayoutsState`: `catalog` (the controller's own, to read and not change), `layoutId`,
  `revision` (what the next write into the held layout is checked against), `dirty`,
  `busy`, `suspended` (since 2.5.10), `conflict`, `autosave` (`LayoutAutosaveStatus`: `off`, `pending`, `saving`,
  `saved`, `failed`) and `error`. `LayoutsControllerOptions.autosaveDelay` (ms, default
  1000; a value that is not a finite number takes the default) is the quiet period before
  the target is compared with its layout and, with autosave on, written once.
- `open` autosaves a change still waiting into the layout being left, applies the new one,
  then records it as active and recent, writing nothing when it already is (as after a page
  load). When that autosave fails, `open` rejects and changes nothing, so the change stays
  on the target; opening again goes ahead without it. When the record is refused the
  previous layout goes back on the target. Change events raised during an apply are not
  edits.
- A write refused because the catalog moved is tried again after a fresh read when what it
  acts on is unchanged there: the held layout's charts for a save or autosave, the named
  layout for `open`, `rename`, `duplicate` and `remove`. A change to the held layout
  elsewhere sets `conflict` and `dirty`, and `save()` and autosave stay refused until
  `overwrite()`, `saveAs()` or `open()`; `reload()` keeps it unless the layout is back as this
  controller left it. A failed autosave pauses until a write goes through again or a
  reload, then writes the unsaved change without waiting for another.

## Layouts menu and indicator templates (since 2.5.10)

`createWidget(el, { workspaces })` with a `WorkspaceStore` builds a layouts controller over
the widget (`widget.layouts`) and the Layouts menu. Source of truth:
`src/widget/layouts-menu.ts`, `layouts-widget.ts`, `layouts-target.ts` and
`layouts-templates.ts`.

```ts
const workspaces = new WorkspaceRepository(createIndexedDbWorkspaceStorage(indexedDB), 'account-7');
const widget = createWidget('#chart', { feed, symbol: 'INFY', workspaces });
widget.openLayouts();            // false without a store or after destroy
await widget.layouts?.flush();   // the controller behind the menu; flush before destroy
```

- The top bar's Layouts button names the held layout (its accessible name too, with what
  the mark means when it shows, such as "Layouts: Morning, Unsaved changes") and carries
  `data-attention="true"` with unsaved changes (autosave off), a failed autosave or a
  conflict. The name gives way to the glyph as the bar narrows, before it would wrap. A
  phone layout's More sheet has a Layouts row; the menu opens centred there.
- The menu: Save (names the chart first when nothing is held, prefilled with symbol and
  interval), Save as, Rename, Delete (asks), Recent (up to ten, `recentWorkspaceIds`), the
  other layouts by name, and an Autosave switch (`role="switch"`) with its status: Saving,
  Saved, Could not save, Waiting to save, or waiting for a replay to end. It reads the list
  and flushes the controller as it opens, so Save is enabled exactly when there is
  something to save. Its words are `schema.ui.layouts.*` message keys, the templates
  list's `schema.ui.templates.*`, with English fallbacks.
- Opening a layout flushes first, then asks when the held layout still has changes: Save
  and open, Open without saving, or Cancel.
- A conflict shows as an alert with Reload list, Save as a copy (prefilled "{name} copy")
  and Overwrite; Save stays disabled until one is chosen. The status line says so once.
- On creation the widget reopens `catalog.activeWorkspaceId`, writing nothing to do it; it
  replaces the host's first chart and, with `persist` too, the state `persist` restored. A
  change inside autosave's quiet period is written when the page is hidden, and tried
  again on `pagehide`. Destroying the widget drops it unless the host flushed first.
- Two widgets on one page take repositories of separate namespaces, or both hold the same
  layout as two tabs would.
- `openLayoutsMenu(ctx, controller, anchor?)` opens the same menu for any controller (a
  grid host's own) and resolves with its `PanelHandle`. The menu loads on first use (see
  Packaging facts), so the promise rejects when it could not load or the widget was destroyed by then; its rules join the
  widget's stylesheet then. The top bar's Layouts button, which shows before anyone opens
  the menu, is in `WIDGET_COMPONENT_CSS`. `widgetLayoutTarget` is above.
- Indicator templates: the picker's Templates button (bottom left) appears when the store
  has `planIndicatorTemplateState`. `applyIndicatorTemplate(ctx, store, template, mode,
  label?)` (`IndicatorTemplateApplyMode`: `'replace'` or `'append'`; returns false when an
  append adds nothing) and `saveIndicatorTemplate(ctx, store, name)` (captured with
  `captureIndicatorTemplate` when the store has it, else the plain study list; never a study
  the host keeps, and it rejects when the chart has none of the user's) are the same from
  host code, `ctx` being `widget.context`. An apply keeps drawings, alerts and the price
  source's place over a study it keeps, refuses during a replay, and on a failure part way
  through its restore puts the chart back and rethrows.
- Undo: the apply goes through `restoreState`, so it starts a new timeline (earlier steps
  are dropped, since their studies were rebuilt) and is the one step on it: undo puts the
  studies and panes back, keeping the drawings, alerts and view the chart has then; redo
  applies it again. A template the chart refuses before restoring leaves the timeline alone.
  `ChartHistory.clear()` now empties its stacks in place, so a pushed command whose undo or
  redo restores the chart keeps its step.

## Drawings per instrument (since 2.5.9)

A widget keeps drawings per instrument by default (`drawingScope: 'instrument'`):
a trend line drawn on one symbol stays with that symbol, comes back when it is
loaded again, and a delete on another symbol leaves it alone. The widget builds
the draw tier's `InstrumentDrawings` (see drawing-tools.md, Drawings per
instrument) over `drawingStore`, or over its own storage with `persist`
(`DRAWINGS_KEY_PREFIX`), or in memory. The swap follows the chart's data
context, so `setSymbol`, the symbol box, quick entry, a watchlist row and a
linked symbol in a grid all move the drawings with the instrument; an interval
or a data variant keeps them.

- **The layout.** `getState().chart.drawings` holds the drawings of
  `getState().symbol` and `exchange`, the ones on screen, exactly as before.
  `restoreState` of a layout for the symbol on screen replaces its drawings. A
  layout for another symbol keeps the drawings on screen for the symbol they
  belong to, stores the layout's for its own symbol, and then switches, so the
  alerts the layout restores are judged against their own drawings.
- **Migration.** A persisted layout from before (one drawing set, no per
  instrument entries) holds the drawings of the symbol it was saved on: they
  are attached to that symbol the first time the widget opens, so opening on
  another symbol (`symbol` option) neither shows them there nor loses them.
- **Undo.** A symbol change is not a step. The widget's `history` drops every
  drawing step recorded before it, and the drawings a removed pane took with it,
  so no Ctrl+Z on one symbol restores or removes a drawing of another; steps of
  studies, panes, settings and the chart type stay, since those belong to the chart.
- **Alerts.** An alert anchored to a drawing stays with that drawing's symbol:
  kept and idle on another symbol (availability says the instrument context
  differs), and evaluated again when its symbol is back.
- **Failures.** A refused write shows "The drawings for {instrument} could not
  be saved" on the status line (and the `status` event); the drawings stay for
  the session and the next change tries again.
- **Chart grid.** Each cell keeps its own documents, keyed by its pane id: two
  cells on one symbol never overwrite each other's lines through one shared
  entry. With the grid's `persist` the documents of the instruments a cell is
  not showing are written beside the workspace, under `oac-widget:<namespace>:grid-drawings`;
  the workspace payload itself still carries only what each chart shows. A cell
  a preset drops takes its documents with it, and a workspace the host applies
  starts each cell from its own payload.
- **Keeping the old behaviour.** `drawingScope: 'chart'` keeps one drawing set
  per widget (per cell in a grid), shown whatever symbol is loaded.

## Watchlist and news panels (2.5.5)

Two optional sources for the panel dock, beside Data and Objects. A tab (and the top bar
and mobile More entries) appears only when its source is supplied, and each needs
`panels` on. Sources: `src/widget/watchlist-panel.ts`, `news-panel.ts`, `quote-board.ts`,
`news-reader.ts`.

```ts
import { createWidget } from 'openalgo-charts/widget';
import { WatchlistRepository, createIndexedDbWatchlistStorage } from 'openalgo-charts/workspace';

const widget = createWidget('#chart', {
  feed, symbol: 'INFY', exchange: 'NSE',
  watchlist: { store: new WatchlistRepository(createIndexedDbWatchlistStorage(indexedDB), 'account-7'), quotes },
  news: { feed: newsFeed, pageSize: 20 },
});
widget.openWatchlist(); // false without a watchlist source, with panels off, or after destroy
widget.openNews();
```

- `WidgetOptions.watchlist` (`WidgetWatchlistOptions`): `store` (a `WatchlistStore`,
  usually `WatchlistRepository`), `quotes?` (`QuoteFeed`), `staleAfterMs?` (default
  60000), `pollMs?` (snapshot-only sources, default 15000, 0 off), `formatPrice?(value,
  instrument)`. Choosing a row calls `setSymbol(symbol, exchange)`, and the widget
  supplies the panel's `normalize` as setSymbol's upper-casing, so a lower-case entry is
  the chart's own row and never a second copy of it. `WidgetOptions.news`
  (`WidgetNewsOptions`): `feed`, `pageSize?` (20), `staleAfterMs?` (300000), `maxItems?` (500).
- `PanelDockId` adds `'watchlist'` and `'news'`; `PanelDockOptions` takes optional
  `watchlist(host)` and `news(host)` factories. `sanitizePanelDockState` keeps both ids;
  restoring one on a dock without that source leaves it closed.
- `mountWatchlistPanel(ctx, host, WatchlistPanelOptions)` returns a `WatchlistPanelHandle`
  (`el`, `initialFocus`, `reload()`, `destroy()`), for a custom host's dock as the
  reference host does. A table of the active list: symbol, last, change and percent
  change from the provider's `previousClose`. List select, New, Rename and Delete (inline
  forms, confirm before delete), an Add input (the host's `symbolSearch` when there is
  one; typed text is uppercased and saved on the chart's exchange), and "Add {symbol}"
  for the chart's instrument. `normalize?(instrument)` maps an entry to the instrument
  the host charts for it (default unchanged): adds are saved in that form, an add
  matching a listed entry that way is refused as already listed, and the current-row
  marker and "Add {symbol}" compare through it. Remove per row; Alt+ArrowUp/Down
  reorders in list order with the revision it was computed from, one move at a time so
  a held key lands every step; ArrowUp/Down moves between rows.
- Rows take prices only from `quotes`. Without it every row is `unavailable` and shows
  `n/a`. That word, the `...` of a loading row and the name a row and a
  message give an instrument (`{symbol} on {exchange}`) translate through
  `schema.ui.watchlist.noQuote`, `schema.ui.watchlist.quoteLoading` and
  `schema.ui.watchlist.entry`. Row `data-state` is a `QuoteRowStatus`: `loading`, `live`, `delayed`,
  `snapshot`, `stale`, `unavailable`, `error`; the status line reads the
  `QuoteBoardStatus`, and warns that values are stale only when one is on screen. The
  board holds one timer, for the next visible snapshot to age past `staleAfterMs`; a
  row behind a live stream never ages, so an idle board holds none. Only rows an `IntersectionObserver` reports on screen hold a
  stream; a list switch, a hidden page, closing or switching the panel, and `destroy`
  release them. Sorting by header (`WatchlistSort`, `WatchlistSortKey`: `list`, `symbol`,
  `last`, `change`, `percent`; a third click returns to list order) is stable, sinks
  unknowns in both directions, and holds row order while the pointer or focus is in the
  rows. The sort is read from and written to `ctx.storage` (`watchlist-sort`), and kept
  per store in memory as well, so it outlives a panel switch when that storage keeps
  nothing. Conflicts show "The watchlists changed in another session" and reload the store.
- `mountNewsPanel(ctx, host, NewsPanelOptions)` returns a `NewsPanelHandle` (`el`,
  `initialFocus`, `refresh()`, `destroy()`). It follows the chart's `data:context`
  instrument (an interval change is the same instrument), cancels the previous request
  on a switch, and lists headline, source and time in the chart's timezone. A detail
  view shows the summary and "Open article" only for `safeNewsUrl(url)`: absolute http or
  https without credentials, opened with `rel="noopener noreferrer"` and
  `referrerpolicy="no-referrer"`. All provider text is set as text.
- DOM-free controllers, exported for custom hosts: `QuoteBoard` (`setVisible`, `row`,
  `status`, `error`, `subscribed`, `destroy`; `QuoteBoardOptions`, `QuoteRow`) and
  `NewsReader` (`setInstrument`, `refresh`, `loadMore`, `snapshot`, `destroy`;
  `NewsReaderOptions`, `NewsSnapshot` with `refreshFailed`, `NewsStatus`: `idle`,
  `loading`, `ready`, `empty`, `error`). `quoteChange(quote)` returns
  `{ change, percent }` or null without a positive `previousClose`.
- `WATCHLIST_PANEL_CSS` and `NEWS_PANEL_CSS` are part of `WIDGET_COMPONENT_CSS`.

## Chart-wide undo and redo (2.5.6)

`ChartHistory` (widget tier, DOM-free) is one timeline for a chart: a study added or
removed (with its settings, visibility, pane, stacking row and scale), study settings,
visibility and scale assignment (`setPriceScale`, `setPlotPriceScales`), the chart type and
the primary series' scale, price scale settings (mode, invert, margins, auto-fit, pinned
ratio, axis placement), panes (moved, folded, resized, added or removed, and brought back with
the studies and drawings they held), the chart settings `applyChartSettings` writes, and drawings. The widget
builds one as `widget.history` and hands it to every piece as `ctx.history`; Ctrl+Z, Ctrl+Y
and Ctrl+Shift+Z, the rail's Undo and Redo, and the mobile Drawing and More sheets all walk it.

```ts
import { ChartHistory } from 'openalgo-charts/widget';

const history = new ChartHistory(chart, { draw, onError: e => console.warn(e) });
history.undo(); history.redo();           // false when there is nothing, or the step failed
history.canUndo(); history.canRedo();
history.peekUndo();                       // { label?, changes: ChartHistoryChange[] } | null
history.transact(() => chart.setPriceAxisOptions(0, 'right', { mode: 'logarithmic' }), 'Scale');
const end = history.group('Chart settings');   // one step until end() runs; a no-op group is none
history.ignore(() => hostOwnSetup());     // the host's own change, drawings included, never a step
history.push({ label: 'Chart type', undo: () => rebuild('candlestick'), redo: () => rebuild('line') });  // none inside ignore
history.attach(rebuiltChart, rebuiltDraw);    // a host that rebuilds its chart keeps the timeline
history.subscribe(refreshButtons); history.clear(); history.destroy();
```

- **Recording.** Changes the chart announces (`objects:change`, `indicatorRemoved`,
  `pane*`, `priceAxis*`, and `layout:change`, which follows `setPaneWeight`,
  `setPriceAxisOptions`, `setPriceScaleOptions` and the other setters that had no event)
  are compared before and after the turn they happened in, so one user action is one step
  whatever made it: a legend button, a dialog, a menu, host code. A pane weight or a scale
  option set in code is therefore a step of its own. A chart setting (the grid, the status
  line) and a scale's auto-fit or pinned ratio are read only in a transaction's full
  capture, so they are recorded inside `transact`; auto-fit announced on its own is a view,
  never a step. The widget's context menu runs every row in `transact`, and its chart and
  study settings dialogs are one `group` per session.
- **Applying.** A step makes the chart look the way it did in exactly the fields it
  changed, through the chart's public calls; it never restores a whole state (that would
  rebuild every study, replay managed requests and reset the drawing history). A host's
  change to a neighbouring field since is kept. A step of several stretches (a group or a
  transaction with an `ignore` inside it) reads each stretch against the chart the stretch
  before it in the press leaves, so none loses its part of the stack order.
- **Scale defaults.** The chart-wide defaults a pane added later starts from
  (`chart.priceScaleDefaults()`: mode, invert and both margins) are a field of each step,
  apart from every pane's own axes. A chart-wide change (`setPriceScaleOptions`, the
  settings dialog) is taken back with its defaults, so a pane added after the undo starts
  from the old ones. One axis changed from its own menu leaves the defaults alone, even on
  a chart with one pane, and is replayed on that axis alone: it never writes the defaults
  and never announces a linked appearance change. The chart settings `scales.mode`,
  `scales.inverted` and `scales.autoScale` are never compared: the defaults and the axes
  carry them.
- **Drawings** stay the controller's: each step is held by the number `drawing:change`
  reported (`DrawingChangeEvent.step`, `DrawingController.historySteps()`), and undone by the
  controller. After `attach` to a new controller, an old step is taken back from the drawings
  either side of it, and so is a step the controller holds under one the history does not.
- **The host's own changes** (`ignore`, and whatever a listener does while a press is applied)
  are recorded nowhere, drawings included: they run through `DrawingController.untracked`,
  so no undo or redo reverses them and the redo branch is kept. Inside `transact` or `group`
  the step is recorded on either side of an `ignore`. A group that ends as no step (a
  Cancel) gives the redo branch back.
- **Panes** that come or go with no study bringing or taking them are `pane-add` and
  `pane-remove` steps: one left with only drawings comes back with them, an empty one empty.
  A pane holding a host's own series, and a pane the host made (`addPrimitive` at a new
  index for a primitive of its own, or a drawing placed there), is the host's: never a
  `pane-add` step, and never made or removed by an undo or redo.
- **Linked charts**: a linked appearance change is the step of the chart that made it.
  Followers apply it through their `ignore` (the grid and the yfinance split view do), and
  walking the step re-announces the result on `style:change` so the followers follow.
- **Never**: no bars are written, no alert fires (a study brought back reseeds silently), no
  order is placed.
- **Failure**: a step that cannot be applied is rolled back, dropped with every step behind
  it, and reported to `onError`; the redo branch is kept. A new action clears redo.
- **Layouts**: `chart.restoreState` and `widget.restoreState` start a new timeline.
- **Study ids**: a study brought back is re-created under the instance id it had
  (`addIndicator(id, settings, { instanceId })`), so its readers and the alerts naming it find
  it again. Studies are told apart by the chart's own object for each, not by id or kind: when
  a study the host placed under that id since holds it (`addIndicator` throws on an id in use),
  of the same kind or another, the one brought back takes a fresh id with the settings the step
  gives it, later steps and the studies reading it follow it, and the host's study keeps the
  id, its pane and its settings and is never taken for the one a step means.
- **Study policies**: no press overrides one. A study stays on the chart while `removable:
  false`, keeps its settings and scales while `configurable: false` and its pane while
  `movable: false`; the rest of the step applies, and a step left with nothing to do is dropped
  and the press goes on, so `canUndo`, `canRedo` and the peeks stay true (`subscribe` hears a
  policy change that moves them). A study that may not move is never moved by a call of its
  own, but other studies pass it, as the chart lets them: a reorder that moves a free study
  past a pinned one is a step and is taken back, and a study removed from above a pinned one
  comes back above it. Two pinned studies never trade places. Adding a protected study and a
  forced write or remove on one are the host's and never steps.
- **Policies the host changes later**: a study an undo or redo brings back takes the policy
  its host holds now, the one it last had on the chart, never an older one the step captured,
  so a press never removes or weakens a restriction set after the step was made. A study that
  left the chart by the host's hand (inside `ignore`, a forced remove, or left out of a chart
  the host rebuilt and passed to `attach`) is the host's to bring back: the part of any step
  that would re-add it is dropped, and a step left with nothing else to do is dropped with it.
- **Study input anchors**: `ChartHistory` takes the anchor steps of its drawing controller
  (`DrawingController.delegateInputAnchorSteps`) and records the settings patch a drag or a
  `moveInputAnchor` wrote as the move ends, so each is one step, undone once and in order with
  the drawings, and a settings dialog's Pick point on chart is part of that dialog's step. The
  drawing controller holds none of them while the history is attached. Without a history the
  drawing controller keeps them itself, and a point written through the settings (the Pick
  point) is one of its steps too, so its undo takes a pick back first and never a drawing made
  before it.
- Types: `ChartHistoryOptions` (`draw`, `limit` default 100, `series`, `setChartType`,
  `onError`), `ChartHistoryCommand`, `ChartHistoryStep`, `ChartHistoryChange` (`study-add`,
  `study-remove`, `study-settings`, `study-visibility`, `study-scale`, `study-pane`,
  `study-order`, `chart-type`, `series-scale`, `pane-add`, `pane-remove`, `pane-order`,
  `pane-weight`, `pane-collapse`, `axis`, `settings`, `drawing`, `command`), `ChartHistoryError`
  (`direction`, `step`, `error`).

## Drawing toolbar, style templates and coordinates (since 2.5.9)

**Floating toolbar.** With the rail on (or `drawingToolbar: true`), selecting drawings on a
desktop layout shows `.oac-drawbar` (`role="toolbar"`) over the chart: a colour swatch,
the line width, the line style, lock, delete and a more menu (Properties..., Duplicate,
Hide or Show, the four order rows, and the template rows). It sits above the selection's
highest visible anchor, centred on the part of it in view, below the selection when the
top has no room, and always inside the chart. It follows a pan, a zoom, a resize, an
edit, a price axis dragged or wheeled, and a tick that moves the autoscale. It steps aside
while a tool is placing, while a drawing is dragged (`draw:preview`), in the narrow layout
(which has its own bar) and while the properties dialog is open.

- A control shows only when every selected drawing's settings schema declares its field
  (`style.color`, `style.lineWidth`, `style.lineStyle`), as the properties dialog does.
- When the selection disagrees, the control says so: the swatch splits corner to corner
  into two of the colours in use and is labelled "Color: mixed", the width reads "Mixed",
  the style shows a solid line over a dashed one, and lock is `aria-pressed="mixed"`.
- Each click is one step of `widget.history` (`transact`), however many drawings it
  changes: one `updateMany`, one `removeMany`, or a front or back move of several.
- A selection with nothing the user may edit (`policy.editable: false`) shows its edit
  controls disabled with "(read-only)" in the title. Delete is also disabled when every
  selected drawing is locked, as in the context menu.
- The toolbar, the context menu, the properties dialog, the rail, the phone bar
  and the Delete, Backspace and cut keys share these rules (`drawing-actions.ts`): each
  press is one history step; lock and hide read every drawing the user may edit, on when
  every one is, so a partly locked selection locks; a selection whose every drawing is
  locked is neither deleted nor cut; the order moves and duplicate reach every drawing.
- Keyboard: it follows the chart in the tab order, so Tab from the focused chart reaches it,
  with one tab stop. Inside it, the arrow keys (with or without Shift), Home and End move
  between controls, and Escape goes back to the chart with the selection kept. Its key scope,
  `drawing-toolbar`, claims every arrow the widget reads as a nudge, so none of them moves
  the drawing while the focus is in the bar. Every label is a message key: `Drawing toolbar`,
  `More drawing actions`, `Color: {value}`, `Line width`, `Line width: {value}`,
  `Line style`, `Line style: {style}`, `{value} px`, `Solid`, `Dashed`, `Dotted`, `mixed`,
  `Mixed`.
- `mountDrawingToolbar(ctx, host, { chart?, templates? })` mounts one in a custom host,
  after the chart element in `host`, and returns a `DrawingToolbarHandle` (`el`, `refresh()`,
  `destroy()`). `TOOLBAR_LINE_WIDTHS` is `[1, 1.5, 2, 3, 4]`, and `DRAWING_TOOLBAR_CSS` holds
  its rules (part of `WIDGET_COMPONENT_CSS`). Types `DrawingToolbarOptions`,
  `DrawingToolbarHandle`.

**Style templates.** Pass a store and the widget holds its catalog:

```ts
import { DrawingTemplateRepository, createIndexedDbDrawingTemplateStorage } from 'openalgo-charts/workspace';

const templates = new DrawingTemplateRepository(createIndexedDbDrawingTemplateStorage(indexedDB), 'account-1');
const widget = createWidget('#chart', { feed, symbol: 'INFY', drawingTemplates: templates });
widget.drawingTemplates?.templatesFor('trend-line');   // saved looks for one tool
```

- The more menu and the properties dialog's Templates button (bottom left) offer "Save as
  default for this tool", "Forget the default for this tool", "Save as template..." (a name
  prompt; the same name on the same tool replaces that template) and "Apply {name}" for each
  template of the selection's tool. A selection of several tools gets the save rows greyed
  ("one tool at a time") and no apply rows; a read-only one gets apply greyed.
- A template holds settings by schema path (`style.*`, `text.*`, `props.*`), never
  `text.value`, anchors, a lock or a pane, and is applied through each drawing's own schema
  (`applyDrawingSettings`), as one `updateMany`.
- A tool's default reaches only drawings the user places with that tool after it was saved:
  not the drawings already on the chart, not another tool, and not a host's `draw.add`, a
  paste or a duplicate, even one made while that tool is in use. A placement is an `add`
  step of one drawing of the tool in use that the controller closes, in the same turn, with
  `draw:tool`. The default is written with `DrawingController.untracked` (through
  `history.ignore`), which every recorded step takes in, so placing the drawing is still
  one undo step and its redo brings the default back.
- `createDrawingTemplates(ctx, store)` builds the holder for a custom host; the widget's is
  `widget.drawingTemplates` and `ctx.drawingTemplates` (null and undefined without a store).
  `DrawingTemplates`: `store`, `catalog()`, `templatesFor(tool)`, `defaultFor(tool)`,
  `capture(drawing)`, `apply(ids, values)`, `saveDefault(id)`, `clearDefault(tool)`,
  `saveTemplate(id, name)`, `removeTemplate(templateId)`, `subscribe(listener)`, `destroy()`.
  A load that lands after a newer commit is ignored; a failed load puts "Drawing templates
  could not be loaded" on the status line, and a failed save a toast. `DRAWING_TEMPLATES_CSS`
  holds the name prompt's rules.

**Coordinates.** The properties dialog's Coordinates tab lists each anchor as a date, a
time and a price. Times are on the chart's clock (`chart.timezone()`, IST unless the chart
says otherwise), with seconds only when the anchor has them. Prices show at the pane's
precision (two decimals at least) when that is exact, and in full when it is not. A row is
written on Enter or when the focus leaves the row, after it validates, as one `draw.update`
and so one undo step; a field left as shown keeps its exact value. Not on `change`: a date
or time field reports one for each segment typed, and each would be a step of its own. A
date that names no day, a time that does not read, a price that is not a number, and a
price at or below zero on a logarithmic scale are refused with the reason (`aria-invalid`),
writing nothing. A drawing pinned to the screen and a freehand stroke list no anchors, with
a note.

**Objects panel.** Each pane lists back to front (a hint line says so), a draggable row
carries a grip, and Alt with ArrowUp or ArrowDown on a row moves it one step the way
Earlier and Later do.

**Contrast.** `--oac-faint` is now the dimmest colour that reads at 4.5 to 1 on `bg`,
`panel`, `panel-2` and `elev`; hints on a hovered row and the tooltip's second line use
`--oac-mut`. New `--oac-up` and `--oac-down` are the candle pair lifted to read as text
(the watchlist's moves and the status line's change use them); `--oac-buy` and
`--oac-sell` stay the raw colours for fills and borders.
