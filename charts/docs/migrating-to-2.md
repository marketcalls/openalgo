# Migrating from 1.9.x to 2.0

2.0.0 rebuilds the drawing model, adds a render backend option and eases the
wheel zoom by default. Everything else a 1.9.x host calls (`createChart`,
`addSeries`, `addIndicator`, the trading overlay, feeds, state, linking,
replay) is unchanged. This guide is
written for a host like the OpenAlgo React terminal: it constructs a
`DrawingController` with `magnet`, calls `select`, `selected`, `toJSON` and
`fromJSON`, and keeps the drawings JSON in `localStorage` between sessions.

The short version:

- Stored 1.9.x drawings survive. `fromJSON` runs `migrateDrawings` on whatever
  it is handed, so a bare array saved by 1.9.x loads unchanged. Nothing has to
  be rewritten in storage.
- `toJSON()` now returns `{ version: 2, drawings }`, not an array. Code that
  reads the array out of the saved payload (a length, a map, a filter) has to
  read `.drawings` or normalise with `migrateDrawings` first.
- Text moved off `DrawingStyle` on to `drawing.text`; fib levels are objects;
  `zIndex` is on every drawing; `select` takes a list.
- `chart.renderer` is `chart.rendererKind`. Four `ChartOptions` keys are new:
  `renderer`, `renderBackend`, `zoomAnchor` and `animZoom`. The first three
  change nothing unless set. `animZoom` defaults to `true`, so a wheel zoom now
  eases over a few frames on a host that changed nothing; `animZoom: false`
  restores the 1.9.2 single-frame step.

Every change below has the 1.9.x code, the 2.0 code, and the reason.

## 1. Persistence: `toJSON` returns a document

**1.9.x**

```ts
// save
localStorage.setItem(`drawings:${symbol}`, JSON.stringify(draw.toJSON()));   // Drawing[]

// restore
const saved = JSON.parse(localStorage.getItem(`drawings:${symbol}`) ?? '[]');
draw.fromJSON(saved);
```

**2.0**

```ts
import { migrateDrawings } from 'openalgo-charts/draw';

// save: the same line. What it stores is now { version: 2, drawings: [...] }.
localStorage.setItem(`drawings:${symbol}`, JSON.stringify(draw.toJSON()));

// restore: the same line. fromJSON accepts a 1.9.x array and a 2.0 document.
const saved = JSON.parse(localStorage.getItem(`drawings:${symbol}`) ?? 'null');
draw.fromJSON(saved ?? []);
```

Both lines are unchanged, so a chart a user drew in 1.9.x opens in 2.0 with
its drawings, text and fib levels in place. The migration is the one place the
old shape is understood: it moves the seven text keys into `drawing.text`,
turns each bare ratio into a `FibLevel` carrying the conventional colour for
that ratio, fills in `zIndex: 0` (which paints exactly where 1.9.2 painted)
and keeps ids and order. It never throws: garbage yields an empty document,
because it runs on the load path where an exception takes the chart down.

What does change is any code that treated the saved value as an array:

```ts
// 1.9.x
const count = saved.length;
const onPane0 = saved.filter((d) => d.paneIndex === 0);

// 2.0: normalise first, then read .drawings. Idempotent on a 2.0 document,
// so it is safe to call on every load.
const doc = migrateDrawings(saved);
const count = doc.drawings.length;
const onPane0 = doc.drawings.filter((d) => d.paneIndex === 0);
```

The document is versioned so that the next shape change is recognisable too;
`DRAWING_STATE_VERSION` is `2`.

### `chart.getState().drawings` is the same document

A host that persists `chart.getState()` rather than `draw.toJSON()` needs no
change either: the `drawings` slot carries the document, the controller
restores through the same `fromJSON`, and a 1.9.x state with a bare array in
the slot loads. The ordering rule from 1.9.x still holds: construct the
controller after `restoreState`, or call
`draw.fromJSON(chart.drawingState())` yourself.

### The clipboard

`DRAWING_CLIPBOARD_VERSION` is `2`. A version 1 body (one written by a 1.9.x
tab, or one still sitting in the OS clipboard) pastes in 2.0; it is upgraded
through the same migration after the clipboard's own validation. Paste stays
strict where load is lenient: a saved layout is the user's own work, a paste
is foreign input.

## 2. Selection: `select` takes a list

**1.9.x**

```ts
draw.select(id);          // one id or null
const current = draw.selected();   // string | null
```

**2.0**

```ts
draw.select(id);                       // still valid: replaces the selection with one id
draw.select([a, b, c]);                // replace with several
draw.select(id, true);                 // additive: toggle id in or out (the shift-click gesture)
draw.select(null);                     // clear

const primary = draw.selected();       // the first id picked, or null (unchanged type)
const all = draw.selection();          // readonly string[], in the order picked
```

A host that only ever called `select(id)` and read `selected()` compiles and
behaves as before. A host that assumed the selection had at most one member
(a properties bar keyed on `selected()`, a Delete handler that removes
`selected()`) should read `selection()`, because a shift-click, a marquee of
your own or a body drag over an unselected drawing can now put more than one
id there, and the engine's own bulk operations expect the list:

```ts
draw.removeMany(draw.selection());
draw.duplicate(draw.selection());              // returns the copies
draw.nudge(draw.selection(), 0, -1);           // px, one undo entry
draw.updateMany(draw.selection().map((id) => ({ id, patch: { locked: true } })));
```

The `draw:select` event is unchanged. `drawing:select { ids }` and
`drawing:change { ids, kind }` are new and carry the whole list.

## 3. Text is `drawing.text`, not `style.text`

**1.9.x**

```ts
draw.add({
  tool: 'text',
  points: [anchor],
  paneIndex: 0,
  style: { text: 'Breakout', fontColor: '#fff', fontWeight: 'bold', textAlign: 'center' },
});
draw.update(id, { style: { ...d.style, text: 'Retest' } });
```

**2.0**

```ts
draw.add({
  tool: 'text',
  points: [anchor],
  paneIndex: 0,
  text: { value: 'Breakout', color: '#fff', bold: true, align: 'center' },
});
draw.update(id, { text: { ...d.text, value: 'Retest' } });
```

Key by key:

| 1.9.x `style.*` | 2.0 `text.*` |
|---|---|
| `text` | `value` |
| `fontColor` | `color` (falls back to `style.color`) |
| `fontWeight: 'bold'` | `bold: true` |
| `fontStyle: 'italic'` | `italic: true` |
| `textAlign` | `align` |
| `textVAlign` | `valign` |
| `textPosition` | `position` (`'inside'` or `'outside'`, shapes only) |
| `fontSize`, `fontFamily`, `wrap`, `wrapWidth`, `background`, `backgroundColor`, `backgroundOpacity`, `border`, `borderColor` | the same names, on `text` |

Seven keys that only meant something to the eight tools that draw words were
sitting on every trend line's style bag, and a host could not tell a label
colour from a stroke colour without knowing the tool. `DrawingStyle` is now
what a stroke needs; `DrawingText` is a closed block. TypeScript reports every
site that still writes `style.text`, which is the fastest way to find them. A
custom tool that read `c.drawing.style.text` reads `c.drawing.text?.value`.

`drawingSettingsSchema(toolId).textIsContent` is true for the tools that *are*
their text (`text`, `callout`, `note`, `balloon`, `comment`, `signpost`,
`price-note` and `table`), so a host can ask for the content on placement; for
a shape, `text` is an optional label.

## 4. Fib levels are objects

**1.9.x**

```ts
style: { levels: [0, 0.382, 0.5, 0.618, 1] }
```

**2.0**

```ts
style: {
  levels: [
    { ratio: 0 },
    { ratio: 0.382 },
    { ratio: 0.5, color: '#f5a623' },          // one rung recoloured
    { ratio: 0.618, label: 'golden' },         // one rung relabelled
    { ratio: 1, enabled: false },              // hidden without being forgotten
  ],
}
```

`FibLevel` is `{ ratio, color?, enabled?, label? }`. A level with no `color`
takes `levelColor(ratio)`, the one statement of the conventional colour per
ratio, shared by every fib and gann tool and by the migration, so 0.618 reads
the same on every tool. The frozen defaults are exported (`DEFAULT_FIB`,
`DEFAULT_FIB_FAN`, `DEFAULT_GANN_BOX`, `DEFAULT_GANN_FAN`,
`DEFAULT_FIB_TIME_ZONE`); copy one with `cloneLevels` before editing it. A
level editor in the host is a list of these objects; the widget tier ships
one.

## 5. `zIndex` and paint order

`Drawing.zIndex` is required on the type. `add()` accepts a `DrawingInput`
and fills in `0`, so a host that builds drawings through `add` changes
nothing. A host that constructs a `Drawing` object by hand (a fixture, a
server-side generator typed as `Drawing`) adds `zIndex: 0`.

`drawings()` returns paint order, not creation order: below zero paints under
the series, at or above zero over it, ties by list order. A host that showed
the list as "most recent first" sorts by `createdAt`, which is now a field:

```ts
const newestFirst = [...draw.drawings()].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
```

The ordering verbs are `setZIndex(id, z)`, `bringToFront(id)` and
`sendToBack(id)` (which stay on their side of the series), and
`sendBehindSeries(id)` and `bringAboveSeries(id)` (which cross it).

## 6. `magnet` takes a mode

**1.9.x**

```ts
new DrawingController(chart, { magnet: true });
```

**2.0**

```ts
new DrawingController(chart, { magnet: 'strong' });   // what true meant
new DrawingController(chart, { magnet: 'weak' });     // pulls only when an O/H/L/C is within a few px
draw.setOptions({ magnet: 'off' });
draw.magnetMode();                                    // 'off' | 'weak' | 'strong'
```

`true` and `false` are still accepted and mean `'strong'` and `'off'`, so
nothing has to change; `'weak'` is the mode most terminals want, because a
click on open space then lands where it was made. Either mode paints a ring
where the next click will land.

## 7. `chart.renderer` is `chart.rendererKind`

```ts
// 1.9.x had no such property. In 2.0:
const chart = createChart(el, { renderer: 'auto' });   // 'canvas2d' (default) | 'webgl2' | 'auto'
chart.rendererKind;                                     // what the chart actually paints with
```

`chart.renderer` exists as the same value under the name it first shipped
with in the 2.0 development line; it is deprecated and goes in 3.0.0, so new
code reads `rendererKind`. The default
is `'canvas2d'` and is pixel-identical to 1.9.2, so a host that passes no
option sees no change. `'webgl2'` needs `import 'openalgo-charts/webgl'` and
throws without it; `'auto'` is the silent form. A GPU backend that loses its
context moves the chart to `canvas2d` for the session and emits
`renderer:fallback`.

## 8. New `ChartOptions`, and the one that changes a default

Four keys are new on `ChartOptions`. Three are opt-in, and a host that does
not set them sees no change; the fourth is on by default.

| Key | Default | What it does |
|---|---|---|
| `animZoom` | `true` | Ease a wheel zoom over a few frames instead of landing the whole step on one. **On by default.** |
| `zoomAnchor` | `'cursor'` | What a wheel zoom holds still: the bar under the cursor (what 1.9.x did), or `'right'`, the latest bar. |
| `renderer` | `'canvas2d'` | Which backend paints the series; section 7. |
| `renderBackend` | unset | Build the backend yourself, one call per pane, bypassing `renderer`. |

**The eased wheel zoom is a visible change for every 1.9.x host.** In 1.9.2 a
wheel tick landed its whole step on one frame, while a flick already glided
to a stop, so the chart glided when panned and jumped when zoomed. In 2.0 the
zoom eases in log space (`ZoomGlide`), and the first frame's step is applied
on the wheel event itself, so `barSpacing` has already moved when anything
looks at it synchronously and a new tick folds into a running glide without a
jump. The glide lands on exactly the bar spacing the single-frame step would
have produced; what changes is that for a few frames after the tick the chart
is still on its way there.

A host that wants the 1.9.2 behaviour, or one whose tests dispatch a wheel
event and assert the final range on the same or the next frame, turns it off:

```ts
const chart = createChart(el, { animZoom: false });   // the single-frame step of 1.9.2
```

`zoomAnchor` does not change the default. `'right'` keeps the most recent bar
pinned while history stretches away from it, which is what a live chart
usually wants:

```ts
const chart = createChart(el, { zoomAnchor: 'right' });
```

Neither is re-appliable through `applyOptions`; both are decided at
construction, like `renderer`.

## 9. Custom drawing tools

A tool registered with `registerDrawingTool` in 1.9.x still registers. Three
optional fields are new on `DrawingTool`, and one read has moved:

- `defaultText?: DrawingText` merges under the caller's `text` the way
  `defaultStyle` merges under `style`.
- `settings?: SettingsSchema` declares the fields a properties panel may show
  (`drawingSettingsSchema(toolId)` returns it). Declare only fields your
  `draw` reads; a tool without one gets the plain line fields.
- `angleLock?: boolean` opts a two-point tool into the Shift 45 degree lock.
- `constrain?(points, handle)` returns the anchors to keep after one moved
  (`handle` is the dragged index, `null` for a `points` patch). The position
  tools use it to hold the stop and the target on opposite sides of the entry.
- `ExpandContext` gained optional `toPixel` / `fromPixel`, present when the
  host can map coordinates, so an `expand` default can be sized in pixels and
  fall back to chart units without them.
- A `draw` that read `style.text` reads `drawing.text?.value`; one that read
  `style.levels` as numbers reads `level.ratio`, and should skip a level whose
  `enabled` is `false`.

The position tools themselves changed how they place: two clicks (entry,
then target) instead of one, with the stop derived at 1:2 and the direction
read from where the target landed. A 1.9.x position box loads unchanged; only
new placements take the new defaults.

## 10. Things that did not change

- Every `draw:*` event name and payload.
- `undo`, `redo`, `canUndo`, `canRedo`, `clear`, `remove`, `get`, `add`,
  `update`, `setTool`, `activeTool`, `finish`, `copy`, `cut`, `paste`.
- `matchDrawingShortcut` and `drawingShortcuts()`. `keyToDrawingAction` is
  new and optional: a pure mapping of the editing chords (undo, redo, copy,
  cut, paste, duplicate, delete, arrow nudge) the host can wire instead of
  its own switch.
- Anchors are `{ time, price }`, never pixels.
- The chart's `click`, `drag`, `drag:end` and `crosshair:move` payloads only
  grew (`modifiers`, `pointerType`, `pressure`, `samples`); no existing field
  changed.
- The engine ships no DOM. The rail, dialogs and menus stay yours, or come
  from `openalgo-charts/widget` if you would rather not write them.

## 11. A checklist

1. Bump to `openalgo-charts@2.0.0`. Run the type-checker: every `style.text`
   and `levels: number[]` site is reported.
2. Find every read of the saved drawings payload that is not `fromJSON`, and
   wrap it in `migrateDrawings(...)`. `fromJSON` and `restoreState` need
   nothing.
3. Replace `selected()` with `selection()` wherever a bulk action or a
   properties bar assumed one member.
4. If a custom tool reads text or levels, update its `draw`, and give it a
   `settings` schema so the properties panel offers only what it reads.
5. Optional: `magnet: 'weak'`, `renderer: 'auto'` with the webgl tier, and
   `zoomAnchor: 'right'` for a live chart.
6. Wheel-zoom once. The zoom now eases; if that is unwanted, or a test asserts
   the final range synchronously after a wheel event, pass `animZoom: false`.
7. Open a chart drawn under 1.9.x and check the drawings, their text and the
   fib ladders are where they were. The migration is tested, but the check
   costs a minute and it is your users' work.
