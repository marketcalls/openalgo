// A chart host for the real DrawingController: a working event bus and a
// fixed pixel mapping (8px per bar, 2px per price unit), so the bar's
// positioning and the controller's own offsets (duplicate, nudge) can be
// checked against numbers worked out by hand. No canvas, no panes.
import { DrawingController } from '/dist/openalgo-charts.draw.mjs';

export const T0 = 1700000000;
export const BAR_SEC = 60;
export const PX_PER_BAR = 8;
export const timeToX = (t) => ((t - T0) / BAR_SEC) * PX_PER_BAR;
export const priceToY = (p) => 500 - p * 2;

export function fakeChart() {
  const handlers = new Map();
  return {
    on(event, fn) {
      if (!handlers.has(event)) handlers.set(event, []);
      handlers.get(event).push(fn);
      return () => handlers.set(event, (handlers.get(event) || []).filter((h) => h !== fn));
    },
    emit(event, payload) { for (const h of (handlers.get(event) || []).slice()) h(payload); },
    listenerCount: (event) => (handlers.get(event) || []).length,
    addPrimitive() {},
    removePrimitive() {},
    dataLayer: {
      baseIndex: 0,
      length: 200,
      indexToTime: (i) => T0 + i * BAR_SEC,
      indexToTimeFloat: (i) => T0 + i * BAR_SEC,
      timeToIndexFloat: (t) => (t - T0) / BAR_SEC,
    },
    getVisibleLogicalRange: () => ({ from: 0, to: 120 }),
    drawingState: () => null,
    setDrawingState() {},
    setPlacementMode() {},
    timeToCoordinate: timeToX,
    coordinateToTime: (x) => T0 + (x / PX_PER_BAR) * BAR_SEC,
    priceToCoordinate: (p) => priceToY(p),
    coordinateToPrice: (y) => (500 - y) / 2,
    panes: () => [{}],
  };
}

/** The demo's `app` with a live controller on the fake chart. */
export function makeApp() {
  const chart = fakeChart();
  const draw = new DrawingController(chart);
  const app = { chart, draw, draw2: null, chart2: null, focusPane: 1, props: null, shortcuts: {} };
  return { app, chart, draw };
}

export const line = (draw, extra = {}) => draw.add({
  tool: 'trend-line', paneIndex: 0, style: {},
  points: [{ time: T0 + 600, price: 100 }, { time: T0 + 1200, price: 120 }],
  ...extra,
});
export const rect = (draw, extra = {}) => draw.add({
  tool: 'rectangle', paneIndex: 0, style: {},
  points: [{ time: T0 + 600, price: 100 }, { time: T0 + 1800, price: 140 }],
  ...extra,
});
export const text = (draw, extra = {}) => draw.add({
  tool: 'text', paneIndex: 0, style: {},
  points: [{ time: T0 + 600, price: 100 }],
  text: { value: 'Hello' },
  ...extra,
});
export const fib = (draw, extra = {}) => draw.add({
  tool: 'fib-retracement', paneIndex: 0, style: {},
  points: [{ time: T0 + 600, price: 100 }, { time: T0 + 1800, price: 160 }],
  ...extra,
});

/** Tell the controller the pointer is over `id`, the way the chart's hit-test does. */
export const hover = (chart, id) => chart.emit('hover', { id: id ? 'draw:' + id : null });
