// <OpenAlgoChart>: a chart whose instrument, interval and theme are props.
// Written with a template string so it runs from the browser build of Vue
// with no compile step; in a project it is a single-file component, shown in
// the Vue 3 section of the website's framework guide (/docs/frameworks#vue-3).
import { defineComponent, ref, watch } from 'vue';
import { darkTheme, lightTheme, intervalToSeconds } from 'openalgo-charts';
import { useOpenAlgoChart } from './use-openalgo-chart.js';

export const OpenAlgoChart = defineComponent({
  name: 'OpenAlgoChart',
  props: {
    symbol: { type: String, required: true },
    exchange: { type: String, default: 'NSE' },
    interval: { type: String, default: '5m' },
    theme: { type: String, default: 'dark', validator: value => value === 'dark' || value === 'light' },
    /** A DataFeed. Keep it out of deep reactive state, or pass it through markRaw. */
    feed: { type: Object, required: true },
    /** Host the widget (toolbar, rail, dialogs). Read on mount; change it with a new `key`. */
    widget: { type: Boolean, default: false },
    /** Bars asked of the feed per load. */
    lookback: { type: Number, default: 300 },
    /** More chart (or widget) options, read on mount like `widget`. */
    options: { type: Object, default: () => ({}) },
  },
  emits: ['ready', 'loaded', 'update:symbol', 'update:interval', 'update:theme'],
  setup(props, { emit, expose }) {
    const container = ref(null);
    const { chart, widget, series } = useOpenAlgoChart(container, () => props.widget
      ? {
          widget: {
            persist: false, ...props.options,
            feed: props.feed, symbol: props.symbol, exchange: props.exchange, interval: props.interval,
            theme: props.theme, lookbackBars: props.lookback,
          },
        }
      : { chart: { ...props.options, theme: props.theme === 'light' ? lightTheme : darkTheme } });

    // The chart, once, as soon as it exists. The widget's own controls change
    // the symbol, interval and theme too; reporting them as update events is
    // what lets a parent bind all three with v-model.
    watch(chart, (c) => {
      if (c === null) return;
      const w = widget.value;
      if (w !== null) {
        // widget.destroy() drops these subscriptions; nothing to undo here.
        w.on('symbol', ({ symbol }) => emit('update:symbol', symbol));
        w.on('interval', ({ interval }) => emit('update:interval', interval));
        w.on('theme', ({ theme }) => emit('update:theme', theme));
        w.on('data', payload => emit('loaded', payload));
      }
      emit('ready', { chart: c, widget: w, series: series.value });
    });

    // Props to data: the same chart and series take new bars. A new chart per
    // prop change would drop the viewport, the studies and every drawing.
    let generation = 0;
    async function load() {
      const c = chart.value, s = series.value;
      if (c === null || s === null) return;
      const w = widget.value;
      if (w !== null) {
        // The widget loads through its feed; these are no-ops when the
        // change came from its own controls.
        w.setSymbol(props.symbol, props.exchange);
        w.setInterval(props.interval);
        return;
      }
      const ticket = ++generation;
      const { symbol, exchange, interval } = props;
      const to = Math.floor(Date.now() / 1000);
      const from = to - props.lookback * intervalToSeconds(interval);
      // The old instrument's bars go before the context moves, so nothing
      // computes the new symbol's studies from the previous symbol's prices.
      s.setData([]);
      c.setDataContext({ symbol, exchange, interval });
      try {
        const bars = await props.feed.getBars({ symbol, exchange, interval, from, to });
        // A newer prop change, or an unmount, won while this was in flight.
        if (ticket !== generation || c.isDestroyed) return;
        s.setData(bars);
        c.resetScale();
        emit('loaded', { symbol, interval, bars: bars.length });
      } catch (error) {
        if (ticket !== generation || c.isDestroyed) return;
        emit('loaded', { symbol, interval, bars: 0, error: String(error?.message ?? error) });
      }
    }
    watch([series, () => props.symbol, () => props.exchange, () => props.interval], load);

    watch(() => props.theme, (theme) => {
      const w = widget.value;
      // A change the widget's own theme button made is already applied.
      if (w !== null) { if (w.theme() !== theme) w.setTheme(theme); }
      else chart.value?.setTheme(theme === 'light' ? lightTheme : darkTheme);
    });

    // A parent holding a template ref on this component reads these. Exposed
    // refs arrive unwrapped, and a shallowRef unwraps to the chart itself.
    expose({ chart, widget, series });
    return { container };
  },
  // The chart fills this element. Its size comes from CSS; the chart's own
  // ResizeObserver follows it, so there is no resize handler to write.
  template: '<div ref="container" class="oac-vue-chart"></div>',
});
