/**
 * The magnet everywhere: a handle or a whole shape in hand snaps the way a
 * placement does, a study pane snaps to the values its plots show, and Ctrl
 * (Cmd) held is a strong magnet for as long as it is held, whatever the mode.
 *
 * Measured charts throughout (`applySize` plus a synchronous raf): the weak
 * magnet and a study pane are judged in pixels.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController, DrawingLayer } from '../src/draw/index';
import { barAt, magnetPoint } from '../src/draw/snap';
import type { Bar } from '../src/model/bar';
import type { DrawingPoint } from '../src/draw/types';

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const T0 = 1700000000;
const STEP = 60;

/** A walk with wide, distinct bars, so every O/H/L/C is its own place on screen. */
const BARS: Bar[] = (() => {
  let price = 100;
  let seed = 7;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  return Array.from({ length: 120 }, (_, i) => {
    const open = price;
    const close = open + (next() - 0.5) * 6;
    const high = Math.max(open, close) + 1 + next() * 3;
    const low = Math.min(open, close) - 1 - next() * 3;
    price = close;
    return { time: T0 + i * STEP, open, high, low, close, volume: 100 + Math.round(next() * 900) };
  });
})();

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div') as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(BARS);
  charts.push(chart);
  return chart;
}

const bar = (i: number) => {
  const { time, open, high, low, close } = BARS[i];
  return { time, open, high, low, close };
};

/** A price `dy` media px below `price` on a pane. */
const below = (chart: Chart, price: number, dy: number, pane = 0): number =>
  chart.coordinateToPrice((chart.priceToCoordinate(price, pane) as number) + dy, pane) as number;

const dragHandle = (chart: Chart, id: string, handle: number, to: DrawingPoint, extra: Record<string, unknown> = {}, pane = 0): void => {
  chart.emit('drag', { id: `draw:${id}#${handle}`, ...to, paneIndex: pane, ...extra });
  chart.emit('drag:end', {});
};

const trendLine = (draw: DrawingController, pane = 0, a = 10, b = 20) => draw.add({
  tool: 'trend-line', paneIndex: pane, style: {},
  points: [{ time: BARS[a].time, price: BARS[a].close }, { time: BARS[b].time, price: BARS[b].close }],
});

describe('the magnet pulls a handle in hand', () => {
  it('strong: the handle lands on the nearest O/H/L/C of the bar under it, at the bar time', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    const d = trendLine(draw);
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 17, price: BARS[30].high + 0.4 });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time, price: BARS[30].high });
    expect(draw.get(d.id)!.points[0]).toEqual({ time: BARS[10].time, price: BARS[10].close });
  });

  it('weak: pulls within eight pixels and leaves a handle further away where it was put', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'weak' });
    const d = trendLine(draw);
    const near = below(chart, BARS[30].low, 5);
    dragHandle(chart, d.id, 1, { time: BARS[30].time, price: near });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time, price: BARS[30].low });
    const far = below(chart, BARS[30].low, 40);
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 5, price: far });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time + 5, price: far });
  });

  it('off: a handle follows the pointer exactly, as it always has', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = trendLine(draw);
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 17, price: BARS[30].high + 0.4 });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time + 17, price: BARS[30].high + 0.4 });
  });

  it('the angle lock still wins over the magnet on a handle', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    const d = trendLine(draw);
    const target = { time: BARS[40].time, price: BARS[10].close + 0.05 };
    dragHandle(chart, d.id, 1, target, { modifiers: { shift: true } });
    const p = draw.get(d.id)!.points[1];
    expect(chart.priceToCoordinate(p.price, 0)).toBeCloseTo(chart.priceToCoordinate(BARS[10].close, 0) as number, 6);
  });

  it('never pulls a drawing pinned to the viewport', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    const d = draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [], space: 'viewport',
      viewportPoints: [{ x: 0.2, y: 0.2 }, { x: 0.4, y: 0.4 }] });
    const before = draw.get(d.id)!.viewportPoints!.map((p) => ({ ...p }));
    dragHandle(chart, d.id, 1, { time: BARS[60].time + 11, price: BARS[60].high + 0.2 },
      { point: { x: chart.timeToCoordinate(BARS[60].time + 11), y: chart.priceToCoordinate(BARS[60].high + 0.2, 0) } });
    const after = draw.get(d.id)!.viewportPoints!;
    const rect = chart.plotRect(0)!;
    expect(after[0]).toEqual(before[0]);
    expect(after[1].x * rect.width).toBeCloseTo(chart.timeToCoordinate(BARS[60].time + 11) - rect.left, 6);
  });
});

describe('the magnet pulls a whole shape in hand', () => {
  it('strong: the anchor nearest the grab lands on a bar value and the shape moves rigidly', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { magnet: 'strong' });
    const d = trendLine(draw);
    const [a0, a1] = draw.get(d.id)!.points.map((p) => ({ ...p }));
    // Grabbed a little along the line from anchor 0, moved to near bar 40's low.
    const from = { time: a0.time + 30, price: a0.price + 0.1 };
    const dt = BARS[40].time + 9 - a0.time;
    const dp = BARS[40].low + 0.3 - a0.price;
    chart.emit('drag', { id: `draw:${d.id}`, time: from.time + dt, price: from.price + dp, paneIndex: 0,
      fromTime: from.time, fromPrice: from.price });
    chart.emit('drag:end', {});
    const [b0, b1] = draw.get(d.id)!.points;
    expect(b0).toEqual({ time: BARS[40].time, price: BARS[40].low });
    expect(b1.time - a1.time).toBeCloseTo(b0.time - a0.time, 9);
    expect(b1.price - a1.price).toBeCloseTo(b0.price - a0.price, 9);
  });

  it('off: a shape moves by the pointer delta exactly, as it always has', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = trendLine(draw);
    const [a0] = draw.get(d.id)!.points.map((p) => ({ ...p }));
    chart.emit('drag', { id: `draw:${d.id}`, time: a0.time + 30 + 609, price: a0.price + 3.3, paneIndex: 0,
      fromTime: a0.time + 30, fromPrice: a0.price });
    chart.emit('drag:end', {});
    expect(draw.get(d.id)!.points[0]).toEqual({ time: a0.time + 609, price: a0.price + 3.3 });
  });
});

describe('Ctrl or Cmd held is a strong magnet for as long as it is held', () => {
  const hover = (chart: Chart, i: number, price: number, extra: Record<string, unknown> = {}): void =>
    chart.emit('crosshair:move', { time: BARS[i].time, price, paneIndex: 0, bar: bar(i), ...extra });

  it('snaps a placement click with the magnet off', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('horizontal-line');
    hover(chart, 50, BARS[50].high + 2, { modifiers: { ctrl: true } });
    chart.emit('click', { id: null, time: BARS[50].time + 13, price: BARS[50].high + 2, paneIndex: 0,
      point: { x: 0, y: 0 }, modifiers: { ctrl: true } });
    expect(draw.drawings()[0].points[0]).toEqual({ time: BARS[50].time, price: BARS[50].high });
  });

  it('snaps a handle drag with Cmd, and nothing snaps once it is let go', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const d = trendLine(draw);
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 17, price: BARS[30].high + 0.4 }, { modifiers: { meta: true } });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time, price: BARS[30].high });
    dragHandle(chart, d.id, 1, { time: BARS[31].time + 17, price: BARS[31].high + 0.4 }, { modifiers: {} });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[31].time + 17, price: BARS[31].high + 0.4 });
  });

  it('shows the magnet ring while held, even with the magnet off', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    draw.setTool('trend-line');
    const ring = (): DrawingPoint | null => {
      const layer = chart.panes()[0].primitives().find((p) => p instanceof DrawingLayer && p.zOrder() === 'top') as DrawingLayer | undefined;
      return layer?.snapPoint() ?? null;
    };
    hover(chart, 50, BARS[50].low - 1);
    expect(ring()).toBeNull();
    hover(chart, 50, BARS[50].low - 1, { modifiers: { ctrl: true } });
    expect(ring()).toEqual({ time: BARS[50].time, price: BARS[50].low });
    hover(chart, 50, BARS[50].low - 1);
    expect(ring()).toBeNull();
  });

  it('does nothing when the host turns the gesture off', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart, { gestures: { snapModifier: false } });
    const d = trendLine(draw);
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 17, price: BARS[30].high + 0.4 }, { modifiers: { ctrl: true } });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time + 17, price: BARS[30].high + 0.4 });
    draw.setOptions({ gestures: { snapModifier: true } });
    dragHandle(chart, d.id, 1, { time: BARS[30].time + 17, price: BARS[30].high + 0.4 }, { modifiers: { ctrl: true } });
    expect(draw.get(d.id)!.points[1]).toEqual({ time: BARS[30].time, price: BARS[30].high });
  });
});

describe('a study pane snaps to the values its plots show', () => {
  const setup = (magnet: 'weak' | 'strong' = 'strong') => {
    const chart = makeChart();
    const rsi = chart.addIndicator('rsi');
    const pane = chart.panes().findIndex((p) => p.scales().includes(rsi.series('rsi')!.priceScale()));
    const draw = new DrawingController(chart, { magnet });
    const value = (i: number): number => rsi.values().rsi[i] as number;
    return { chart, rsi, pane, draw, value };
  };

  it('strong: a placement lands on the plotted value at the bar time', () => {
    const { chart, pane, draw, value } = setup();
    expect(pane).toBeGreaterThan(0);
    draw.setTool('horizontal-line');
    chart.emit('crosshair:move', { time: BARS[60].time, price: 50, paneIndex: pane, bar: bar(60) });
    chart.emit('click', { id: null, time: BARS[60].time + 21, price: 50, paneIndex: pane, point: { x: 0, y: 0 } });
    expect(Number.isFinite(value(60))).toBe(true);
    expect(draw.drawings()[0].points[0]).toEqual({ time: BARS[60].time, price: value(60) });
  });

  it('weak: pulls only within eight pixels of the plot', () => {
    const { chart, pane, draw, value } = setup('weak');
    const near = below(chart, value(70), 6, pane);
    const far = below(chart, value(70), 30, pane);
    draw.setOptions({ stayInDrawingMode: true });
    draw.setTool('horizontal-line');
    chart.emit('crosshair:move', { time: BARS[70].time, price: near, paneIndex: pane, bar: bar(70) });
    chart.emit('click', { id: null, time: BARS[70].time, price: near, paneIndex: pane, point: { x: 0, y: 0 } });
    chart.emit('crosshair:move', { time: BARS[70].time, price: far, paneIndex: pane, bar: bar(70) });
    chart.emit('click', { id: null, time: BARS[70].time, price: far, paneIndex: pane, point: { x: 0, y: 0 } });
    expect(draw.drawings()[0].points[0]).toEqual({ time: BARS[70].time, price: value(70) });
    expect(draw.drawings()[1].points[0]).toEqual({ time: BARS[70].time, price: far });
  });

  it('snaps a handle dragged on the study pane', () => {
    const { chart, pane, draw, value } = setup();
    const d = trendLine(draw, pane);
    // The anchors sit on candle closes, far off the RSI scale; only the handle moves.
    dragHandle(chart, d.id, 0, { time: BARS[80].time + 7, price: value(80) + 1.5 }, {}, pane);
    expect(draw.get(d.id)!.points[0]).toEqual({ time: BARS[80].time, price: value(80) });
  });

  it('ignores a hidden study, so an anchor never lands on something that is not drawn', () => {
    const { chart, rsi, pane, draw } = setup();
    rsi.setVisible(false);
    draw.setTool('horizontal-line');
    chart.emit('crosshair:move', { time: BARS[60].time, price: 50, paneIndex: pane, bar: bar(60) });
    chart.emit('click', { id: null, time: BARS[60].time, price: 50, paneIndex: pane, point: { x: 0, y: 0 } });
    expect(draw.drawings()[0].points[0].price).toBe(50);
  });

  it('keeps the candles off a study pane and the plots off the price pane', () => {
    const { chart, pane, value } = setup();
    const b = bar(60);
    expect(magnetPoint(chart, { time: b.time, price: b.high + 0.2 }, 0, 'strong', 0, b)).toEqual({ time: b.time, price: b.high });
    const onStudy = magnetPoint(chart, { time: b.time, price: 50 }, pane, 'strong', 0, b);
    expect(onStudy).toEqual({ time: b.time, price: value(60) });
  });
});

describe('barAt', () => {
  it('finds the price bar whose slot a time falls in, and nothing past the data', () => {
    const chart = makeChart();
    expect(barAt(chart, BARS[12].time + 25)).toEqual(bar(12));
    expect(barAt(chart, BARS[12].time + 35)).toEqual(bar(13));
    expect(barAt(chart, BARS[BARS.length - 1].time + 50 * STEP)).toBeNull();
  });
});
