# React integration

*When to read this: mounting a chart inside a React component, feeding it props without recreating it, wiring host dialogs to chart events, or shipping it through Next.js.*

Source of truth: `src/core/chart.ts` (constructor and `destroy`), `website/pages/docs/frameworks.mdx`.

Every pattern below is taken from a real production consumer, a React + TypeScript trading terminal that lives in the **OpenAlgo application repo, not in this package**: `openalgo/frontend/src/components/trading/ChartPane.tsx` (774 lines, the lifecycle component), `openalgo/frontend/src/lib/trading/terminal.ts` (1840 lines, the orchestration layer), and the simpler `openalgo/frontend/src/components/portfolio/PortfolioLineChart.tsx`.

## The lifecycle rule

Create once in an effect, destroy in its cleanup, hold the instance in a ref.

```tsx
const containerRef = useRef<HTMLDivElement>(null);
const chartRef = useRef<Chart | null>(null);

useEffect(() => {
  if (!containerRef.current) return;
  const chart = createChart(containerRef.current);
  chartRef.current = chart;
  return () => {
    chart.destroy();
    chartRef.current = null;
  };
}, []);
```

**Never hold the chart in `useState`.** `createChart` returns a mutable object graph with a running rAF loop; storing it in state schedules a re-render on every swap and gives React a value it will try to compare. A ref is the correct box.

**Never call `createChart` in the component body, in `useMemo`, or in `useLayoutEffect` before the ref is attached.** The constructor reads `container.clientWidth/clientHeight`, calls `getComputedStyle`, writes inline styles, appends a live region, and installs a `ResizeObserver`, it needs a mounted element.

**`destroy()` does not reset the container's inline styles or ARIA attributes.** It stops the loop, disconnects the `ResizeObserver`, removes every input listener, removes the live region, and detaches each pane element. `position`, `display: flex`, `background` and `touch-action: none` stay on the element; re-creating into the same node is safe. The production terminal still clears `container.innerHTML = ''` before a rebuild, which is a cheap guard against anything a host appended.

## Keep chart orchestration outside React

This is the headline lesson from the production consumer. `terminal.ts` is a plain class, no React import. It owns the chart, the feeds, the tick path, the order lines, the drawing controller and the indicator list. React owns only the toolbar, the dialogs and the menu. The class exposes a constructor, `init(): Promise<void>`, `destroy()`, and imperative setters (`setInterval`, `setChartType`, `setProduct`, `setQty`, `loadSymbol`).

The React side is then a fixed shape regardless of how much the class does:

```tsx
useEffect(() => {
  const terminal = new TradingTerminal({ container, legendEl, callbacks, getTheme });
  terminalRef.current = terminal;
  terminal.init();
  return () => {
    terminal.destroy();
    terminalRef.current = null;
  };
}, [paneId, apiKey, wsUrl]);
```

Why this shape wins:

- A 60 fps tick stream never enters React state. The terminal writes the OHLC legend with `legendEl.innerHTML` and repaints the canvas; no component re-renders.
- Callbacks are a bag passed once at construction (`onReady`, `onToast`, `onWsState`, `onSymbolLoaded`, `onDrawChange`, `onIndicatorsChange`, `onIndicatorSettings`, `onDrawSelect`, `onDrawTextEdit`). Only low-frequency, UI-shaped events reach `setState`.
- Unmount is one `destroy()` call, no per-subscription cleanup list to keep in sync.
- The chart can be rebuilt (theme change, chart-type change) without React knowing: `buildChart()` snapshots drawings to JSON, destroys the chart, creates a new one, and re-applies indicators, grid, drawings and price lines.

**Callbacks that read the instance must go through the ref, not a closure variable.** In the production effect the callback bag is built before `new TradingTerminal(...)` assigns `terminal`, so a callback body that referenced the local would read `undefined`. It reads `terminalRef.current` instead.

**Guard every `setState` from an async callback with a liveness flag.** The terminal's `init()` awaits network calls; the pane can unmount mid-flight. `ChartPane` keeps `aliveRef` and every callback starts `if (!aliveRef.current) return`. The class keeps its own `destroyed` flag and re-checks it after each `await`.

## Feeding data on prop change

Never tear the chart down to change data. Keep the series handle next to the chart handle and drive it from a second effect.

```tsx
useEffect(() => {
  seriesRef.current?.setData(bars);
}, [bars]);
```

| Call | Use when | Cost |
|---|---|---|
| `series.setData(items)` | the whole array changed, new symbol, new interval, a recomputed transform | replaces all rows |
| `series.update(item)` | one tick arrived, updates the last item in place, or appends when the time advances | O(1) |
| `series.prependData(items)` | history paging pulled older bars | merges at the left edge |

The production terminal calls `setData` on every tick rather than `update`, because a transform (Renko, Range) can turn one new raw bar into a different number of elements, the transformed array is recomputed wholesale. Use `update` only when the series maps 1:1 to raw bars.

**Preserve the viewport across a data reload.** `setData` does not move the scales, but a prepend shifts every logical index:

```ts
const before = chart.getVisibleLogicalRange();
series.prependData(older);
chart.setVisibleLogicalRange({ from: before.from + older.length, to: before.to + older.length });
```

Measure the shift rather than assuming `older.length` when a transform sits between raw bars and the series.

**Effects that recreate the chart must list only genuinely identity-bearing deps.** `PortfolioLineChart` depends on `[series, format, mode, appMode]` and rebuilds; that is correct there because the caller memoizes `series`. An unmemoized array or inline arrow in the dep list rebuilds the chart on every parent render.

## Resizing

The chart installs a `ResizeObserver` on its container in the constructor and calls `applySize(contentRect.width, contentRect.height)` itself. **Do not add a window resize listener, and do not pass width/height props.** Size the container with CSS and let it reflow.

Call `chart.applySize(width, height)` yourself only when `ResizeObserver` is undefined (`_observeSize` early-returns) or when you are driving layout imperatively. It early-returns when the size is unchanged, so a redundant call is free.

Full-screen transitions need no chart code: `ChartPane` calls `element.requestFullscreen()` and lets the observer handle the geometry, tracking `fullscreenchange` only to re-portal its menus.

## Wiring host UI to chart events

The engine is canvas-only and ships no DOM. Anything with a form, a dialog or a menu is the host's, driven by an event.

```tsx
// The gear on an indicator's on-chart legend row.
const off = chart.on('indicatorSettings', (p) => {
  const { instanceId } = p as { instanceId: string };
  openSettingsDialog(instanceId);
});
// off() to unsubscribe; chart.destroy() drops every subscription anyway.
```

| Chart hook | Host UI it drives |
|---|---|
| `chart.on('indicatorSettings', cb)` | the indicator settings dialog; payload is `{ instanceId, indicatorId, paneIndex }` |
| `chart.on('indicatorRemoved', cb)` | re-read `chart.indicators()`, the legend's own x can remove one behind your back |
| `chart.on('draw:tool' \| 'draw:select' \| 'draw:add' \| 'draw:remove' \| 'draw:update', cb)` | the drawing rail's enabled state and the style popover |
| `chart.subscribeCrosshairMove(cb)` | an OHLC legend or tooltip; `e.bar`, `e.index`, `e.point` |
| `chart.subscribeClick(cb)` / `chart.subscribeDrag(move, end)` | order-line cancel and drag-to-modify |
| `chart.setHistoryLoader(fn)` | infinite scroll; every exit path must call `chart.historyLoadComplete()` or paging stops for the session |

Build the settings form from the descriptor, not per indicator. `registeredIndicators()`, `indicatorStyleInputs(descriptor)` and `indicatorDefaults(descriptor)` give a field list that one generic component renders for every indicator. See [indicators](indicators.md).

Drawing tools: import `openalgo-charts/draw` lazily on first use, construct one `DrawingController` per chart, and re-attach it after any rebuild by round-tripping `toJSON()` / `fromJSON()`. See [drawing-tools](drawing-tools.md).

Symbol and interval switching are plain imperative setters on the orchestration class, `setInterval(iv)`, `setChartType(v)`, `loadSymbol(row)`. React sets its own display state and forwards the call; it never diffs chart internals.

## Strict Mode

React 18 Strict Mode mounts, unmounts and remounts every effect in development. The chart survives because `destroy()` is complete and `createChart` is idempotent against an already-used container. To keep it clean: put the create/destroy pair in one effect with a returned cleanup (never split them across two effects); null the ref in the cleanup so the second mount cannot see a destroyed instance; guard async work with a liveness flag captured per effect run; and do not try to memoize the chart across the double invoke, building a second chart and throwing it away is the intended behaviour.

## Next.js and SSR

`createChart` touches `document` and `window` at construction. It must never run on the server.

Option 1, `useEffect` alone. Effects do not run during SSR, so the component above works unchanged in the App Router (mark the file `'use client'`).

Option 2, dynamic import when you also want a separate chunk or want to skip the server render of the chart component:

```tsx
const Chart = dynamic(() => import('../components/Chart'), { ssr: false });
```

In the App Router, `ssr: false` is allowed only inside a Client Component, so this line lives in a small `'use client'` wrapper, not in a Server Component.

**Importing is safe anywhere; creating is not.** Evaluating `openalgo-charts` or any of its tiers touches no DOM, so a top-level import works in a module a server also evaluates, including a Server Component. CI holds this: `npm run skills:coverage` imports every built tier in Node and fails if module evaluation touches the DOM. What must stay in the browser is the call to `createChart` or `createWidget`, which belongs in an effect. A Server Component can import the module, but it cannot hold a chart, or pass one (or a feed with functions) to a Client Component as a prop: build both in the client module. Tier imports for their registration side effect (`import 'openalgo-charts/indicators'`) are safe at the top of any module, or can wait for an `await import(...)` inside the effect when you want them out of the first chunk.

`ShortcutManager` persistence is already guarded (`typeof localStorage === 'undefined'`), so `persist: true` is safe in a test or SSR environment.

## A complete component

```tsx
'use client';
import { useEffect, useRef } from 'react';
import { createChart, type Bar, type Chart, type SeriesApi, type SeriesType } from 'openalgo-charts';

interface Props {
  bars: Bar[];
  seriesType?: SeriesType;
  ariaLabel?: string;
  onHover?: (bar: Bar | null) => void;
}

export function ChartPane({ bars, seriesType = 'candlestick', ariaLabel, onHover }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const seriesRef = useRef<SeriesApi | null>(null);
  // Latest callback without making it an effect dependency.
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;

  // Create once. seriesType is in the deps because a series type cannot change
  // in place, see chart-types.md.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let alive = true;

    const chart = createChart(el, { ariaLabel });
    chartRef.current = chart;
    seriesRef.current = chart.addSeries(seriesType);
    chart.subscribeCrosshairMove((e) => {
      if (alive) hoverRef.current?.(e.bar);
    });

    return () => {
      alive = false;
      chart.destroy();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [seriesType, ariaLabel]);

  // Feed data without recreating anything.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || bars.length === 0) return;
    series.setData(bars);
    chartRef.current?.timeScale.fitContent(bars.length);
  }, [bars]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}
```

The container needs a resolved height. A parent with `position: absolute; inset: 0` or an explicit `height` works; a bare `height: 100%` inside an auto-height parent gives the chart zero pixels and it renders nothing.

## Vue and plain JS hosts

Same two-step contract, different hook names. Vue 3: `createChart` in `onMounted` with a template ref, `chart.destroy()` in `onBeforeUnmount`, chart held in a `shallowRef` or a plain `let`, **not** in `ref()` or `reactive()`, which hand back a deep proxy the library does not recognise as its chart; the composable, the component and the failure modes are in [vue-integration](vue-integration.md). Svelte: `onMount` returning the destroy function. Angular: `ngAfterViewInit` / `ngOnDestroy` with `@ViewChild`. Plain JS: call `createChart(el)` once and `chart.destroy()` when you remove the node. Full snippets in `website/pages/docs/frameworks.mdx`.

The orchestration-class pattern is framework-independent and is the recommended shape for any host beyond a single static series.

## Related

[core-api](core-api.md) · [events-and-state](events-and-state.md) · [feeds-and-live](feeds-and-live.md) · [indicators](indicators.md) · [drawing-tools](drawing-tools.md) · [bundling-and-tiers](bundling-and-tiers.md) · [pitfalls](pitfalls.md)
