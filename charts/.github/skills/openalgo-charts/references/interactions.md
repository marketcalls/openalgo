# Interactions

*When to read this: wiring or rebinding keyboard shortcuts, changing crosshair behaviour, supporting touch, arming a placement gesture, or making the chart keyboard-accessible.*

Source of truth: `src/core/chart-input.ts` (`_attachInput` and the pointer/wheel/key handlers; `src/core/chart.ts` keeps the listener fields that delegate to it), `src/core/chart-motion.ts` (the eased wheel zoom, the kinetic glide and the autoscale easing), `src/input/wheel.ts`, `src/input/shortcuts.ts`, `src/input/kinetic.ts`, `src/input/touch.ts`, `src/input/crosshair.ts`, `src/primitives/time-navigator.ts`. Tests: `tests/wheel-navigation.test.ts`, `tests/price-scale-transitions.test.ts`, `tests/shortcuts.test.ts`, `tests/interaction.test.ts`, `tests/pointer-button-guard.test.ts`, `tests/placement-mode.test.ts`, `tests/time-navigator.test.ts`.

Everything is built on Pointer Events, so mouse, touch and pen share one code path. Listeners are attached to the container in the constructor and removed in `destroy()`; `keydown` goes on `document` when available, else on the container.

## Pointer gestures

| Gesture | Effect | Detail |
|---|---|---|
| Drag the plot | mouse, pen and touch pan time and price by default | `navigation.mousePan: 'horizontal'` limits mouse and pen to time; panning price switches the pressed pane to manual scaling, while horizontal-only panning preserves autoscale |
| Vertical wheel over the plot | zoom the time axis | proportional to normalized CSS-pixel distance, eased by default (each event moves one target, the frames chase it by real frame time, so a fast wheel or a trackpad zooms in one smooth motion); `animZoom: false` applies instantly. `zoomAnchor` selects cursor x or right edge |
| Horizontal wheel, dominant x delta or Shift-wheel | pan time | Shift maps a vertical-only delta onto x; Ctrl-wheel and Meta-wheel remain pinch-style zoom input |
| Wheel over a price axis | scale that left or right price range | pointer price stays anchored and that one scale becomes manual |
| Drag either price axis | rescale price | `exp(dy * 0.005)` about the range centre, then `setAutoScale(false)` |
| Drag the time axis (bottom strip of the last pane) | left expands bar spacing; right compresses it | `barSpacing * exp(-dx * 0.005)`, preserving the logical right edge |
| Drag a pane divider | redistribute height between the nearest open panes either side of it: the two adjacent panes, or past a collapsed strip, which keeps its height | grab tolerance 4 px, cursor `row-resize`, summed weight preserved, neither side below `min(24, total/4)` px; emits `paneResized` on release. No divider while a pane is maximized, or beside a strip with no open pane on one side |
| Double-click | `doubleClick` option: `'reset'` (default) is `resetScale()`, the configured default view plus autoscale on every pane; `'maximize'` toggles `maximizePane` for the pane under the pointer; `'none'` only emits | suppressed while placement mode is on, or when a `dblclick` listener set `handled` on the event; the event carries `paneIndex`, `x`, `y` |
| Press on a draggable primitive | drags the line instead of panning | arms when `hit.draggable` is true, or `hit.cursor === 'ns-resize'` and `subscribeDrag` is registered |
| Flick and release | kinetic scroll | see below |
| Two pointers | pinch | see below |
| Right-click | composites the pane into the overlay so the browser's "Save image as…" is not blank, and freezes overlay repaints until the next input | skipped when the host called `preventDefault()` |

A press-and-release with under 3 px of movement is a click: `subscribeClick` fires for a hit, and the `click` event fires either way carrying `id`, `price`, `time`, `paneIndex` and `point`.

**Only the primary mouse button starts a gesture.** Both `pointerdown` and the native `pointerup` filter `e.pointerType === 'mouse' && e.button !== 0`. Without the pointerup half, a right-click replays the previous left-click against stale coordinates and fires a phantom order (`tests/pointer-button-guard.test.ts`). Touch and pen contact with button 0 and are unaffected.

`wheelPixels` converts DOM_DELTA_LINE to 16 CSS px and DOM_DELTA_PAGE to the chart
width or height. `wheelLogFactor` preserves a 1.1 zoom for a 100 px notch and scales
smaller input proportionally, clamped per event. A browser pinch reported as Ctrl-wheel
or Meta-wheel zooms at the pointer even when `zoomAnchor: 'right'` is configured.

**The wheel handler prevents default for non-zero normalized input.** A chart placed
inline in a scrolling page traps wheel movement while the pointer is over it; give it its
own scroll region when the page must retain wheel scrolling.

Kinetic scrolling: a release faster than `triggerSpeed` decelerates as `velocity(t) = v0 · e^(−k·t)`. `DEFAULT_KINETIC_OPTIONS` is `friction: 0.0055` (1/ms, larger stops sooner), `minSpeed: 0.02` px/ms (animation ends), `triggerSpeed: 0.08` px/ms (slower flicks ignored). `KineticAnimation` uses no `Date` or `rAF` internally, so it is deterministic; the next `pointerdown` cancels it. Since 2.5.8 the chart steps the kinetic glide and the eased wheel zoom at the top of its own render frame, before the study flush, and schedules no frames for them: each frame paints the step it made, a glide asks for one animation frame per frame, and its `pan` or `zoom` event fires in the frame that paints it.

Pinch: a second pointer aborts any single-pointer drag. Each frame compares two `pinchState` snapshots (`factor` (distance ratio) zooms time at the midpoint, `dx` pans time, `dy` pans the pinched pane's price scale) all in the same frame, so spreading while sliding zooms and pans at once.

## Autoscale motion and cancellation

`ChartOptions.animAutoscale` defaults to `animZoom` and eases an automatic price range
while time navigation reveals new extrema. The range interpolation works in linear,
logarithmic, percentage and indexed-to-100 modes. It does not override a manually panned
or scaled axis, or a fixed range.

Programmatic `setVisibleLogicalRange`, `fitContent`, `resetScale`, primary-series
`setData` and `destroy` stop pending navigation motion before applying their own state.
A new wheel tick folds its remaining zoom distance into the new target; a pointer press
cancels the zoom glide so the direct gesture owns the viewport. There is no promised
delay tied to realtime data, and browser or device event delivery may differ.

## Navigation options

```ts
createChart(el, { navigation: { mousePan: 'both', defaultVisibleBars: 120 } });
chart.setNavigationOptions({ mousePan: 'horizontal' }); // optional time-only panning
chart.navigationOptions();  // Readonly<ChartNavigationOptions>
```

`ChartNavigationOptions` is exported from the base entry. `mousePan` defaults to
`'both'` and applies to mouse and pen plot drags; touch retains two-axis panning.
Horizontal panning leaves autoscale enabled when it was enabled, so price can still
follow the newly visible bars.

`defaultVisibleBars` defaults to `0`, fitting all loaded bars. A positive count targets
the newest N loaded bars plus four empty bar slots on the right, within available-data
and bar-spacing limits. Initial data and `resetScale()` use this default, and changing
the count applies the default view immediately. `fitContent()` continues to fit all
loaded bars. The count changes no feed request and discards no history; an explicit host
viewport applied after loading data wins. The widget's ordinary load views honour the
configured count when no spacing preference is selected.

`navigation.defaultBarSpacing` selects an initial/reset density in CSS pixels per bar.
Positive values override the count, and `0` disables spacing mode. A count-only edit
also disables spacing mode. The widget defaults to 8 pixels; saved and explicit count
preferences remain supported. Resize preserves the current zoom. The spacing preference
round-trips through chart state and the Axes settings schema.

Both fields appear in the settings schema's Axes / Navigation group as
`navigation.mousePan` and `navigation.defaultVisibleBars`. `readChartSettings` /
`applyChartSettings` and `getState` / `restoreState` persist them. Upgrading preserves
explicit saved horizontal preferences. Select **Axes > Mouse drag > Time and price**
or set `mousePan: 'both'` to change that preference; do not reset unrelated user settings.

## Crosshair

```ts
createChart(el, { crosshairMode: 'magnet' });   // 'normal' is the default
chart.applyOptions({ crosshairMode: 'normal' }); // takes effect on the next pointer move
```

`magnetSnapPrice(price, bar)` returns whichever of `bar.open/high/low/close` is nearest.

**Magnet only snaps in the pane holding the first price series.** Volume and indicator panes are not price scales, so the snap is skipped there. `DrawingController`'s own `magnet` option is separate and snaps on the price pane only, wherever it sits.

**`CrosshairMode` is not exported by name.** Pass the string literals `'normal'` / `'magnet'`; the type is inlined into `dist/index.d.ts` but absent from the export list.

## Keyboard

On by default. `chart.shortcuts` is the `ShortcutManager`, or `null` when disabled with `shortcuts: false`.

### Default keymap

`DEFAULT_KEYMAP` in `src/input/shortcuts.ts`. `Mod` is Ctrl on Windows/Linux and Cmd on macOS.

| Command | Label | Default combos | What it does |
|---|---|---|---|
| `panLeft` | Pan left | `ArrowLeft` | `rightOffset -= 2` |
| `panRight` | Pan right | `ArrowRight` | `rightOffset += 2` |
| `panLeftFast` | Pan left (fast) | `Mod+ArrowLeft` | `rightOffset -= 10` |
| `panRightFast` | Pan right (fast) | `Mod+ArrowRight` | `rightOffset += 10` |
| `panUp` | Pan up | `ArrowUp` | `panes[0].priceScale.panByPixels(20)` |
| `panDown` | Pan down | `ArrowDown` | `panes[0].priceScale.panByPixels(-20)` |
| `zoomIn` | Zoom in | `Equal`, `Shift+Equal`, `NumpadAdd` | `zoomAtX(width/2, 1.1)` |
| `zoomOut` | Zoom out | `Minus`, `NumpadSubtract` | `zoomAtX(width/2, 1/1.1)` |
| `resetScale` | Reset view | `Home`, `Digit0` | `resetScale()` |
| `fitContent` | Fit all bars | `Alt+KeyF` | `timeScale.fitContent(length)` |
| `screenshot` | Screenshot (PNG) | `Alt+Shift+KeyS` | `downloadScreenshot()` |
| `toggleGridVert` | Toggle vertical grid | `Alt+KeyV` | flips `grid.vertLines` |
| `toggleGridHorz` | Toggle horizontal grid | `Alt+KeyH` | flips `grid.horzLines` |
| `toggleCrosshairMagnet` | Toggle crosshair magnet | `Alt+KeyM` | swaps `normal` / `magnet` |

`panLeftBar` and `panRightBar` (`rightOffset ∓ 1`) are executable commands with **no default binding**: they exist for the TimeNavigator buttons and for hosts that want a one-bar step. `BUILTIN_COMMANDS` is the set built from `DEFAULT_KEYMAP`, so it does not contain them.

`ALT_PRESET` overlays three: `panLeftFast: Alt+ArrowLeft`, `panRightFast: Alt+ArrowRight`, `screenshot: Mod+Shift+KeyS`. Select it with `preset: 'alt'` or `setPreset('alt')`; user rebinds still win.

**`panUp` and `panDown` always act on the price pane**, in whatever slot it sits, whatever pane the pointer is over.

### Combos

Physical key codes, so bindings survive keyboard layouts. Modifiers in canonical order `Mod`, `Ctrl`, `Meta`, `Alt`, `Shift`, joined with `+`, one non-modifier key last matching `[A-Za-z0-9]+` (`KeyR`, `Digit0`, `ArrowLeft`, `Home`, `Equal`, `Minus`, `NumpadAdd`, `Escape`, `Space`).

```ts
parseCombo('Shift+Mod+KeyA');   // { mods: ['Mod','Shift'], key: 'KeyA' }
normalizeCombo('Shift+Mod+KeyA'); // 'Mod+Shift+KeyA'  ('' when invalid)
isValidCombo('Alt+KeyR');       // true
isReservedCombo('Mod+KeyW');    // true
formatCombo('Alt+KeyR');        // 'Alt + R'; on macOS, the Option glyph U+2325 then 'R'
eventToCombo(keyboardEvent);    // 'Mod+ArrowLeft'
```

Reserved (never bindable): `Mod+KeyW/T/N/Q/R/L`, `Mod+Shift+KeyT/N/W`.

Scope: `hover` (default) fires only while the pointer is inside the chart or focus is on the container or a descendant, the right choice for a multi-chart page. `global` always fires. Keys are ignored whenever the event target is an `input`, `textarea`, `select`, or a `contenteditable` element (`ShortcutManager.shouldIgnore`).

### Configuring and rebinding

```ts
const chart = createChart(el, {
  shortcuts: {
    preset: 'alt',
    scope: 'global',
    overrides: { panLeftFast: 'Alt+ArrowLeft', screenshot: null }, // null unbinds, still listed
    disabledCommands: ['toggleCrosshairMagnet'],
    customShortcuts: [
      { command: 'openOrders', label: 'Open orders', combos: 'Alt+KeyO', onTrigger: () => openOrders() },
    ],
    persist: true,          // localStorage, key 'openalgo-charts:shortcuts'
  },
});

chart.shortcuts?.setBinding('zoomIn', 'Shift+Equal'); // false if reserved or all combos invalid
chart.shortcuts?.disable('panUp');
chart.shortcuts?.resetBinding('panUp');
chart.shortcuts?.resetAll();
chart.shortcuts?.list();   // [{ command, label, combos, isCustom, isDisabled }]
chart.shortcuts?.state();  // { preset, overrides, disabled }, serializable
chart.shortcuts?.on((e) => track(e.command)); // { command, combo, isCustom }; returns an unsubscribe
chart.shortcuts?.onChange(() => redrawHints()); // (since 2.5.10) after every keymap change; returns an unsubscribe
```

`shortcuts` also accepts a pre-built `ShortcutManager`, which is how two charts share one keymap.

**Persisted state overrides constructor options.** With `persist: true` the manager loads saved preset/overrides/disabled in the constructor and applies them on top of what you passed, so a stale localStorage entry silently wins. Bump `storageKey` when you change defaults.

**Reserved combos passed through `overrides` are dropped silently.** Only `setBinding` reports failure, by returning `false`.

**Disabling shortcuts does not disable the TimeNavigator buttons.** They call `_runShortcut` directly; with `shortcuts: false` they still zoom, reset and step, they just lose their keyboard-hint tooltips. Since 2.5.10
the hints follow a rebind (`onChange`) unless the host passed `timeNavigator.hints`.

## Touch and mobile

The constructor sets `touch-action: none` on the container, so the browser does not steal pan or pinch. One finger pans both axes; two fingers pinch-zoom and pan; a double-tap raises the synthetic `dblclick` and resets the scale; a tap under 3 px of travel is a click and hit-tests primitives.

**A scrollable ancestor can still swallow touch before the chart sees it.** Put `touch-action: none` on the scroll container too, or move the chart out of the native-scroll region.

`window.devicePixelRatio` is read at startup, on every resize and whenever the ratio changes (the chart watches a `(resolution: Xdppx)` query and the window's `resize`), and every canvas is re-sized and repainted at once; override with `pixelRatio: () => 2` for fixed-density screenshots or headless environments.

The packaged widget adds responsive mobile chrome; the engine itself remains DOM-free.
See [widget](widget.md#mobile-controls) for the `'auto'`, `'always'` and `'never'` modes,
shared drawing state and reduced-motion defaults.

## Accessibility

The constructor makes the container a focusable, labelled region: `role="application"` (only when no `role` is set), `aria-label` from `ChartOptions.ariaLabel` (default `'Interactive financial chart'`, always set), `tabindex="0"` (only when no `tabindex` is set), plus a visually hidden `aria-live="polite"` div refreshed with the bar count and latest formatted close on data changes and on every handled shortcut.

```ts
createChart(el, { ariaLabel: 'NIFTY 5-minute candlestick chart' });
```

Keyboard-only navigation is complete: focus the container, then arrows pan, `=`/`-` zoom, `Home` or `0` resets, `Alt+F` fits. `destroy()` removes the live region and clears the cursor hint but leaves `role`, `aria-label` and `tabindex` on the element.

**`ariaLabel` is constructor-only.** There is no setter; call `container.setAttribute('aria-label', …)` when the symbol changes.

## Placement mode

```ts
chart.setPlacementMode(true);
```

While active: a press no longer pans, `dblclick` no longer resets the scale (so a variable-anchor tool can be finished with a double-click), and a press-drag-release is reported as **two** `click` events (the press point, then the release point tagged `viaDrag: true`) so a two-point shape is drawn in one gesture. A press-release that never moves more than 3 px stays a single click. Verified in `tests/placement-mode.test.ts`.

`DrawingController` drives this for you: `setTool(id)` turns it on, and clearing the tool, finishing a shape or destroying the controller turns it off. Call it directly only when building a placement UI that is not a drawing tool (an alert level, a custom annotation).

**Leaving placement mode on makes the chart un-pannable.** Always pair the `true` with a `false`.

## Time navigator

A hover-revealed control strip above the time axis, on by default. It is an ordinary primitive living on the bottom pane, re-parented when panes are added or removed.

```ts
createChart(el, { timeNavigator: false });
createChart(el, { timeNavigator: { size: 30, revealHeight: 90, fadeSeconds: 0.2, showTooltip: false } });
```

| Option | Default |
|---|---|
| `buttons` | `['zoomOut', 'zoomIn', null, 'resetScale', null, 'panLeftBar', 'panRightBar']` (`null` inserts a group gap) |
| `size` / `gap` / `groupGap` | `26` / `4` / `16` |
| `bottomMargin` / `revealHeight` | `10` / `64` |
| `fadeSeconds` | `0.12` (`0` disables the fade) |
| `showTooltip` / `id` | `true` / `'timenav'` |

Buttons run the same command ids the keyboard does, through `_runShortcut`, so the two paths cannot drift. Tooltip hints are read from the live keymap at construction, so a rebind of `zoomIn` shows in the tooltip; the one-bar step buttons have no default binding and therefore no hint.

`TimeNavigatorAction` includes `'resetScale'`. The centre button's default tooltip is
**Reset view**, with the `Home` keyboard hint. It restores `navigation.defaultVisibleBars`
and autoscale, through the same `resetScale()` action as the keyboard.

Reveal is driven by an explicit `setPointer(plotLocalPoint | null)` from the chart, not by hover ids, a drawing or order line near the bottom edge would otherwise win the hit test and hide the strip. While hidden the buttons hit-test to nothing, so they never steal a click.

## Related

[core-api](core-api.md) · [scales-and-panes](scales-and-panes.md) · [events-and-state](events-and-state.md) · [drawing-tools](drawing-tools.md) · [primitives-and-plugins](primitives-and-plugins.md) · [react-integration](react-integration.md) · [pitfalls](pitfalls.md)
# Candle-center crosshair

`createChart(element, { crosshairSnapToBar: true })` aligns the vertical line
with the nearest bar center. `chart.applyOptions({ crosshairSnapToBar: false })`
restores pointer-following immediately; `chart.crosshairSnapToBar()` reads it.
The option defaults to false, survives `getState` / `restoreState`, and is exposed
as `canvas.crosshairSnapToBar` in the chart settings schema. It is independent of
`crosshairMode: 'magnet'`, which controls horizontal OHLC snapping. Event points
and drawing hit tests retain the raw pointer. Empty and future space do not snap.

## Plot grab and release (2.4.8)

A primary-button press on the plot shows the `grabbing` cursor. Mouse and pen pan
time and price by default and stop immediately on release. Lost pointer capture
and cancellation abandon the pan; drawing placement and primitive drags keep their
own gestures. Touch flicks retain momentum. `navigation.mousePan: 'horizontal'`
continues to restrict mouse and pen movement to time. No host cursor handler is needed.
