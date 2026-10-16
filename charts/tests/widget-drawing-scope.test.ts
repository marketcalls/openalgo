/**
 * The widget and the chart grid keep drawings per instrument: a symbol change
 * swaps them, a saved layout's drawings stay with the symbol it was saved on,
 * an alert anchored to a drawing stays with that drawing's instrument, and no
 * undo on one symbol brings back a drawing of another. Runs against the fake
 * DOM with measured charts and a synchronous raf, like the widget shell tests.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { registerIndicator, type Bar } from '../src/index';
import type { DrawingInput } from '../src/draw/index';
import {
  createChartGrid, createWidget, DRAWINGS_KEY_PREFIX, STATE_KEY, STORAGE_PREFIX,
  type ChartGrid, type ChartGridOptions, type StorageLike, type Widget, type WidgetOptions,
} from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
beforeAll(() => {
  registerIndicator({
    id: 'scope-osc', name: 'Scope oscillator', placement: 'pane',
    inputs: [{ key: 'length', type: 'number', label: 'Length', default: 5 }],
    plots: [{ key: 'v', title: 'Value', type: 'line' }],
    calc: b => ({ v: b.map(x => x.close - x.open) }),
  });
});

const T0 = 1_700_000_000;
const bars = (n = 40): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: T0 + i * 60, open: c - 1, high: c + 2, low: c - 2, close: c };
});
const line = (price: number, extra: Partial<DrawingInput> = {}): DrawingInput => ({
  tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 10 * 60, price }], ...extra,
});
/** The turn an action ran in is over: observed chart changes are recorded then. */
const settle = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 0));
/** What `alert:removed` carries. */
interface AlertRemovedPayload { alert: { id: string }; reason: string }

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public failWrites: RegExp | null = null;
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void {
    if (this.failWrites?.test(k)) throw new Error('quota');
    this.map.set(k, v);
  }
  public removeItem(k: string): void { this.map.delete(k); }
}

const widgets: Widget[] = [];
const grids: ChartGrid[] = [];
afterEach(() => {
  for (const w of widgets.splice(0)) if (!w.isDestroyed) w.destroy();
  for (const g of grids.splice(0)) if (!g.isDestroyed) g.destroy();
  vi.restoreAllMocks();
});

function make(opts: WidgetOptions = {}): Widget {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc, 800, 600) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1, panels: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    symbol: 'AAA', exchange: 'NSE', ...opts,
  });
  w.chart.applySize(800, 600);
  w.series.setData(bars());
  widgets.push(w);
  return w;
}

/** Move the widget to `symbol` and give it bars, as a host without a feed does. */
function show(w: Widget, symbol: string): void {
  w.setSymbol(symbol);
  w.series.setData(bars());
}

const prices = (w: Widget): number[] => w.draw.drawings().map(d => d.points[0].price);

describe('the widget keeps drawings per instrument', () => {
  it('swaps drawings with the symbol, and a chart scope keeps one set for a host that wants it', () => {
    const w = make();
    w.draw.add(line(101));
    show(w, 'BBB');
    expect(w.draw.drawings()).toEqual([]);
    w.draw.add(line(102));
    show(w, 'AAA');
    expect(prices(w)).toEqual([101]);
    // Another exchange is another instrument.
    w.setSymbol('AAA', 'BSE');
    expect(w.draw.drawings()).toEqual([]);

    const shared = make({ drawingScope: 'chart' });
    expect(shared.instrumentDrawings).toBeNull();
    shared.draw.add(line(101));
    show(shared, 'BBB');
    expect(prices(shared)).toEqual([101]);
  });

  it('attaches the drawings of a layout saved before they were per instrument to the symbol it was saved on', () => {
    const store = new MemoryStorage();
    const legacy = make({ persist: 'old', storage: store });
    legacy.draw.add(line(101));
    legacy.destroy();
    // What an older release left: the layout alone, drawings inside it.
    for (const key of [...store.map.keys()]) if (!key.endsWith(`:${STATE_KEY}`)) store.map.delete(key);
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}old:${STATE_KEY}`)!).chart.drawings.drawings).toHaveLength(1);

    const elsewhere = make({ persist: 'old', storage: store, symbol: 'BBB' });
    expect(elsewhere.draw.drawings()).toEqual([]);
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}old:${DRAWINGS_KEY_PREFIX}NSE:AAA`)!).drawings).toHaveLength(1);
    show(elsewhere, 'AAA');
    expect(prices(elsewhere)).toEqual([101]);
    elsewhere.destroy();

    // Opened on the symbol it was saved on, it shows them as it always did.
    store.map.delete(`${STORAGE_PREFIX}old:${DRAWINGS_KEY_PREFIX}NSE:AAA`);
    const same = make({ persist: 'old', storage: store });
    expect(prices(same)).toEqual([101]);
  });

  it('gives the drawings of a saved layout that names no symbol to the symbol charted', () => {
    const store = new MemoryStorage();
    store.setItem(`${STORAGE_PREFIX}blank:${STATE_KEY}`, JSON.stringify({
      version: 1, symbol: '', exchange: '', interval: '1d', chartType: 'candlestick', theme: 'dark', rail: null,
      chart: { version: 1, drawings: { version: 2, drawings: [{ ...line(101), id: 'kept', zIndex: 0 }] } },
    }));
    const w = make({ persist: 'blank', storage: store });
    expect(w.draw.drawings().map(d => d.id)).toEqual(['kept']);
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}blank:${DRAWINGS_KEY_PREFIX}NSE:AAA`)!).drawings).toHaveLength(1);
  });

  it('restores a layout for another symbol with its drawings and alerts on their own instruments', () => {
    const w = make();
    const onA = w.draw.add(line(101));
    const alertA = w.alerts.add({ source: { kind: 'drawing', drawingId: onA.id } });
    show(w, 'BBB');
    const onB = w.draw.add(line(99));
    const alertB = w.alerts.add({ source: { kind: 'drawing', drawingId: onB.id } });
    // A layout saved on A: A's drawings, and every alert the chart held.
    const state = w.getState();
    const layout = { ...state, symbol: 'AAA', chart: { ...state.chart, drawings: { version: 2, drawings: [{ ...onA }] } } };
    const removed: AlertRemovedPayload[] = [];
    w.chart.on('alert:removed', event => removed.push(event as AlertRemovedPayload));
    expect(w.restoreState(layout).applied).toBe(true);
    expect(w.symbol()).toBe('AAA');
    w.series.setData(bars());
    expect(w.draw.drawings().map(d => d.id)).toEqual([onA.id]);
    // B's alert was judged against B's drawings, which were on screen, and A's against A's.
    expect(removed).toEqual([]);
    expect(w.alerts.list().map(a => a.id).sort()).toEqual([alertA.id, alertB.id].sort());
    expect(w.alerts.availability(alertA.id).available).toBe(true);
    show(w, 'BBB');
    expect(w.draw.drawings().map(d => d.id)).toEqual([onB.id]);
    expect(w.alerts.availability(alertB.id).available).toBe(true);
  });

  it('reports a store that refuses the drawings, and keeps them for the session', () => {
    const store = new MemoryStorage();
    store.failWrites = /drawings:/;
    const w = make({ persist: 'full', storage: store });
    const messages: string[] = [];
    w.on('status', ({ text }) => messages.push(text));
    w.draw.add(line(101));
    expect(messages).toContain('The drawings for NSE:AAA could not be saved');
    show(w, 'BBB');
    show(w, 'AAA');
    expect(prices(w)).toEqual([101]);
  });
});

describe('alerts anchored to a drawing across a symbol change', () => {
  it('keeps the alert with its instrument, idle on another symbol, even over a drawing with the same id', () => {
    const w = make();
    const onA = w.draw.add(line(101, { id: 'level' }));
    const alert = w.alerts.add({ source: { kind: 'drawing', drawingId: onA.id } });
    const removed: AlertRemovedPayload[] = [];
    w.chart.on('alert:removed', event => removed.push(event as AlertRemovedPayload));
    const fired: unknown[] = [];
    w.chart.on('alert:triggered', event => fired.push(event));
    show(w, 'BBB');
    expect(w.alerts.list().map(a => a.id)).toEqual([alert.id]);
    expect(w.alerts.availability(alert.id)).toMatchObject({ available: false, reason: 'Instrument context differs' });
    // B has a drawing under the same id: it is not A's, and the alert is not its.
    w.draw.add(line(90, { id: 'level' }));
    w.series.update({ time: T0 + 40 * 60, open: 80, high: 120, low: 80, close: 110 });
    w.series.update({ time: T0 + 41 * 60, open: 110, high: 111, low: 109, close: 110 });
    expect(fired).toEqual([]);
    w.draw.removeMany(['level']);
    expect(removed).toEqual([]);
    show(w, 'AAA');
    expect(w.alerts.availability(alert.id).available).toBe(true);
    // Deleted on its own instrument, it goes as it always did.
    w.draw.remove(onA.id);
    expect(removed.map(r => r.reason)).toEqual(['drawing-removed']);
  });
});

describe('the chart-wide undo history across a symbol change', () => {
  it('takes back no drawing step of the symbol it left', () => {
    const w = make();
    const made = w.draw.add(line(101));
    expect(w.history.canUndo()).toBe(true);
    show(w, 'BBB');
    expect(w.history.canUndo()).toBe(false);
    expect(w.history.undo()).toBe(false);
    show(w, 'AAA');
    expect(w.draw.get(made.id)).toBeDefined();
  });

  it('brings a removed pane back without the drawings another symbol had on it', async () => {
    const w = make();
    w.chart.addIndicator('scope-osc');
    await settle();
    w.draw.add(line(1, { paneIndex: 1 }));
    await settle();
    expect(w.chart.removePane(1)).toBe(true);
    await settle();
    expect(w.draw.drawings()).toEqual([]);
    expect(w.history.peekUndo()?.changes).toContain('study-remove');
    show(w, 'BBB');
    expect(w.history.undo()).toBe(true);
    expect(w.chart.panes()).toHaveLength(2);
    expect(w.draw.drawings()).toEqual([]);
  });

  it('keeps the steps of the studies, which belong to the chart and not to a symbol', async () => {
    const w = make();
    w.chart.addIndicator('scope-osc');
    await settle();
    w.draw.add(line(101));
    show(w, 'BBB');
    expect(w.history.peekUndo()?.changes).toEqual(['study-add']);
    expect(w.history.undo()).toBe(true);
    expect(w.chart.indicators()).toHaveLength(0);
  });
});

describe('the chart grid keeps drawings per chart and per instrument', () => {
  function makeGrid(options: ChartGridOptions = {}): ChartGrid {
    const doc = fakeWidgetDocument();
    const grid = createChartGrid(fakeContainer(doc, 1200, 800) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
      symbol: 'AAA', exchange: 'NSE', interval: '1m', rail: false, preset: '1x2', ...options,
    });
    grids.push(grid);
    for (const cell of grid.cells()) { cell.widget.chart.applySize(600, 400); cell.widget.series.setData(bars()); }
    return grid;
  }
  const cell = (grid: ChartGrid, i: number): Widget => grid.cells()[i].widget;

  it('gives each chart its own documents, so two charts on one symbol never share one', () => {
    const grid = makeGrid();
    cell(grid, 0).draw.add(line(101));
    expect(cell(grid, 1).draw.drawings()).toEqual([]);
    show(cell(grid, 1), 'BBB');
    show(cell(grid, 1), 'AAA');
    expect(cell(grid, 1).draw.drawings()).toEqual([]);
    show(cell(grid, 0), 'BBB');
    expect(cell(grid, 0).draw.drawings()).toEqual([]);
    show(cell(grid, 0), 'AAA');
    expect(prices(cell(grid, 0))).toEqual([101]);
  });

  it('saves the documents beside the workspace, restores them, and drops those of a chart the grid drops', async () => {
    const store = new MemoryStorage();
    const first = makeGrid({ persist: 'desk', storage: store });
    cell(first, 1).draw.add(line(101));
    show(cell(first, 1), 'BBB');
    cell(first, 1).draw.add(line(102));
    first.destroy();
    const saved = JSON.parse(store.map.get(`${STORAGE_PREFIX}desk:grid-drawings`)!);
    expect(Object.keys(saved.charts)).toEqual(['p1']);
    expect(Object.keys(saved.charts.p1).sort()).toEqual(['NSE:AAA', 'NSE:BBB']);

    const second = makeGrid({ persist: 'desk', storage: store });
    expect(cell(second, 1).symbol()).toBe('BBB');
    expect(prices(cell(second, 1))).toEqual([102]);
    show(cell(second, 1), 'AAA');
    expect(prices(cell(second, 1))).toEqual([101]);
    second.setPreset('1x1');
    await settle();
    second.destroy();
    expect(JSON.parse(store.map.get(`${STORAGE_PREFIX}desk:grid-drawings`)!).charts).toEqual({});
  });

  it('starts a workspace the host hands over from its own payload, not the documents of the charts it replaces', () => {
    const grid = makeGrid();
    cell(grid, 0).draw.add(line(101));
    show(cell(grid, 0), 'BBB');
    const payload = grid.getWorkspace();
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    const w = cell(grid, 0);
    w.chart.applySize(600, 400);
    expect(w.symbol()).toBe('BBB');
    show(w, 'AAA');
    expect(w.draw.drawings()).toEqual([]);
  });
});
