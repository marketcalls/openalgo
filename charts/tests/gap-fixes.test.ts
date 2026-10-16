import { describe, it, expect } from 'vitest';
import { FakeDataFeed } from '../src/feed/fake-feed';
import { Chart } from '../src/core/chart';
import { DataLayer } from '../src/model/data-layer';
import { toBar } from '../src/model/bar';
import { drawTimeAxis } from '../src/render/axis';
import { TimeScale } from '../src/scale/time-scale';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

function recordingDoc(): Document {
  const make = (tag: string): Record<string, unknown> => {
    const el: Record<string, unknown> = {
      tagName: tag.toUpperCase(), style: {}, children: [],
      appendChild(c: unknown) { (el.children as unknown[]).push(c); return c; },
      remove() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
      addEventListener() {}, removeEventListener() {},
      setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
    };
    if (tag === 'canvas') {
      el.width = 0; el.height = 0;
      el.getContext = () => new RecordingContext() as unknown as CanvasRenderingContext2D;
    }
    return el;
  };
  return { createElement: (t: string) => make(t) } as unknown as Document;
}
function makeChart(opts: Record<string, unknown> = {}): Chart {
  const doc = recordingDoc();
  const container = doc.createElement('div') as unknown as Record<string, unknown>;
  container.clientWidth = 800; container.clientHeight = 600;
  return new Chart(container as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1, raf: { schedule: () => 0, cancel: () => {} }, ...opts,
  });
}
const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c, volume: 100 });

describe('DataLayer visible-range binary search (Gap 7)', () => {
  const b = (t: number, c: number): Bar => ({ time: t, open: c, high: c + 1, low: c - 1, close: c });
  it('returns exactly the bars in the logical window', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, Array.from({ length: 100 }, (_, i) => b(1000 + i * 60, i)));
    const win = dl.visibleBars(id, 10, 20);
    expect(win.map((x) => x.index)).toEqual([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
    expect(win[0].bar.close).toBe(10);
    expect(win[win.length - 1].bar.close).toBe(20);
  });
  it('lastIndexedBar returns the newest bar and null for an empty series', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, [b(1000, 1), b(1060, 2), b(1120, 3)]);
    const last = dl.lastIndexedBar(id);
    expect(last?.index).toBe(2);
    expect(last?.bar.close).toBe(3);
    expect(dl.lastIndexedBar(dl.createSeries())).toBeNull();
  });
  it('maps a partially-overlapping series to the right global indices', () => {
    const dl = new DataLayer();
    const a = dl.createSeries();
    const c = dl.createSeries();
    dl.setSeriesData(a, [b(100, 1), b(200, 2), b(300, 3)]);
    dl.setSeriesData(c, [b(200, 9)]); // only present at time 200 -> global index 1
    const win = dl.visibleBars(c, 0, 2);
    expect(win.map((x) => x.index)).toEqual([1]);
    expect(win[0].bar.close).toBe(9);
  });
});

describe('FakeDataFeed.subscribeBars streams (not a silent no-op)', () => {
  it('emits deterministic advancing bars on the injected scheduler and stops on unsubscribe', () => {
    let fire: (() => void) | null = null;
    let cleared = false;
    const scheduler = (cb: () => void): (() => void) => { fire = cb; return () => { cleared = true; fire = null; }; };
    const feed = new FakeDataFeed(60, scheduler);
    const bars: Bar[] = [];
    const off = feed.subscribeBars!({ symbol: 'X', exchange: 'NSE', interval: '1m', from: 1000 }, (b) => bars.push(b));
    fire!(); fire!(); fire!();
    expect(bars).toHaveLength(3);
    expect(bars[1].time - bars[0].time).toBe(60); // advances by the interval
    expect(bars.every((b) => b.high >= b.close && b.low <= b.close)).toBe(true);
    off();
    expect(cleared).toBe(true);
  });
});

describe('Custom time formatter (Gap 10)', () => {
  const b = (t: number, c: number): Bar => ({ time: t, open: c, high: c + 1, low: c - 1, close: c });
  it('drawTimeAxis routes axis labels through a custom formatter (UTC seconds)', () => {
    const dl = new DataLayer();
    const id = dl.createSeries();
    dl.setSeriesData(id, Array.from({ length: 20 }, (_, i) => b(1_700_000_000 + i * 60, i)));
    const ts = new TimeScale();
    ts.setWidth(400);
    ts.setBaseIndex(dl.baseIndex);
    ts.fitContent(dl.length);
    const seen: number[] = [];
    const rec = new RecordingContext();
    drawTimeAxis(rec as unknown as CanvasRenderingContext2D, ts, dl,
      { plotWidth: 400, plotHeight: 100 } as never, 1, undefined, (s) => { seen.push(s); return 'X'; });
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.every((s) => s >= 1_700_000_000)).toBe(true); // real bar times, not IST-mangled
  });
});

describe('SeriesDataItem normalization (Gap 4)', () => {
  it('toBar normalizes value points and whitespace', () => {
    expect(toBar({ time: 1, open: 1, high: 2, low: 0, close: 1.5 })).toMatchObject({ close: 1.5 });
    expect(toBar({ time: 2, value: 42 })).toMatchObject({ time: 2, open: 42, high: 42, low: 42, close: 42 });
    expect(Number.isNaN(toBar({ time: 3 }).close)).toBe(true);
  });
  it('a line series accepts { time, value } and { time } gap items', () => {
    const chart = makeChart();
    const s = chart.addSeries('line');
    s.setData([{ time: 100, value: 10 }, { time: 160 }, { time: 220, value: 12 }]);
    const bars = s.getData();
    expect(bars).toHaveLength(3);
    expect(bars[0].close).toBe(10);
    expect(Number.isNaN(bars[1].close)).toBe(true); // whitespace gap
    expect(bars[2].close).toBe(12);
  });
});

describe('ChartOptions.priceScale applies per pane', () => {
  it('seeds every pane price scale with the given options', () => {
    const chart = makeChart({ priceScale: { mode: 'logarithmic', inverted: true, minMove: 0.05 } });
    chart.addSeries('candlestick').setData([bar(1000, 90), bar(1060, 100)]);
    chart.addSeries('histogram', { paneIndex: 1 }).setData([{ time: 1000, open: 0, high: 5, low: 0, close: 5 }]);
    for (const pane of chart.panes()) {
      expect(pane.priceScale.options.mode).toBe('logarithmic');
      expect(pane.priceScale.options.inverted).toBe(true);
    }
    // Every field but the tick. `minMove` is the instrument's trading step, so
    // it lands on the pane that quotes the instrument and stops there: the
    // second pane here plots volume, which is not priced in paise. See
    // `Chart._scalePatchFor` and tests/indicator-pane-precision.test.ts.
    expect(chart.panes()[0].priceScale.options.minMove).toBe(0.05);
    expect(chart.panes()[1].priceScale.options.minMove).toBe(0);
  });
});
