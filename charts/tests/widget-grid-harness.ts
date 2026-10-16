/**
 * What the chart grid suites share: a grid in the fake DOM with measured
 * charts and a synchronous raf, a seeded random walk for bars, a memory store
 * and a size observer a test fires by hand. Not a suite itself; the vitest
 * include pattern takes only `*.test.ts`.
 */
import { afterEach, vi } from 'vitest';
import type { Bar, BarsRequest, DataFeed } from '../src/index';
import { createChartGrid, type ChartGrid, type ChartGridOptions, type StorageLike } from '../src/widget/index';
import { fakeContainer, fakeWidgetDocument, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

const live: ChartGrid[] = [];
afterEach(() => {
  for (const grid of live.splice(0)) grid.destroy();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

export const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

/**
 * Minute bars as a seeded random walk, the way a real stock moves: `base` is
 * the starting price and the seed, so each instrument walks its own path and
 * a longer walk begins with the shorter one.
 */
export function walk(count: number, base = 100, t0 = 60): Bar[] {
  let seed = Math.round(base * 7919) >>> 0;
  const rand = (): number => {
    seed = (seed + 0x6d2b79f5) >>> 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out: Bar[] = [];
  let close = base;
  for (let i = 0; i < count; i++) {
    const open = close;
    close = Math.max(1, open * (1 + (rand() - 0.49) * 0.012));
    out.push({ time: t0 + i * 60, open, high: Math.max(open, close) * (1 + rand() * 0.004), low: Math.min(open, close) * (1 - rand() * 0.004), close });
  }
  return out;
}

export class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

/** A size observer the test fires by hand, installed as the document's window. */
export class FakeResizeObserver {
  public static all: FakeResizeObserver[] = [];
  public readonly targets: unknown[] = [];
  public constructor(private readonly cb: () => void) { FakeResizeObserver.all.push(this); }
  public observe(target: unknown): void { this.targets.push(target); }
  public unobserve(): void {}
  public disconnect(): void { this.targets.length = 0; }
  public static fire(target: unknown): void {
    for (const o of FakeResizeObserver.all) if (o.targets.includes(target)) o.cb();
  }
}

/** A window with the size observer, so a test can resize the grid. */
export function withWindow(doc: FakeDocument = fakeWidgetDocument()): FakeDocument {
  FakeResizeObserver.all = [];
  (doc as unknown as { defaultView: unknown }).defaultView = {
    ResizeObserver: FakeResizeObserver,
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  return doc;
}

export interface Pending { request: BarsRequest; resolve(bars: Bar[]): void; reject(error: Error): void }
export function pendingFeed(): { feed: DataFeed; requests: Pending[] } {
  const requests: Pending[] = [];
  const feed: DataFeed = { getBars: request => new Promise<Bar[]>((resolve, reject) => { requests.push({ request, resolve, reject }); }) };
  return { feed, requests };
}

export function makeGrid(options: ChartGridOptions = {}, doc: FakeDocument = fakeWidgetDocument()) {
  const container = fakeContainer(doc, 1200, 800);
  const grid = createChartGrid(container as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    symbol: 'AAA', exchange: 'NSE', interval: '1m', now: () => 60_000_000, rail: false, ...options,
  });
  live.push(grid);
  measure(grid);
  return { grid, doc, container, root: grid.root as unknown as FakeElement };
}

/** Give every chart a plot so logical ranges mean something. */
export function measure(grid: ChartGrid): void {
  for (const cell of grid.cells()) cell.widget.chart.applySize(600, 400);
}

export const el = (node: unknown): FakeElement => node as FakeElement;
export const chartEl = (grid: ChartGrid, index: number): FakeElement =>
  el(grid.cells()[index].widget.root).querySelector('.oac-chart')!;
export const topbar = (grid: ChartGrid, index: number): FakeElement =>
  el(grid.cells()[index].widget.root).querySelector('.oac-topbar')!;
