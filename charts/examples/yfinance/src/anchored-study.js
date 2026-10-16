import { registerIndicator } from '/dist/openalgo-charts.mjs';

/**
 * A study whose anchor is one point on the chart: a bar time and a price that
 * belong together. The price input names its time (`timeKey`), so Pick point
 * on chart in the settings dialog sets both from one click, and `anchor: true`
 * puts a handle on the chart that drags both at once; Ctrl+Z takes a drag
 * back. The path grows from the anchor by a fixed percentage per bar.
 */
export function anchoredGrowthDescriptor() {
  return {
    id: 'anchored-growth-sample', name: 'Anchored growth sample', category: 'Examples',
    placement: 'onchart',
    inputs: [
      { key: 'from', type: 'timestamp', label: 'Anchor time', default: 0, min: 0, pick: true, group: 'Anchor' },
      { key: 'price', type: 'price', label: 'Anchor price', default: 0, min: 0, pick: true,
        timeKey: 'from', anchor: true, group: 'Anchor' },
      { key: 'rate', type: 'number', label: 'Growth per bar (%)', default: 0.1, min: -5, max: 5, step: 0.05 },
    ],
    plots: [{ key: 'path', title: 'Growth path', type: 'line', style: { color: '#d97706', lineWidth: 2 } }],
    calc(bars, settings) {
      const from = Number(settings.from), price = Number(settings.price), rate = Number(settings.rate) / 100;
      const start = bars.findIndex(bar => bar.time >= from);
      return { path: bars.map((_, i) => (start < 0 || i < start || !(price > 0) ? null : price * (1 + rate) ** (i - start))) };
    },
  };
}

/**
 * Where a new sample is anchored: the bar two thirds across the view, at its
 * close, so the handle is on screen to be grabbed. The descriptor's own
 * defaults cannot know the loaded history.
 */
export function anchoredGrowthSeed(chart) {
  const bars = chart.primaryBars();
  if (!bars.length) return {};
  const range = chart.getVisibleLogicalRange?.();
  const index = range ? Math.round(range.from + (range.to - range.from) * 2 / 3) : bars.length - 1;
  const bar = bars[Math.max(0, Math.min(bars.length - 1, index))];
  return { from: bar.time, price: bar.close };
}

export function initAnchoredStudy() {
  registerIndicator(anchoredGrowthDescriptor());
}
