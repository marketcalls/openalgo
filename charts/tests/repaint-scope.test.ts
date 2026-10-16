/**
 * How far a data write repaints (ARCHITECTURE.md §3.2).
 *
 * A live tick used to raise a chart-wide `Full`, and so did every plot a
 * study wrote, so one tick repainted every pane's base canvas, and one study
 * recompute did the same. These tests count `paintBase` and `paintTop` per
 * pane over exactly one frame, so a write that reaches a pane it has no
 * business in fails here, and so does one that misses a pane that has to
 * change: the price pane on a tick, a study's own pane and any pane its output
 * targets, every pane when the shared time scale moves, and the panes whose
 * axis chrome reads the wall clock (the corner clock on the pane that carries
 * the time axis, the bar countdown in each price tag), which read it only as
 * their pane paints.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { Pane } from '../src/core/pane';
import type { Bar } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import { registerIndicator, type IndicatorAttachContext } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const T0 = 1_700_000_000;
const STEP = 60;
const BARS: Bar[] = Array.from({ length: 200 }, (_, i) => ({
  time: T0 + i * STEP, open: 100 + (i % 7), high: 104 + (i % 7), low: 97 + (i % 7), close: 101 + (i % 7),
}));
const LAST = BARS[BARS.length - 1];

let sequence = 0;

/** What a probe study draws besides its own plot. */
interface ProbeOptions {
  /** A second plot, sent to the candles. */
  overlay?: boolean;
  /** A level at the last close, so a tick moves it. */
  level?: boolean;
  /** Bar colours that paint the last bar red while its close is on an odd tenth. */
  barColors?: boolean;
}

/** A study with one plot of its own, and whatever else `options` asks for. */
function probe(options: ProbeOptions = {}): { id: string; recompute: () => void } {
  let attachment: IndicatorAttachContext | undefined;
  const id = `repaint-scope-probe-${sequence++}`;
  registerIndicator({
    id, name: 'Probe', placement: 'pane', inputs: [],
    plots: [
      { key: 'v', type: 'line', title: 'Value' },
      ...(options.overlay ? [{ key: 'o', type: 'line' as const, title: 'On price', overlay: true }] : []),
    ],
    calc: input => ({ v: input.map(bar => bar.close - bar.open), o: input.map(bar => bar.close) }),
    ...(options.level ? { levels: ({ bars }: { bars: readonly Bar[] }) => [{ price: bars[bars.length - 1]?.close ?? 0 }] } : {}),
    ...(options.barColors ? {
      barColors: ({ bars }: { bars: readonly Bar[] }) => bars.map((bar, i) =>
        i === bars.length - 1 && Math.round(bar.close * 10) % 2 === 1 ? '#ff0000' : null),
    } : {}),
    attach: context => { attachment = context; },
  });
  return { id, recompute: () => attachment?.requestRecompute() };
}

const charts: Chart[] = [];
afterEach(() => {
  vi.restoreAllMocks();
  for (const chart of charts.splice(0)) chart.destroy();
});

/**
 * A measured chart with a deferred scheduler, so every frame is run by hand
 * and a count covers exactly one of them. Pane 0 holds the price series,
 * pane 1 a study computed from it, pane 2 an unrelated line series and the
 * time axis.
 */
function fixture(study: ProbeOptions = {}) {
  let now = 0;
  let id = 0;
  const queue = new Map<number, () => void>();
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, now: () => now,
    raf: { schedule: cb => { queue.set(++id, cb); return id; }, cancel: key => { queue.delete(key); } },
  });
  charts.push(chart);
  const frame = (): void => {
    now += 16;
    const due = [...queue.entries()];
    for (const [key, cb] of due) if (queue.delete(key)) cb();
  };
  const settle = (): void => { for (let i = 0; i < 50 && queue.size > 0; i++) frame(); };
  chart.applySize(800, 600);
  const price = chart.addSeries('candlestick');
  price.setData(BARS);
  const { id: studyId, recompute } = probe(study);
  chart.addIndicator(studyId);
  const other: SeriesApi = chart.addSeries('line', { paneIndex: 2 });
  other.setData(BARS.map(bar => ({ time: bar.time, value: bar.close * 2 })));
  settle();
  expect(chart.panes()).toHaveLength(3);
  return { chart, price, other, recompute, frame, settle, queue };
}

/** Base and overlay paints per pane while `act` runs. */
function paints(chart: Chart, act: () => void): { base: number[]; top: number[] } {
  const base = vi.spyOn(Pane.prototype, 'paintBase');
  const top = vi.spyOn(Pane.prototype, 'paintTop');
  act();
  const count = (calls: unknown[]): number[] => chart.panes().map(pane => calls.filter(c => c === pane).length);
  const out = { base: count(base.mock.contexts), top: count(top.mock.contexts) };
  base.mockRestore();
  top.mockRestore();
  return out;
}

describe('a live tick', () => {
  it('repaints the price pane and the study computed from it, once per frame, and no unrelated pane', () => {
    const f = fixture();
    const counts = paints(f.chart, () => {
      // A burst between two frames, the usual shape of a busy feed.
      for (let i = 1; i <= 3; i++) f.price.update({ ...LAST, close: LAST.close + i / 10 });
      f.frame();
    });
    expect(counts.base).toEqual([1, 1, 0]);
    // The legends and the crosshair live on the overlay: the study's legend
    // shows the new value, so its pane's overlay repaints with its base.
    expect(counts.top).toEqual([1, 1, 0]);
    expect(f.queue.size).toBe(0);
  });

  it('re-measures the price scale it repaints', () => {
    const f = fixture();
    const high = LAST.high + 500;
    f.price.update({ ...LAST, high, close: high - 1 });
    f.settle();
    expect(f.chart.panes()[0].priceScale.priceRange().max).toBeGreaterThanOrEqual(high);
  });

  it('that moves a study level repaints the study pane, not every pane', () => {
    const f = fixture({ level: true });
    const close = LAST.close + 0.1;
    const counts = paints(f.chart, () => {
      f.price.update({ ...LAST, close });
      f.frame();
    });
    const levels = f.chart.panes()[1].primitives().map(p => (p as { options?: () => { price?: number } }).options?.().price);
    expect(levels).toContain(close);
    expect(counts.base).toEqual([1, 1, 0]);
  });

  it('that recolours the forming bar repaints the price pane, not every pane', () => {
    const f = fixture({ barColors: true });
    const color = (): string | undefined => { const data = f.price.getData(); return data[data.length - 1]?.color; };
    expect(color()).toBeUndefined();
    const counts = paints(f.chart, () => {
      f.price.update({ ...LAST, close: LAST.close + 0.1 });
      f.frame();
    });
    expect(color()).toBe('#ff0000');
    expect(counts.base).toEqual([1, 1, 0]);
  });

  it('with the corner clock on also repaints the bottom pane, whose clock reads the time as it paints', () => {
    const f = fixture();
    f.chart.setAxisChromeOptions({ sessionClock: true });
    f.settle();
    const tick = paints(f.chart, () => {
      f.price.update({ ...LAST, close: LAST.close + 0.1 });
      f.frame();
    });
    expect(tick.base).toEqual([1, 1, 1]);
    const recompute = paints(f.chart, () => { f.recompute(); f.settle(); });
    expect(recompute.base).toEqual([0, 1, 1]);
  });

  it('with the bar countdown on also repaints every pane whose price tag carries one', () => {
    const f = fixture();
    // A histogram is not a price series, so its pane has no last-price tag
    // and no countdown, and nothing here writes to it.
    f.chart.addSeries('histogram', { paneIndex: 3 }).setData(BARS.map(bar => ({ time: bar.time, value: bar.close })));
    f.chart.setAxisChromeOptions({ barCountdown: true });
    f.settle();
    const counts = paints(f.chart, () => {
      f.other.update({ time: LAST.time, value: LAST.close * 3 });
      f.frame();
    });
    // The host line's own pane for the write, and the price and study panes
    // for the countdown their tags carry.
    expect(counts.base).toEqual([1, 1, 1, 0]);
  });

  it('on a series of another pane repaints that pane alone', () => {
    const f = fixture();
    const counts = paints(f.chart, () => {
      f.other.update({ time: LAST.time, value: LAST.close * 3 });
      f.frame();
    });
    expect(counts.base).toEqual([0, 0, 1]);
  });

  it('that appends a bar at the right edge moves the shared time scale, so every pane and the time axis repaint', () => {
    const f = fixture();
    expect(f.chart.timeScale.rightOffset).toBeGreaterThanOrEqual(0);
    const before = f.chart.getVisibleLogicalRange();
    const counts = paints(f.chart, () => {
      f.price.update({ ...LAST, time: LAST.time + STEP });
      f.frame();
    });
    expect(f.chart.getVisibleLogicalRange().to).toBeGreaterThan(before.to);
    // Pane 2 is the bottom pane: its base canvas carries the time axis.
    expect(counts.base).toEqual([1, 1, 1]);
  });
});

describe('a study recompute', () => {
  it('repaints the study\'s own pane and nothing else', () => {
    const f = fixture();
    const counts = paints(f.chart, () => { f.recompute(); f.settle(); });
    expect(counts.base).toEqual([0, 1, 0]);
  });

  it('also repaints a pane its output targets', () => {
    const f = fixture({ overlay: true });
    expect(f.chart.panes()[0].series()).toHaveLength(2);
    const counts = paints(f.chart, () => { f.recompute(); f.settle(); });
    expect(counts.base).toEqual([1, 1, 0]);
  });

  it('re-measures a pane where its output is a primitive alone', () => {
    // Every plot goes to the candles, so the study's own pane holds a
    // primitive whose extent the calculation moves, and no series.
    const f = fixture();
    let extent = 0;
    let attachment: IndicatorAttachContext | undefined;
    const id = `repaint-scope-probe-${sequence++}`;
    registerIndicator({
      id, name: 'Band', placement: 'pane', inputs: [],
      plots: [{ key: 'o', type: 'line', title: 'On price', overlay: true }],
      calc: input => { extent += 1000; return { o: input.map(bar => bar.close) }; },
      attach: context => {
        attachment = context;
        context.addPrimitive?.({ zOrder: () => 'normal', draw: () => {}, autoscaleInfo: () => ({ min: 0, max: extent }) });
      },
    });
    f.chart.addIndicator(id);
    f.settle();
    const pane = f.chart.panes()[3];
    expect(pane.series()).toHaveLength(0);
    const counts = paints(f.chart, () => { attachment?.requestRecompute(); f.settle(); });
    expect(counts.base).toEqual([1, 0, 0, 1]);
    expect(pane.priceScale.priceRange().max).toBeGreaterThanOrEqual(extent);
  });
});

describe('a study that opens a pane', () => {
  it('repaints every pane, because making room resizes their canvases', () => {
    const f = fixture();
    const { id } = probe();
    const counts = paints(f.chart, () => { f.chart.addIndicator(id); f.settle(); });
    expect(f.chart.panes()).toHaveLength(4);
    expect(counts.base.every(n => n >= 1)).toBe(true);
  });
});
