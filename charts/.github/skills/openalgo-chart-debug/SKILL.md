---
name: openalgo-chart-debug
description: Diagnose an openalgo-charts problem - blank or invisible chart, bars in the wrong place, unknown series type or indicator errors, misaligned indicators, drawings that drift, a chart that will not repaint or resize, live ticks not appearing, linked charts out of step, stale cached prices, an unknown interval code, or a broken bundle import. Use when a chart is not behaving as expected.
argument-hint: "[symptom]"
allowed-tools: Read, Bash, Glob, Grep
---

Diagnose before changing anything. Most openalgo-charts bugs are one of a small set of known causes, and guessing at a fix usually adds a second bug on top of the first.

## Step 1 - ground yourself in the actual install

```sh
node -p "require('./node_modules/openalgo-charts/package.json').version" 2>/dev/null || echo "not a consumer app"
rg -n "from 'openalgo-charts" src app --glob '!node_modules'
```

You need the version and the exact set of tier imports before you can reason about anything. Never diagnose from memory of the API.

## Step 2 - match the symptom

| Symptom | First suspect | Confirm |
|---|---|---|
| Nothing renders, no error | container has zero height | inspect the element's computed height |
| Nothing renders after `setData` | data is empty, or times are not numbers | log `series.getData().length` and the first item |
| Bars bunched at the far left or right | `time` is in milliseconds | a value above 1e12 is milliseconds |
| Bars overlap or a candle draws twice | two bars share a time | times must be unique and ascending per series |
| Axis and crosshair show the wrong hours | the chart is on its default zone, `Asia/Kolkata` | `chart.timezone()`; set `timezone` or call `setTimezone` |
| VWAP restarts mid-afternoon, or a pivot frame spans two sessions | the chart's zone is not the instrument's | `chart.timezone()`; a `timeFormatter` relabels but does not move the calendar |
| `unknown series type "kagi"` | transform tier not imported | `rg "openalgo-charts/transform"` |
| `addIndicator` throws | indicators tier not imported | `rg "openalgo-charts/indicators"` |
| A tier is imported but its feature is missing | deep import created a second registry | check for any path containing `/dist/` or `/src/` in an import |
| Indicator plots misaligned with price | indicator on a different data set, or bar times differ | compare the first and last bar times |
| Series fills or is squashed into part of the pane | price-scale margins | margins are fractions of pane height, not data span |
| A volume overlay swallows the price series | overlay scale margins | `priceScaleId: ''` plus `marginTop` |
| Drawings drift after zoom or a session gap | anchors stored in pixels | anchors must be `{ time, price }` |
| A drawing shortcut does nothing | the library installs no key listener | the host must call `matchDrawingShortcut` |
| Chart does not resize | no `ResizeObserver`, or container is not measurable | call `chart.applySize(w, h)` manually |
| Custom primitive is blurry or offset | media px not multiplied by `dpr` | inspect the `draw` implementation |
| Live ticks never appear | subscription filter, or the builder was never seeded | log inside the tick handler before the builder |
| Live candle duplicates the last history bar | builder started unseeded | pass `seedFrom: lastHistoryBar` |
| Hidden-tab chart opens at the wrong zoom | old initial-size handling or an explicit host fit | 2.1.3 defers its first fit; inspect `applySize`, `navigation.defaultVisibleBars` and later host writes |
| Drawing preview disappears past the last candle, or a future freehand stroke is discarded | no hovered bar time in empty chart space | 2.1.5 maps the pointer through `coordinateToTime`; custom drawing hosts must provide it. Keep candle/tooltip time null where no bar exists |
| Plot drags stop vertical movement | explicit or saved horizontal preference, including a 2.1.3 layout | 2.1.4 defaults to `'both'`; select Axes > Mouse drag > Time and price or set `navigation.mousePan: 'both'`, preserving other preferences |
| Time-axis drag behaves differently on one page | stale copied or bundled runtime | left expands, right compresses; compare deployed bundle hashes and run the website navigation check |
| Replay suddenly reveals future bars | a host history/polling/reconnect writer bypasses replay | inspect every `setData`, `update` and `prependData`; see host integration |
| Old symbol data or resources return after closing | stale async continuation | verify generation, chart identity and disposed state after every await |
| Custom indicator intermittently missing on a split pane | registration marked ready before imports finish | await one shared pending registration promise |
| Chart snaps to the right edge on every update | `setData` called per tick | use `series.update(bar)` |
| Viewport jumps when older history loads | re-fitting after prepend | `prependData` preserves the window; do not `fitContent` |
| A linked crosshair marks the wrong bar | a logical index was copied between charts | it lines up only while both charts hold identical bars; the sync must convert index to time and back |
| Linked charts show different periods after a pan | the same index copy, on the viewport | use the group, or `followerRange`, never `setVisibleLogicalRange(other.getVisibleLogicalRange())` |
| A linked chart shows no crosshair at all | the instant is outside its coverage, or `whenMissing: 'hide'` | `group.crosshairIndex(chart)` returns `null`; an instant past its first/last bar is refused by design |
| Symbol sync changes nothing | no `onSymbol` on the member, or the host never reports the change | the engine has no instrument concept; check both halves |
| The last price is stale after switching symbols and back | a cache serving the forming bar | `withBarCache` never stores it; a hand-rolled cache usually does |
| Every load is cold out of hours | `to` is "now", past the entry's coverage | cap `to` at the newest bar the session table says can exist |
| `UnknownIntervalError` at subscribe time | the interval code is not built in and was never registered | it is the intended behaviour, not a regression; `registerInterval` or fix the code |
| A monthly chart buckets into minutes | `intervalToSeconds` on a calendar code | it throws now; use `resolveInterval` + `bucketStartOf` |
| A cut deleted nothing, or copied "into the void" | the async result was not awaited | `await draw.cut()` and check the boolean; read `draw.clipboard().lastError()` |
| Orders do not reach the broker | wrong layer | `chart.trading` is visualization only |
| Blank page in Next.js or SSR | chart created during server render | client-only component, create in an effect |
| Bare specifier fails in the browser | no bundler resolution | a path into `dist/`, an import map, or the script-tag files |
| `openalgo-charts.<tier>.standalone.js needs ... loaded before it` | a script-tag tier loaded before the base, or the widget before the draw tier | load the files in the order the message names, each once |
| `ERR_REQUIRE_ESM` from `require('openalgo-charts')` | a Node older than 20.19 or 22.12 cannot require ESM | `await import('openalgo-charts')`, or a newer Node |

[pitfalls](../openalgo-charts/references/pitfalls.md) has the full verified list with the reason behind each. [Host integration](../openalgo-charts/references/host-integration.md) covers request ownership, replay and lifecycle checks.

## Step 3 - read the console

The library throws named errors that identify the cause precisely rather than failing silently. Quote the exact message back to the user; it usually names the missing tier or the unknown id. Do not paraphrase it.

## Step 4 - narrow with the smallest possible repro

Strip to a chart, one series, and static bars. If that renders, add back one thing at a time. This resolves ambiguous cases faster than reading more of the host's code.

```ts
import { createChart, generateBars } from 'openalgo-charts';
const chart = createChart(el);
chart.addSeries('candlestick').setData(generateBars(1700000000, 200, 3600));
chart.fitContent();
```

If `generateBars` renders and the user's data does not, the bug is in the data, not the chart.

## Step 5 - report

State the cause, the evidence you have for it, and the one-line fix. If you could not reproduce or could not confirm the cause, say so rather than offering a speculative fix - a wrong fix to a charting bug is expensive to unwind.

Do not apply changes unless the user asked you to fix it, not just diagnose it.
