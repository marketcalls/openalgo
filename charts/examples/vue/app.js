// The demo app around <OpenAlgoChart>: shared symbol, interval and theme
// state, a bare chart and a widget kept alive side by side, and a switch that
// unmounts both. The bars are synthetic and need no network.
import { createApp, defineComponent, markRaw, reactive, watchEffect } from 'vue';
import { intervalToSeconds } from 'openalgo-charts';
// Registers the built-in studies the widget's indicator picker lists. A page
// that shows only bare charts can leave this out.
import 'openalgo-charts/indicators';
import { OpenAlgoChart } from './openalgo-chart.js';

const SYMBOLS = { NIFTY: 24100, BANKNIFTY: 51800, RELIANCE: 2930 };
const INTERVALS = ['1m', '5m', '15m', '1h', '1d', '1w'];
// Read once, on mount. The widget's interval pills offer the same list as the page.
const CHART_OPTIONS = { navigation: { defaultVisibleBars: 150 } };
const WIDGET_OPTIONS = { intervals: INTERVALS, navigation: { defaultVisibleBars: 150 } };

/** A number in [0, 1) that depends only on its arguments. */
function noise(seed, i) {
  let h = Math.imul(seed ^ Math.imul(i, 0x9e3779b1), 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/**
 * A synthetic DataFeed. A bar's prices depend only on the symbol, the interval
 * and the bar's own slot, so any window the chart or the widget asks for is
 * the same history, and there is never a bar after the current time.
 */
function syntheticFeed({ latencyMs = 15 } = {}) {
  const close = (base, seed, i) => base * (1 + 0.03 * Math.sin(i / 41 + seed) + 0.012 * Math.sin(i / 9.7 + seed * 2)
    + 0.006 * (noise(seed, i) - 0.5));
  return {
    async getBars({ symbol, interval, from, to, countBack }) {
      await new Promise(resolve => setTimeout(resolve, latencyMs));
      const base = SYMBOLS[symbol] ?? 1000;
      const seed = [...symbol].reduce((a, ch) => a * 31 + ch.charCodeAt(0), 7) % 1000;
      const sec = intervalToSeconds(interval);
      const last = Math.floor(Math.min(to ?? Infinity, Date.now() / 1000) / sec);
      const first = from === undefined ? last - (countBack ?? 300) + 1 : Math.ceil(from / sec);
      const bars = [];
      for (let i = Math.max(first, last - 5000); i <= last; i++) {
        const open = close(base, seed, i - 1), c = close(base, seed, i);
        const reach = base * 0.002;
        bars.push({
          time: i * sec, open, close: c,
          high: Math.max(open, c) + reach * noise(seed + 1, i),
          low: Math.min(open, c) - reach * noise(seed + 2, i),
          volume: Math.round(1000 + 9000 * noise(seed + 3, i)),
        });
      }
      return bars;
    },
  };
}

// The feed and every chart handle stay out of deep reactive state. markRaw
// keeps the feed itself even if it is later stored in reactive state, where
// its methods would otherwise run through a proxy. The instance list is a
// plain array, never reactive, for the same reason.
const feed = markRaw(syntheticFeed());
const instances = [];
const query = new URLSearchParams(location.search);

const state = reactive({
  symbol: 'NIFTY',
  interval: '5m',
  theme: 'dark',
  view: 'chart',
  // ?mounted=0 opens with nothing mounted, so a test can take its baseline
  // before the first chart exists.
  mounted: query.get('mounted') !== '0',
  created: 0,
  destroyed: 0,
  status: 'Loading',
});

const App = defineComponent({
  components: { OpenAlgoChart },
  setup() {
    const track = kind => ({ chart, widget }) => {
      instances.push({ kind, chart, widget });
      state.created++;
      chart.on('destroy', () => { state.destroyed++; });
    };
    const onLoaded = ({ symbol, interval, bars, error }) => {
      state.status = error ? `${symbol} ${interval}: ${error}` : `${symbol} ${interval}, ${bars} bars`;
    };
    // The page chrome follows the chart theme.
    watchEffect(() => { document.documentElement.dataset.theme = state.theme; });
    return {
      state, feed, symbols: Object.keys(SYMBOLS), intervals: INTERVALS, chartOptions: CHART_OPTIONS, widgetOptions: WIDGET_OPTIONS,
      onChartReady: track('chart'), onWidgetReady: track('widget'), onLoaded,
    };
  },
  template: `
    <header aria-label="Chart controls">
      <strong>Vue 3</strong>
      <label>Symbol
        <select v-model="state.symbol" data-control="symbol">
          <option v-for="s in symbols" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label>Interval
        <select v-model="state.interval" data-control="interval">
          <option v-for="i in intervals" :key="i" :value="i">{{ i }}</option>
        </select>
      </label>
      <button type="button" data-control="theme" @click="state.theme = state.theme === 'dark' ? 'light' : 'dark'">
        {{ state.theme === 'dark' ? 'Light theme' : 'Dark theme' }}
      </button>
      <div class="seg" role="tablist" aria-label="View">
        <button type="button" role="tab" data-control="view-chart" :aria-selected="state.view === 'chart'" @click="state.view = 'chart'">Chart</button>
        <button type="button" role="tab" data-control="view-widget" :aria-selected="state.view === 'widget'" @click="state.view = 'widget'">Widget</button>
      </div>
      <label class="check"><input type="checkbox" v-model="state.mounted" data-control="mounted"> Mounted</label>
    </header>
    <main class="stage" data-stage>
      <KeepAlive v-if="state.mounted">
        <OpenAlgoChart v-if="state.view === 'chart'" key="chart" data-view="chart"
          :symbol="state.symbol" :interval="state.interval" :theme="state.theme" :feed="feed" :options="chartOptions"
          @ready="onChartReady" @loaded="onLoaded" />
        <OpenAlgoChart v-else key="widget" data-view="widget" widget
          v-model:symbol="state.symbol" v-model:interval="state.interval" v-model:theme="state.theme" :feed="feed" :options="widgetOptions"
          @ready="onWidgetReady" @loaded="onLoaded" />
      </KeepAlive>
      <p v-else class="empty">Unmounted. Every chart has been destroyed.</p>
    </main>
    <footer role="status" data-status>
      <span>{{ state.status }}</span>
      <span>Charts created {{ state.created }}, destroyed {{ state.destroyed }}, live {{ state.created - state.destroyed }}</span>
    </footer>
  `,
});

createApp(App).mount('#app');

// For the browser console and tests/e2e/vue-integration.spec.ts: the reactive
// app state, the feed, and every chart and widget created so far, in creation
// order.
window.openalgoVueExample = { state, feed, instances };
