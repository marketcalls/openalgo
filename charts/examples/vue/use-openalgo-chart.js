// A Vue 3 composable that owns one chart, or one widget, for the lifetime of
// the component that calls it. Copy it into a project as
// composables/useOpenAlgoChart.ts; the typed form is in the Vue 3 section of
// the website's framework guide (/docs/frameworks#vue-3).
import { onBeforeUnmount, onMounted, shallowRef } from 'vue';
import { createChart } from 'openalgo-charts';

/**
 * @param {import('vue').Ref<HTMLElement | null>} container
 *   Template ref of the element the chart fills. Vue never proxies a DOM
 *   element, so an ordinary `ref` is right here.
 * @param {() => { widget?: object, chart?: object, seriesType?: string }} options
 *   Read once, on mount. With `widget`, the widget tier is loaded and
 *   `createWidget` builds the whole terminal; otherwise `createChart` builds a
 *   bare chart with one series.
 */
export function useOpenAlgoChart(container, options = () => ({})) {
  // shallowRef, never ref: `.value` is then the chart itself. `ref()` would
  // hand back a deep proxy, and the library keys its replay, pick and
  // comparison registries on the chart's identity, runs its methods with
  // `this` bound to whatever the call went through, and would pay a proxy
  // trap on every field read. Only replacing the chart notifies a watcher.
  const chart = shallowRef(null);
  const widget = shallowRef(null);
  const series = shallowRef(null);
  let disposed = false;

  onMounted(async () => {
    const el = container.value;
    if (el === null) return;
    const opts = options();
    if (opts.widget) {
      // Loaded on first use, so a page that shows only bare charts never
      // downloads the widget tier.
      const { createWidget } = await import('openalgo-charts/widget');
      // The component can unmount while the tier loads; building a widget
      // into a container Vue has already thrown away would leak it.
      if (disposed) return;
      const w = createWidget(el, opts.widget);
      widget.value = w;
      chart.value = w.chart;
      series.value = w.series;
    } else {
      const c = createChart(el, opts.chart);
      chart.value = c;
      series.value = c.addSeries(opts.seriesType ?? 'candlestick');
    }
  });

  // Before unmount rather than after: the container is still in the document,
  // so the chart detaches its canvases, observers and listeners from a live
  // tree, and nothing it removes has been moved by Vue first.
  onBeforeUnmount(() => {
    disposed = true;
    // The widget owns its chart and destroys it along with its own chrome.
    if (widget.value !== null) widget.value.destroy();
    else chart.value?.destroy();
    widget.value = null;
    chart.value = null;
    series.value = null;
  });

  return { chart, widget, series };
}
