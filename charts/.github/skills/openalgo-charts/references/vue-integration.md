# Vue integration

*When to read this: mounting a chart or the widget inside a Vue 3 component, feeding it props without recreating it, keeping it out of Vue's reactivity, or shipping it through KeepAlive or Nuxt.*

Source of truth: `examples/vue/` (the composable `use-openalgo-chart.js`, the component `openalgo-chart.js`, the page `app.js`), `website/pages/docs/frameworks.mdx` (its Vue 3 section, published at /docs/frameworks#vue-3, has the typed composable and the component's load, v-model and KeepAlive code), `tests/vue-reactivity.test.ts` (why the chart stays out of `ref()`, with Vue's own reactivity), `tests/e2e/vue-integration.spec.ts` (the example in Chromium, Firefox and WebKit).

Vue is a devDependency of this repository for the example and the tests. The package itself has no dependencies and no Vue plugin; support is the pattern below.

## The reactivity rule

**Never hold the chart, the widget, a series handle, a feed, a controller or a bar array in `ref()` or `reactive()`.** Both return a deep `Proxy`, not the object, and every object read through it comes back wrapped. Use `shallowRef`, a plain `let`, or `markRaw(x)` before `x` goes anywhere reactive (a store, `data()`, a `reactive({...})`).

```ts
const chart = shallowRef<Chart | null>(null); // .value is the chart itself
// NOT: const chart = ref<Chart | null>(null)  // .value is a Proxy of the chart
```

What goes wrong through the proxy, each held by `tests/vue-reactivity.test.ts`:

| Through `ref(chart).value` | Why | Effect |
|---|---|---|
| `new ReplayController(proxy)` | `src/model/replay-window.ts` keys a module `WeakMap` on the chart object; the widget reads it with its own chart | `isReplaying(widget.chart)` is false, so the widget's right-click order rows stay enabled during replay |
| `proxy.beginPick(...)` | `src/input/pick.ts` keys its registry on the receiver; `DrawingController.setTool` cancels picks through the chart it holds | the pick survives the drawing tool that should cancel it |
| `proxy.addSeries(...)` | the method runs with `this` = proxy, so the owner record holds a proxied `Pane` (`src/core/chart-series.ts`) | the chart itself answers `seriesType(series) === null`, `setSeriesType` returns false |
| `proxy.primarySeries()`, `proxy.panes()[0]` | reads through the proxy wrap their result | never `===` the handle the host already has |
| `addComparison(proxy, ...)` | `src/compare/controller.ts` keys controllers on the chart | a caller holding the chart sees no comparisons |
| `series.setData(ref(bars).value)` | `toBar` keeps an OHLC item as is | every bar is stored inside the chart as a proxy, read through a trap every frame |
| any call | every field read inside it is a proxy trap | a series created through the proxy pays it for its whole life |

Vue never proxies a DOM element, so the container is an ordinary template `ref`. Strings (symbol, interval, theme) are ordinary refs too.

## The composable

```ts
export function useOpenAlgoChart(container: Readonly<Ref<HTMLElement | null>>, setup: () => OpenAlgoChartSetup = () => ({})) {
  const chart = shallowRef<Chart | null>(null);
  const widget = shallowRef<Widget | null>(null);
  const series = shallowRef<SeriesApi | null>(null);
  let disposed = false;

  onMounted(async () => {
    const el = container.value;
    if (el === null) return;
    const options = setup();
    if (options.widget) {
      const { createWidget } = await import('openalgo-charts/widget'); // lazy tier
      if (disposed) return;                                           // unmounted while loading
      const w = createWidget(el, options.widget);
      widget.value = w; chart.value = w.chart; series.value = w.series;
    } else {
      const c = createChart(el, options.chart);
      chart.value = c; series.value = c.addSeries(options.seriesType ?? 'candlestick');
    }
  });

  onBeforeUnmount(() => {
    disposed = true;
    if (widget.value !== null) widget.value.destroy(); // the widget owns its chart
    else chart.value?.destroy();
    widget.value = null; chart.value = null; series.value = null;
  });

  return { chart, widget, series };
}
```

`onBeforeUnmount`, not `onUnmounted`: the container is still in the document when the chart tears down. The typed version is in the Vue 3 section of `website/pages/docs/frameworks.mdx`.

## Props to data

The component (`<OpenAlgoChart symbol interval theme feed widget options>`) creates the chart once. A prop change is a call on it, never a new chart:

```ts
let generation = 0;
async function load() {
  const c = chart.value, s = series.value;
  if (!c || !s) return;
  if (widget.value) { widget.value.setSymbol(props.symbol, props.exchange); widget.value.setInterval(props.interval); return; }
  const ticket = ++generation;
  s.setData([]);                                             // old instrument out first
  c.setDataContext({ symbol, exchange, interval });          // studies and alerts rescope
  const bars = await props.feed.getBars({ symbol, exchange, interval, from, to });
  if (ticket !== generation || c.isDestroyed) return;        // a newer change or an unmount won
  s.setData(bars);
  c.resetScale();
}
watch([series, () => props.symbol, () => props.exchange, () => props.interval], load);
```

The ticket matters: without it a slow answer for the previous symbol lands after the new one and the chart shows the wrong prices under the new name (the e2e spec holds a request and answers it last). The widget loads through its own feed, and `setSymbol` / `setInterval` are no-ops for the current value, so its own top bar changes do not loop.

`v-model` with the widget: subscribe `widget.on('symbol' | 'interval' | 'theme', ...)` once the chart exists and emit `update:symbol`, `update:interval`, `update:theme`. `widget.destroy()` drops those subscriptions.

## Resize and theme

The chart's own `ResizeObserver` follows the container and repaints in the same frame. No window listener, no width/height props; the container needs a resolved height (a sized parent, a growing flex item, or `position: absolute; inset: 0`). A chart hidden by `v-show` or created hidden fits on its first measurable layout.

Theme: `chart.setTheme(darkTheme | lightTheme | custom)` for a bare chart, `widget.setTheme('dark' | 'light' | custom)` for the widget (guard with `widget.theme() !== next` when the prop is bound with `v-model`).

## KeepAlive, v-if and Nuxt

| Case | Behaviour |
|---|---|
| `<KeepAlive>` deactivation | not an unmount: the element leaves the document, the chart sees 0x0, and on return it relays out with the same visible range. Watchers keep running while parked, so prop changes are already applied when it returns. A live subscription keeps streaming; stop it in `onDeactivated` if that is not wanted. |
| `v-if` false, or the `<KeepAlive>` itself removed | every cached instance unmounts and destroys its chart. The e2e spec checks the page's listeners, observed elements and interval timers against a ledger taken before any chart existed, no animation frames requested afterwards, and both containers empty. |
| Remount | a new chart in a new container; creating into a used container is also safe (`destroy()` leaves inline styles and ARIA only). |
| Nuxt / SSR | `onMounted` never runs on the server, so the composable is already client-only. Importing any tier on the server is safe (module evaluation touches no DOM, which `npm run skills:coverage` enforces by importing every tier in Node). Use `<ClientOnly>` or a `.client.vue` component to skip the server render, and give the container its height in CSS. |
| Options API | do not declare the chart in `data()`; create it in `mounted()` on `this`, or `markRaw` it. Destroy in `beforeUnmount()`. |

## Related

[react-integration](react-integration.md) · [widget](widget.md) · [host-integration](host-integration.md) · [replay-and-compare](replay-and-compare.md) · [core-api](core-api.md) · [pitfalls](pitfalls.md)
