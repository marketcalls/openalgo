# OpenAlgo Charts architecture diagram: update brief

## Current diagram: 2.6.4, updated 2026-10-14

The current SVG replaces the old seven-row capability list with explicit ownership
boundaries and data flow. The old layout had received updated numbers but did not
explain the workspace, alert, replay and feed changes shipped during September.

`docs/architecture-diagram.svg` is the editable source used by README and
ARCHITECTURE.md. `website/public/architecture-diagram.svg` is its identical website
copy, refreshed by the site's sync script. The intrinsic size is 1280 by 1520;
README displays it at 920 pixels with a link to the full-size vector.
The site's light theme shows `website/public/architecture-diagram-light.svg`,
which the same sync step generates from the docs file with
`website/scripts/diagram-light.mjs`. That script maps every colour to its light
counterpart and stops the build on a colour it does not know, so a colour added
to the dark SVG needs its light pair added to the map in the same change.

The map must preserve these distinctions:

- The host supplies custom UI or the optional widget, adapters, instrument lookup,
  chart selection and workspace activation. Credentials, broker execution and
  external notification delivery remain host responsibilities.
- The base contains the loading pipeline, shared DataLayer and time scale,
  independent price scales, the study registry and primitive contracts, chart interaction,
  alerts, comparisons, replay groups, linking and rendering.
- Loading snapshots reach series through host wiring. Data-flow arrows are not
  automatic API connections or an import/dependency graph.
- Closed bars can be cached; the live tail must be refreshed. Optional open
  interest is a level: aggregation retains the last observation and never sums
  it. Missing OI remains absent, not zero.
- Alerts default to bar-close evaluation. A threshold drag previews a draft and
  commits once. Restored lifecycle state and external delivery remain distinct.
- Group replay follows when observations become available, not only the candle's
  opening timestamp. Host callbacks perform linked symbol and interval changes.
- Appearance links use structural host adapters in base. Drawing replication
  stays in the draw tier, requires matching symbol and exchange, and preserves
  local history and persisted lineage across rebuilt charts.
- Anchored VWAP and fixed-range Volume Profile are time-anchored analysis drawings.
  Grouped timeline events and clustering remain in base; the widget owns details
  UI, and hosts supply their event data and optional detail loader.
- The workspace tier provides documents, templates, revisioned catalogs and
  asynchronous storage. It does not render or activate a chart grid itself; the
  widget's `createChartGrid` (2.5.4) does, for widget cells, and a custom host still can.
- Canvas 2D supplies the base renderer. Optional WebGL2 draws supported series;
  axes, text and primitives remain 2D. Study and profile calculation stays on CPU.
- Base plus eight optional ESM entries makes nine tiers. Custom study contracts
  belong to the base registry; the indicator tier adds built-ins and helpers.

Measurements were rechecked with `npm run size` and the built registries on
2.5.2: base 95.04 kB, indicators 29.84 kB, draw 40.73 kB, profile 14.96 kB,
transform 4.50 kB, trade 8.01 kB, workspace 5.55 kB, webgl 6.39 kB and widget
51.06 kB, all decimal Brotli. All tiers total 256.08 kB. Registry counts are
105 indicators, 87 drawing tools and 15 chart types with the transform tier loaded.

Rechecked on 2.5.4: base 117.42 kB, indicators 36.27 kB, draw 42.53 kB, profile
14.96 kB, transform 4.50 kB, trade 8.01 kB, workspace 8.67 kB, webgl 6.39 kB and
widget 71.33 kB; all tiers 310.09 kB. Registry counts are unchanged. The widget chip
names the grid and go-to panel, and the description names pane collapse, study
output targets and drawing policies.

Rechecked on 2.5.5: base 119.15 kB, indicators 36.34 kB, draw 44.87 kB, profile
14.96 kB, transform 4.50 kB, trade 16.64 kB, workspace 9.99 kB, webgl 6.39 kB and
widget 82.30 kB; all tiers 335.15 kB. Registry counts are unchanged. The trade chip
names accounts, the workspace chip watchlists and the widget chip the watchlist and
news panels; the description names the movable price pane, viewport drawings and
tick schedules.

Rechecked on 2.5.6: base 125.39 kB, indicators 36.44 kB, draw 48.42 kB, profile
14.96 kB, transform 4.50 kB, trade 16.69 kB, workspace 10.47 kB, webgl 6.39 kB and
widget 92.72 kB; all tiers 355.97 kB. Registry counts are unchanged. Study policies,
the draw order, data variants, the session calendar and the widget's undo timeline
change no box or arrow: they live inside the base engine, draw and widget chips the
diagram already has.

Rechecked on 2.5.7: base 126.91 kB, indicators 36.44 kB, draw 48.42 kB, profile
14.96 kB, transform 4.50 kB, trade 16.69 kB, workspace 10.47 kB, webgl 6.39 kB and
widget 92.72 kB; all tiers 357.50 kB. The release splits the chart's internals into
collaborator modules inside the base engine and changes no box, arrow or chip.

Rechecked on 2.5.8: base 130.37 kB, indicators 40.38 kB, draw 48.42 kB, profile
14.96 kB, transform 4.50 kB, trade 16.69 kB, workspace 10.47 kB, webgl 6.39 kB and
widget 92.72 kB; all tiers 364.91 kB. The level of detail, the allocation-free series pass, in-place study plot
writes, the repaint scope, the single animation loop and primitive hit boxes live inside
the base engine, and the sixteen built-in tails inside the indicator tier, so the release
changes no box, arrow or chip; "Invalidation + frame coalescing" in the rendering box
still describes it. The base, indicator and all-tier figures (the chips and the
`<desc>`) move, and are taken from `npm run size` on the 2.5.8 release build like every
recheck above, never carried over from earlier notes.

Rechecked on 2.5.9: base 131.68 kB, indicators 40.38 kB, draw 55.61 kB, profile
14.96 kB, transform 4.56 kB, trade 16.69 kB, workspace 11.33 kB, webgl 6.93 kB and
widget 99.64 kB; all tiers 381.78 kB. Registry counts are unchanged. Drawings per instrument,
the drawing gestures and the widget's drawing UI live in their tiers and add no box to the diagram.

Rechecked on 2.5.10: base 134.69 kB, indicators 40.43 kB, draw 57.98 kB, profile
14.97 kB, transform 4.55 kB, trade 16.69 kB, workspace 11.53 kB, webgl 6.93 kB and
widget 121.36 kB; all tiers 409.13 kB. The widget's seven first-use parts (18.19 kB) are
files beside the widget tier, not a tier, so they get no chip. Registry counts are unchanged.
Session phases, session shading and the link channels live inside the base engine's existing
boxes, and the chart grid, bottom bar and saved layouts inside the widget tier, whose `<desc>`
names them; the release adds no box or arrow.

Rechecked on 2.6.4 with `npx size-limit` on the release build: base 137.65 kB, indicators 43.02 kB, draw 58.44 kB, profile 20.83 kB, transform 6.23 kB, trade 16.88 kB on its own (base + trade 154.52 kB), workspace 11.73 kB, WebGL2 6.97 kB, widget 124.94 kB, and 426.67 kB for all tiers. Registry
counts: 112 indicators (Trend 40, Momentum 31, Volatility 23, Volume 18), 87 drawing tools
and 15 chart types with the transform tier loaded, which also registers six series
transforms the chart applies itself. The `/indicators` chip says 112 built-in studies, and
the title and version label name 2.6.4. In-chart transforms, the study bar source and the
typed event map live inside the base engine's existing boxes, and the classic tier scripts
are a second form of the same tiers; the release adds no box or arrow.

Source references: `src/index.ts`, `src/feed/data-controller.ts`,
`src/feed/instrument.ts`, `src/model/bar.ts`, `src/core/pane.ts`,
`src/alerts/controller.ts`, `src/replay/group.ts`, `src/link/group.ts`,
`src/draw/drawing-link.ts`, `src/draw/analysis.ts`, `src/primitives/event-markers.ts`,
`src/widget/event-details.ts`,
`src/compare/controller.ts`, `src/workspace/`, `src/render/backend.ts`,
`src/trade/order-engine.ts` and `package.json` exports.

When updating the asset, check both SVG copies and the light variant,
README/ARCHITECTURE alt text, the website component's intrinsic dimensions and
cache query, and the website guide.
Render at full size and README width in Chromium, Firefox and WebKit; verify text
bounds, label collisions and actual pixels. Keep historical measurements below
as a record of the earlier redraw.

## Historical update brief: 1.8.2

Written 2026-08-28 against openalgo-charts 1.8.2.

> **Status: implemented in `d0eb679`.** The diagram was redrawn and now ships as
> `docs/architecture-diagram.svg`; the PNG is gone. This document is kept as the
> record of what was wrong, what the measured figures were, and why each change
> was made, so the next redraw starts from evidence rather than memory.
>
> The current diagram and measurements are documented above.

Build brief for the replacement of `docs/architecture-diagram.png` in
`openalgo-charts`, shown in `README.md` at 920 px wide.

Every number below is measured, not quoted. Sizes come from `npx size-limit` on
the current build; the indicator and tool counts come from the registry at
runtime (`registeredIndicators()`, `registeredDrawingTools()`). Where a figure is a budget rather than a measurement it says so.

---

## 1. The good news

**Keep the diagram.** The layered form is right, the dark treatment suits the
subject, and the left-hand rail plus the bundle-tier legend are both good ideas.
This is not a redraw from nothing. It is the same picture with the contents
brought up to 1.8.2, one row added, and three numbers corrected.

What follows is scoped accordingly: what is wrong, what is missing, and the
exact replacement text.

---

## 2. What is factually wrong

| The diagram says | Measured reality |
| --- | --- |
| `Dependency-free HTML5 Canvas Charting Engine - under 50 KB` | Base engine is **59.05 kB** Brotli against a 60 kB budget. The full package is **118.14 kB**. The under-50 claim has not been true for several releases |
| Bundle tiers: `base`, `/trade`, `/transform`, `/profile` | **Six** tiers. `/indicators` and `/draw` are missing, and they are the two largest after base |
| `Indicators: EMA / RSI / ATR / Supertrend` | **91 built-in indicators**, and they are their own loadable tier, not four names inside a drawables row |
| `Transforms: Renko / Heikin-Ashi / P&F` | Six: Renko, Range, Point and Figure, Kagi, Line-break, Heikin-Ashi |
| `Profiles: Volume / Market / Footprint` | Five: Volume Profile, TPO, Market Profile, Footprint, Orderflow |
| `IST to UTC time` | Full IANA timezone support. IST is the default, not the extent of it |

The size claim is the one that matters most. It is the headline, it is the first
thing a reader evaluates the library on, and it is wrong by 18 percent.

Note also that `ARCHITECTURE.md` section 2 still says *three loadable tiers* and
repeats the *under 50 KB* promise. The diagram inherited both. Worth fixing in
the same pass so the two do not disagree again.

### Measured sizes, all Brotli

| Tier | Measured | Budget |
| --- | --: | --: |
| Base engine | 59.05 kB | 60 kB |
| Base + trade | 66.66 kB | 68 kB |
| Indicator tier | 25.04 kB | 27 kB |
| Draw tier | 13.13 kB | 14 kB |
| Transform tier | 2.66 kB | 5 kB |
| Profile tier | 10.66 kB | 11 kB |
| Everything | 118.14 kB | 120 kB |

---

## 3. What is missing

**The draw tier.** Forty-three drawing tools with their own controller,
clipboard, hit-testing and persistence layer, at 13.13 kB. An entire product
surface with no representation on the page at all.

**The indicator descriptor system.** The diagram shows indicators as four
formula names. What actually ships is an extension contract: a descriptor
declares inputs, plots and a `calc`, and may additionally supply `markers`,
`draws`, `levels`, `background`, `barColors`, `fills`, `alerts`, `table`,
`calcTail` and an `attach` lifecycle. Third parties register their own through
`registerIndicator`, and `createTier2Indicator` covers indicators needing data
the chart does not hold. This is the library's main extension point and it is
invisible.

**The session controllers.** Replay, comparison, multi-chart link groups, the
draw controller and the shortcut manager. Five real subsystems, none shown.

**Tick-size awareness.** `PriceScaleOptions.minMove` carries the instrument tick
through to rounding and to indicator `calc` via the context. Added in 1.8.2 and
worth a mention in the model row.

---

## 4. The updated diagram

Keep the existing structure: title, subtitle, left rail, stacked layer rows with
a coloured label chip, bundle-tier legend bottom right. Change the contents as
below.

### Subtitle

Replace `Dependency-free HTML5 Canvas Charting Engine - under 50 KB` with:

```
Dependency-free HTML5 Canvas charting engine - 59 KB base, 118 KB everything
```

Two honest numbers read better than one round wrong one, and the gap between
them is itself the argument for the tier system.

### Rows, top to bottom

**PUBLIC API** (unchanged treatment, one addition)

```
createChart    addSeries    registerIndicator    subscribeCrosshairMove    takeScreenshot
```

`registerIndicator` earns its place next to `createChart`: it is how the library
gets extended, and the current row implies read-only consumption.

**RENDERING** (unchanged, it is still accurate)

```
Render loop (invalidation)    Panes: base + overlay canvas    Crosshair / Axes / Grid    Themes: light / dark
```

**DRAWABLES** (recomposed; the old row conflated four different things)

```
Chart types: candles / bars / line / area    91 built-in + custom indicators    43 drawing tools    Primitives: price lines / markers / events
```

**Custom indicators must be legible as a feature on the page**, not inferred
from an API name. Say `91 built-in + custom indicators` in the drawables row and
carry the point into the caption below the stack:

```
Custom indicators: any host can register its own with the same descriptor
contract the 91 built-ins use. No fork, no build step.
```

That last sentence is the differentiator against every charting library that
ships a fixed indicator list, and the current diagram gives it nothing.

**SHARED MODEL** (one addition)

```
DataLayer (gapless logical index)    Time scale (shared)    Price scale (per pane, tick-aware)    Transforms: Renko / Range / P&F / Kagi / Line-break / HA
```

**SESSION** (new row)

```
Replay    Compare    Link groups (multi-chart sync)    Shortcuts    Draw controller
```

Place it between SHARED MODEL and TRADE LAYER. Give it its own accent, distinct
from the teal used for rendering and model and from the red used for trade.

**TRADE LAYER** (unchanged, still accurate)

```
Order engine (state machine / OCO)    DOM ladder    Drag-to-modify chart trading
```

**FEEDS AND DATA** (one correction)

```
REST history    WebSocket live    Trade API    CandleBuilder: tick to OHLC    Timezone-aware (IANA, IST default)
```

**PROFILES**, currently squeezed into DRAWABLES, moves to its own short row or
joins the transform entry, listing all five: Volume Profile, TPO, Market
Profile, Footprint, Orderflow.

### Bundle tiers legend

The single highest-value fix on the page. Six chips, each with its measured
size, so a reader can price their own build:

```
base 59 KB    /indicators 25 KB    /draw 13 KB    /profile 11 KB    /trade 8 KB    /transform 3 KB
```

The `/trade` figure is the delta: 66.66 minus 59.05, rounded. Ordering by size
rather than alphabetically lets someone read down and stop when the budget runs
out, which is the actual question a reader brings to a tier legend.

### Left rail

Currently reads `OpenAlgo Platform`. That undersells a zero-dependency package
published to npm and usable in any host. Suggested: `Host application` as the
rail label, with `OpenAlgo Platform` as a named example beneath it. If the rail
stays single-purpose, at least note that the platform is one consumer rather
than the only one.

---

## 5. Style

The existing visual direction is working and should carry over: near-black
ground, rounded pill boxes, a single accent per layer, generous row spacing, no
icons. Keep it.

Three constraints for the update:

- **The new row must not crowd the stack.** Seven rows at 920 px is close to the
  limit. If it feels dense, drop PROFILES into the transform entry rather than
  giving it a row of its own.
- **Colour must stay meaningful.** Today teal marks rendering and model, red
  marks trade. The new session row needs its own hue, and the tier legend chips
  should match their tier colours rather than introducing a fourth scheme.
- **Keep the editable source.** The current PNG cannot be corrected without a
  redraw, which is part of why it drifted this far. Commit the source next to
  the export.

---

## 6. Checklist

The numbers in this checklist are the 1.8.2 ones it was written
against. Where a later release moved one, section 7 carries the current figure
and that is the one to check against.

- [ ] Subtitle reads 59 KB base, 118 KB everything. No "under 50 KB" anywhere.
- [ ] Six tier chips, each with its measured size.
- [ ] `/indicators` and `/draw` both present.
- [ ] Indicator count reads 91, stated as built-in **plus custom**.
- [ ] Custom-indicator caption present below the stack.
- [ ] Drawing tool count reads 43.
- [ ] Transforms list all six; profiles list all five.
- [ ] Session row present with replay, compare, link, shortcuts, draw.
- [ ] Timezone entry no longer says IST only.
- [ ] `registerIndicator` appears in the public API row.
- [ ] No icons, no emoji.
- [ ] Readable at 920 px.
- [ ] Editable source committed alongside the export.
- [ ] `ARCHITECTURE.md` section 2 corrected to six tiers, and its "under 50 KB"
      promise updated, so the prose and the picture agree.
- [ ] README size badge updated: it currently reads 53 KB / 111 KB, also stale.
- [ ] `.size-limit.json` draw-tier label corrected: it says 34 drawing tools, the
      registry reports 43.

---

## 7. Appendix: the 1.8.3 correction

Sections 1 to 6 are the record of the 1.8.2 redraw and are left as written. This
appendix records the next set of measurements, so the checklist above is read
against these numbers rather than the 1.8.2 ones where the two differ.

1.8.3 added its indicators in two passes: eight first, taking the registry from
91 to 99, then three more (`t3`, `hull-suite`, `consolidation-breakout`), taking
it to 102. The diagram was corrected after each. Nothing structural changed in
either pass: no row was added or removed, no element moved, no colour changed.
Seven numbers are text in `docs/architecture-diagram.svg` and were edited as
text. The figures below are the shipped ones.

### The SVG lives in two places

`docs/architecture-diagram.svg` is the one README and `ARCHITECTURE.md` point at.
`website/public/architecture-diagram.svg` is the copy the documentation site
serves, and the site cannot reach up out of its own build to read the first. The
two must stay byte-identical: edit one, copy it over the other, and diff them
before committing. A number corrected in only one of them is worse than a number
corrected in neither, because the second reader has no reason to doubt it.

### Measured, 1.8.3 as shipped

| Tier | Measured | Budget in `.size-limit.json` |
| --- | --: | --: |
| Base engine | 59.06 kB | 60 kB |
| Base + trade | 66.67 kB | 68 kB |
| Indicator tier | 27.27 kB | 30 kB |
| Draw tier | 13.13 kB | 14 kB |
| Transform tier | 2.66 kB | 5 kB |
| Profile tier | 10.66 kB | 11 kB |
| Everything | 120.38 kB | 124 kB |

The eleven new indicators carried the tier past its old 27 kB limit, so that
budget was raised to 30 kB and the aggregate to 124 kB. The two have to move
together: `Everything` contains the tier, and every other tier sums to 93.11 kB,
so an aggregate below 93.11 plus the tier's 30 kB ceiling would fail while the
tier it contains passed. All seven rows pass as shipped, and the indicator-tier
label in `.size-limit.json` reads 102 built-ins.

Counts from the registry at runtime: 102 indicators, 43 drawing tools, 13 chart
types in the base bundle and 15 once the transform tier registers its two.

### What changed in the SVG

| Element | 1.8.2 | 1.8.3, first pass | 1.8.3, shipped |
| --- | --- | --- | --- |
| `<desc>` accessibility text | indicators 25 KB, everything 118 KB | indicators 26 KB, everything 119 KB | indicators 27 KB, everything 120 KB |
| Subtitle | 59 KB base, 118 KB everything | 59 KB base, 119 KB everything | 59 KB base, 120 KB everything |
| Drawables row, indicator chip | 91 built-in + custom indicators | 99 built-in + custom indicators | 102 built-in + custom indicators |
| Tier legend, `/indicators` chip | 25 KB, 91 built-in indicators | 26 KB, 99 built-in indicators | 27 KB, 102 built-in indicators |
| Tier legend, everything chip | 118 KB | 119 KB | 120 KB |
| Custom-indicator caption | the 91 built-ins use | the 99 built-ins use | the 102 built-ins use |

The first pass was digit for digit (91 to 99, 25 to 26, 118 to 119) and touched
no layout at all. The second pass is not: 99 to 102 adds a character to three
strings, so those three were checked against the boxes that hold them rather
than assumed.

- Drawables row chip, 16 px semibold, centred in a 350 px box: the longest line
  in that box grows by about nine px and still clears the border by a wide
  margin.
- `/indicators` legend caption, 13 px, centred in a 170 px chip: "102 built-in
  indicators" is the widest caption in the legend row and still sits inside the
  chip, ahead of its neighbours "Trading & order layer" and "Charting engine
  core" by a character.
- Custom-indicator caption, 16 px, centred in a 940 px box: one character on a
  line with well over a hundred px of slack.

Every size figure stayed the same width (26 to 27, 119 to 120), so no legend
chip moved. This is the property the SVG was adopted for and it is holding: two
releases of corrections, no redraw.

The base figure is unchanged at 59 KB across both passes: the new indicators
live entirely in the indicator tier, which is the tier system doing its job and
is worth knowing when the next reader asks whether adding indicators costs every
consumer bytes.

### Still true, not re-verified by measurement

The six tier chips, the seven rows, the transform list of six, the profile list
of five, the session row, the IANA timezone wording, `registerIndicator` in the
public API row and the drawing tool count of 43 are all unchanged from 1.8.2 and
were checked by eye against section 6 rather than remeasured.

## 2.0.0: a seventh tier chip

The WebGL2 render backend ships as its own tier, `openalgo-charts/webgl`, so the
legend row gained a chip. Seven tier chips plus "Everything" do not fit at the
170 px width the six were drawn at, so the row was re-spaced rather than
extended past the frame: every tier chip is 146 px wide on a 162 px pitch from
x=248, the Everything chip is 186 px, and the row still ends at x=1568 where it
did. The size figure dropped from 26 to 24 px and the caption from 13 to 12 px
so "102 built-in indicators", still the widest caption, sits inside the
narrower chip. Chips stay in descending size order, which puts `/webgl`
(6.38 KB, green, a hue the legend had not used) between `/trade` and
`/transform`. The `/webgl` caption reads "WebGL2 series backend".

Every figure in the legend, the `<desc>` and the subtitle was re-measured from
`npm run size` on the 2.0.0 build (base 66.41 KB, everything 146.11 KB); the
1.8.x figures the diagram had carried through several releases were replaced
in the same pass, which is the drift this file exists to record.

## 2.0.0: an eighth tier chip

The widget tier, `openalgo-charts/widget`, is the eighth bundle and the first
that is not an engine feature: it is the chrome (rail, top bar, status line,
dialogs, keymap) as a package. Eight tier chips plus "Everything" on the 162 px
pitch would run 144 px past the frame, so the row was re-spaced once more:
every tier chip is 136 px wide on a 144 px pitch from x=248, the Everything
chip is 168 px, and the row still ends at x=1568. The label dropped to 15 px,
the size figure from 24 to 22 px and the caption from 12 to 11 px so
"102 built-in indicators" still sits inside the chip. Descending size order
puts `/widget` (35.56 KB, rose, a hue the legend had not used) second, between
`base` and `/indicators`; its caption reads "Rail, top bar, dialogs, keys".

Every figure was re-measured from `npm run size` on the build that added the
tier: base 66.41 KB unchanged (the widget is a separate bundle and the base
row did not move), everything 146.11 KB to 181.67 KB, the subtitle 146 KB to
182 KB. The `<desc>` names the eighth chip. The layer count in the `<desc>` and
the README alt text stays at seven: the widget is a bundle, not a layer of the
engine, and the stack above the legend did not change.

## 2.0.0 release: every figure re-measured on the shipping build

The release pass changed two numbers and confirmed the rest. `npm run size` on
the 2.0.0 build (with the version string that ships) reads base 66.39 KB and
everything 181.65 KB, two hundredths under the 66.41 KB and 181.67 KB the
diagram carried from the widget pass, because the version string itself moves
the bundle. Both figures were substituted by matching the text of the chip
they sit in, not by searching for the old number, which is the failure mode
CLAUDE.md records for the README. The `<desc>` carries the same two values.

Confirmed unchanged by measurement on the same build: widget 35.56 KB,
indicators 27.27 KB, draw 25.12 KB, profile 10.66 KB, trade 7.61 KB (the
base + trade row reads 74.00 KB, so the delta over the base is unchanged),
webgl 6.38 KB, transform 2.66 KB. The subtitle's rounded "66 KB base, 182 KB
everything" still rounds correctly. Counts from the registry at runtime on the
same build: 102 indicators, 15 chart types, 51 drawing tools; the three
strings that carry them did not change. Eight tier chips, seven layers.

## Position tool merge: three chips re-measured

The two-click position tool merged after the release pass and lives in the
draw tier, so three figures moved and the rest did not. `npm run size` on the
merged build reads draw 25.82 KB (was 25.12), widget terminal 155.03 KB (was
154.34, budget raised from 155 to 156 kB) and everything 182.34 KB (was 181.65,
budget raised from 182 to 183 kB). The draw chip and the everything chip
changed, again by matching the text of the chip rather than the number, and
the `<desc>` carries the same two values. The subtitle's rounded "66 KB base,
182 KB everything" still rounds correctly. Base 66.39 KB, base + trade 74.00
KB, indicators 27.27 KB, profile 10.66 KB, webgl 6.38 KB, widget 35.56 KB and
transform 2.66 KB were confirmed unchanged on the same build.
`website/public/architecture-diagram.svg` is a byte copy of the docs file,
refreshed by `website/scripts/sync-lib.mjs` on every website build.

## 2.0.1: the version string moves four chips by three hundredths

The depth-key fix adds a few bytes to the base tier and the version string
changes with it. `npm run size` on the 2.0.1 build reads base 66.42 KB (was
66.39), base + trade 74.03 KB (was 74.00), widget terminal 155.06 KB (was
155.03) and everything 182.37 KB (was 182.34). The other six rows did not move.
Chips and `<desc>` substituted by matching the surrounding text; the rounded
subtitle still rounds correctly.

## 2.3.1: the lagging-refresh fix moves four chips by hundredths

The 2.3.1 patch changes `DataLoadingController` in the base engine and nothing
in any other tier, so the base chip and the three rows that include the base
moved and the rest did not. `npm run size` on the 2.3.1 build reads base
76.46 KB (was 76.52), base + trade 84.07 KB (was 84.13), widget terminal
181.60 KB (was 181.66) and everything 214.99 KB (was 215.04). Confirmed
unchanged on the same build: widget 42.41 KB, indicators 28.19 KB, draw
34.53 KB, profile 14.96 KB, trade 7.61 KB as a delta over the base, webgl
6.38 KB, transform 4.44 KB. Counts from the registry at runtime: 102
indicators, 85 drawing tools, 13 chart types in the base; the strings that
carry them did not change. The base chip, the everything chip, the subtitle
(which carries the exact figures) and the `<desc>` were substituted by
matching the surrounding text.

## 2.3.2: stream-driven repair grows the base by under a kilobyte

Stream-driven repair and provisional bars live in the base engine, so the base
chip and the three rows that include it moved. `npm run size` on the 2.3.2
build reads base 77.23 KB (was 76.46, budget raised from 77 to 78 kB), base +
trade 84.84 KB (was 84.07, budget raised from 85 to 86 kB), widget terminal
182.37 KB (was 181.60) and everything 215.76 KB (was 214.99). Confirmed
unchanged on the same build: widget 42.41 KB, indicators 28.19 KB, draw
34.53 KB, profile 14.96 KB, trade 7.61 KB as a delta over the base, webgl
6.38 KB, transform 4.44 KB. Counts from the registry at runtime: 102
indicators, 85 drawing tools, 13 chart types in the base. The base chip, the
everything chip, the subtitle and the `<desc>` were substituted by matching
the surrounding text.

## 2.4.0: coverage for ported studies moves four chips

Measured on the 2.4.0 build with `npx size-limit`, after the version string
was in place. The base engine reads 78.07 KB (was 77.23, budget raised from
78 to 79 kB) for the recompute guard, the per-bar wick and border colour, the
bar offset in the pane, the two marker glyphs and two edge positions, the
drawing hit layer and the bars-provider threading. The indicators tier reads
29.05 KB (was 28.19) for `securitySeries` and the Tier-2 combiner. The widget
reads 42.49 KB (was 42.41) for the two input types. Base + trade reads
85.68 KB (was 84.84), the widget terminal 184.14 KB (was 182.37, budget raised
from 183 to 185 kB) and everything 217.54 KB (was 215.76). Confirmed unchanged
on the same build: draw 34.53 KB, profile 14.96 KB, transform 4.44 KB; webgl
moved by one hundredth to 6.39 KB. Counts from the registry at runtime: 102
indicators, 15 chart types, 85 drawing tools, unchanged.

In the SVG: the subtitle's base figure, the base, widget, indicators, webgl
and everything chips, and the `<desc>` version. Nothing else moved.

## 2.4.5: workspace becomes the ninth tier

The measured release has nine exported entry points. The legend adds workspace
at 5.52 kB for validated documents, named catalogs and asynchronous storage.
Every chip now uses decimal kB: base 91.00, widget 48.30, indicators 29.84,
draw 35.43, profile 14.96, trade 8.01, webgl 6.39 and transform 4.50. Everything
is 243.96 kB. Runtime registries report 105 indicators, 15 chart types after
loading transform (13 in base) and 85 drawing tools.

The SVG keeps its 1600 by 1100 view box. Nine tier chips plus Everything each
use 146 px of width, on a 154 px pitch from x=36 to x=1422. The last chip ends
at x=1568, matching the right edge of the capability rows. Existing text sizes
and the footer stay unchanged. The visible subtitle, title, description and
website image cache key all identify 2.4.5. Earlier sections remain release
history and are not current measurements.
