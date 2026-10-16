/**
 * The status line under each widget (and so the footer of every grid cell)
 * reads the latest bar while the pointer is away from the chart. It used to
 * read that bar once, the first time it had none, and then hold it: a cell
 * the pointer was not over kept the previous instrument's O, H, L, C, change,
 * volume and time after a symbol change, an interval change, a linked change
 * or a live tick, until someone hovered the chart and left it again. Nothing
 * here moves a pointer unless the case is about the pointer.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar, BarsRequest, DataFeed } from '../src/index';
import { createChartGrid, createWidget, mountStatusline, type ChartGrid, type Widget, type WidgetOptions } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const DAY = 86400;
const T0 = 1700000000;
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

/** A short seeded random walk, so each instrument has its own last close. */
function walk(count: number, start: number, seed: number, t0 = T0, step = DAY): Bar[] {
  let state = seed >>> 0 || 1;
  const random = (): number => { state = (state * 1664525 + 1013904223) >>> 0; return state / 4294967296; };
  const out: Bar[] = [];
  let close = start;
  for (let i = 0; i < count; i++) {
    const open = close;
    close = Math.round(open * (1 + (random() - 0.5) * 0.02) * 100) / 100;
    const high = Math.round((Math.max(open, close) + random() * 0.8) * 100) / 100;
    const low = Math.round((Math.min(open, close) - random() * 0.8) * 100) / 100;
    out.push({ time: t0 + i * step, open, high, low, close, volume: 1000 + Math.round(random() * 5000) });
  }
  return out;
}

interface Pending { request: BarsRequest; resolve(bars: Bar[]): void }
function pendingFeed(live?: { push: ((bar: Bar) => void) | null }): { feed: DataFeed; requests: Pending[] } {
  const requests: Pending[] = [];
  const feed: DataFeed = {
    getBars: request => new Promise<Bar[]>(resolve => { requests.push({ request, resolve }); }),
    ...(live ? { subscribeBars: (_req: BarsRequest, onBar: (bar: Bar) => void) => { live.push = onBar; return () => { live.push = null; }; } } : {}),
  };
  return { feed, requests };
}

const widgets: Widget[] = [];
const grids: ChartGrid[] = [];
afterEach(() => {
  for (const w of widgets.splice(0)) if (!w.isDestroyed) w.destroy();
  for (const g of grids.splice(0)) if (!g.isDestroyed) g.destroy();
});

function make(opts: WidgetOptions): { w: Widget; root: FakeElement } {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    locale: 'en-US',
    persist: false,
    ...opts,
  });
  w.chart.applySize(800, 600);
  widgets.push(w);
  return { w, root: w.root as unknown as FakeElement };
}

const price = (v: number): string => new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
const read = (root: FakeElement, field: 'o' | 'h' | 'l' | 'c'): string | null => {
  const el = root.querySelector(`.oac-statusline__${field}`) as FakeElement;
  return el.hidden ? null : (root.querySelector(`.oac-statusline__${field} b`)?.textContent ?? null);
};
const last = (bars: Bar[]): Bar => bars[bars.length - 1];

describe('status line follows the latest bar while the pointer is away', () => {
  it('shows the new instrument once its bars land, with no pointer event', async () => {
    const { feed, requests } = pendingFeed();
    const { w, root } = make({ feed, symbol: 'AAA' });
    const a = walk(40, 100, 7);
    requests.shift()!.resolve(a);
    await flush();
    expect(read(root, 'c')).toBe(price(last(a).close));

    w.setSymbol('BBB');
    // The old instrument's readings vanish with its name, rather than sitting
    // under the new title until the new bars arrive.
    expect(read(root, 'c')).toBeNull();
    expect(root.querySelector('.oac-statusline__time')?.textContent).toBe('');
    const b = walk(40, 2500, 11);
    expect(last(b).close).not.toBe(last(a).close);
    const next = requests.shift()!;
    expect(next.request.symbol).toBe('BBB');
    next.resolve(b);
    await flush();
    expect(read(root, 'o')).toBe(price(last(b).open));
    expect(read(root, 'h')).toBe(price(last(b).high));
    expect(read(root, 'l')).toBe(price(last(b).low));
    expect(read(root, 'c')).toBe(price(last(b).close));
  });

  it('shows the new interval once its bars land', async () => {
    const { feed, requests } = pendingFeed();
    const { w, root } = make({ feed, symbol: 'AAA', interval: '1d' });
    const daily = walk(40, 100, 3);
    requests.shift()!.resolve(daily);
    await flush();
    expect(read(root, 'c')).toBe(price(last(daily).close));
    w.setInterval('1h');
    expect(read(root, 'c')).toBeNull();
    const hourly = walk(60, 104, 5, T0, 3600);
    requests.shift()!.resolve(hourly);
    await flush();
    expect(read(root, 'c')).toBe(price(last(hourly).close));
  });

  it('follows a live tick on the forming bar and a newly opened bar', async () => {
    const live: { push: ((bar: Bar) => void) | null } = { push: null };
    const { feed, requests } = pendingFeed(live);
    const { root } = make({ feed, symbol: 'AAA' });
    const a = walk(30, 100, 9);
    requests.shift()!.resolve(a);
    await flush();
    expect(live.push).not.toBeNull();
    const forming = { ...last(a), high: last(a).high + 3, close: last(a).close + 2.5 };
    live.push!(forming);
    await flush();
    expect(read(root, 'c')).toBe(price(forming.close));
    expect(read(root, 'h')).toBe(price(forming.high));
    const opened = { time: last(a).time + DAY, open: forming.close, high: forming.close + 1, low: forming.close - 1, close: forming.close - 0.75 };
    live.push!(opened);
    await flush();
    expect(read(root, 'c')).toBe(price(opened.close));
  });

  it('keeps a hovered bar through live ticks and returns to the latest bar when the pointer leaves', async () => {
    const live: { push: ((bar: Bar) => void) | null } = { push: null };
    const { feed, requests } = pendingFeed(live);
    const { w, root } = make({ feed, symbol: 'AAA' });
    const a = walk(30, 100, 13);
    requests.shift()!.resolve(a);
    await flush();
    const hovered = a[10];
    w.chart.emit('crosshair:move', { time: hovered.time, index: 10, price: hovered.close, bar: hovered, point: { x: 10, y: 10 }, paneIndex: 0 });
    expect(read(root, 'c')).toBe(price(hovered.close));
    const forming = { ...last(a), close: last(a).close + 4, high: last(a).high + 4 };
    live.push!(forming);
    await flush();
    expect(read(root, 'c')).toBe(price(hovered.close));
    w.chart.emit('crosshair:move', { time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
    expect(read(root, 'c')).toBe(price(forming.close));
  });

  it('updates the hovered forming bar when a tick changes it', () => {
    const { w, root } = make({});
    const a = walk(20, 100, 17);
    w.series.setData(a);
    const tail = last(a);
    w.chart.emit('crosshair:move', { time: tail.time, index: 19, price: tail.close, bar: tail, point: { x: 10, y: 10 }, paneIndex: 0 });
    w.series.update({ ...tail, close: tail.close + 1.25 });
    expect(read(root, 'c')).toBe(price(tail.close + 1.25));
  });

  it('shows the latest bar a host sets without a feed, after a symbol change', () => {
    const { w, root } = make({ symbol: 'AAA' });
    const a = walk(20, 100, 19);
    w.series.setData(a);
    expect(read(root, 'c')).toBe(price(last(a).close));
    w.setSymbol('BBB');
    expect(read(root, 'c')).toBeNull();
    const b = walk(20, 640, 23);
    w.series.setData(b);
    expect(read(root, 'c')).toBe(price(last(b).close));
  });
});

describe('a status line a host mounts itself', () => {
  it('names the bars already on the chart when it is first titled', () => {
    const { w } = make({ statusline: false });
    const a = walk(30, 100, 37);
    w.series.setData(a);
    const doc = (w.root as unknown as FakeElement).ownerDocument as unknown as Document;
    const el = doc.createElement('div');
    const line = mountStatusline(w.context, el);
    line.setSymbol('AAA', 'NSE', '1d');
    const root = el as unknown as FakeElement;
    expect(read(root, 'c')).toBe(price(last(a).close));
    // A second, different title is a change: the old readings go.
    line.setSymbol('BBB', 'NSE', '1d');
    expect(read(root, 'c')).toBeNull();
    line.destroy();
  });

  it('reads the latest bar on a live tick without copying the history', () => {
    const { w, root } = make({ symbol: 'AAA' });
    const a = walk(500, 100, 41);
    w.series.setData(a);
    const primary = w.chart.primarySeries()!;
    const copy = primary.getData.bind(primary);
    let copies = 0;
    primary.getData = () => { copies++; return copy(); };
    let tail = last(a);
    for (let k = 1; k <= 10; k++) {
      tail = { ...tail, close: tail.close + 0.25 };
      w.series.update(tail);
    }
    expect(read(root, 'c')).toBe(price(tail.close));
    expect(copies).toBe(0);
  });
});

describe('grid cell footers', () => {
  it('shows each cell its own new instrument after a linked symbol change', async () => {
    const { feed, requests } = pendingFeed();
    const doc = fakeWidgetDocument();
    const grid = createChartGrid(fakeContainer(doc, 1200, 800) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      symbol: 'AAA', exchange: 'NSE', interval: '1m', now: () => 60_000_000, rail: false,
      locale: 'en-US', feed, preset: '1x2', links: { symbol: true, crosshair: false, viewport: false },
    });
    grids.push(grid);
    for (const cell of grid.cells()) cell.widget.chart.applySize(600, 400);
    const footer = (i: number): FakeElement => grid.cells()[i].widget.root as unknown as FakeElement;
    const first = walk(50, 100, 29, 60, 60);
    for (const pending of requests.splice(0)) pending.resolve(first);
    await flush();
    expect(read(footer(0), 'c')).toBe(price(last(first).close));
    expect(read(footer(1), 'c')).toBe(price(last(first).close));

    grid.cells()[0].widget.setSymbol('BBB');
    await flush();
    const second = walk(50, 870, 31, 60, 60);
    // The follower asks for the same instrument, so the grid shares one load.
    expect(requests.length).toBeGreaterThan(0);
    expect(requests.every(p => p.request.symbol === 'BBB')).toBe(true);
    expect(grid.cells()[1].widget.symbol()).toBe('BBB');
    for (const pending of requests.splice(0)) pending.resolve(second);
    await flush();
    expect(read(footer(0), 'c')).toBe(price(last(second).close));
    expect(read(footer(1), 'c')).toBe(price(last(second).close));
  });
});
