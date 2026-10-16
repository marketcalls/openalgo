/**
 * The chart grid: several widgets under one layout, one active cell, splitters,
 * linked navigation and the portable workspace payload. Runs against the fake
 * DOM with measured charts and a synchronous raf, like the widget shell tests.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart, applyChartSettings, type Bar, type BarsRequest, type DataFeed } from '../src/index';
import '../src/indicators/index';
import { parseWorkspacePayload, type WorkspacePayload } from '../src/workspace/index';
import { createChartGrid, CHART_GRID_PRESETS, type ChartGrid, type ChartGridOptions, type StorageLike } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const live: ChartGrid[] = [];
afterEach(() => {
  for (const grid of live.splice(0)) grid.destroy();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const bars = (count: number, base = 100, t0 = 60): Bar[] => Array.from({ length: count }, (_, i) => {
  const close = base + Math.sin(i / 4) * 5;
  return { time: t0 + i * 60, open: close - 1, high: close + 2, low: close - 2, close };
});

class MemoryStorage implements StorageLike {
  public readonly map = new Map<string, string>();
  public getItem(k: string): string | null { return this.map.get(k) ?? null; }
  public setItem(k: string, v: string): void { this.map.set(k, v); }
  public removeItem(k: string): void { this.map.delete(k); }
}

/** A size observer the test fires by hand, installed as the document's window. */
class FakeResizeObserver {
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

interface FakeWindow { fire(type: string): void }

/** A window with the size observer and page lifecycle listeners a test can fire. */
function withWindow(doc: FakeDocument): FakeDocument {
  const listeners = new Map<string, Set<(e: unknown) => void>>();
  (doc as unknown as { defaultView: unknown }).defaultView = {
    ResizeObserver: FakeResizeObserver,
    addEventListener: (type: string, fn: (e: unknown) => void) => { listeners.set(type, (listeners.get(type) ?? new Set()).add(fn)); },
    removeEventListener: (type: string, fn: (e: unknown) => void) => { listeners.get(type)?.delete(fn); },
    fire: (type: string) => { for (const fn of [...(listeners.get(type) ?? [])]) fn({ type }); },
  };
  return doc;
}
const windowOf = (doc: FakeDocument): FakeWindow => (doc as unknown as { defaultView: FakeWindow }).defaultView;
const SAVED = 'oac-widget:desk:grid';
const stored = (storage: MemoryStorage): WorkspacePayload => JSON.parse(storage.map.get(SAVED)!) as WorkspacePayload;

interface Pending { request: BarsRequest; resolve(bars: Bar[]): void; reject(error: Error): void }
function pendingFeed(): { feed: DataFeed; requests: Pending[] } {
  const requests: Pending[] = [];
  const feed: DataFeed = { getBars: request => new Promise<Bar[]>((resolve, reject) => { requests.push({ request, resolve, reject }); }) };
  return { feed, requests };
}

function makeGrid(options: ChartGridOptions = {}, doc: FakeDocument = fakeWidgetDocument()) {
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
function measure(grid: ChartGrid): void {
  for (const cell of grid.cells()) cell.widget.chart.applySize(600, 400);
}

const chartEl = (grid: ChartGrid, index: number): FakeElement =>
  (grid.cells()[index].widget.root as unknown as FakeElement).querySelector('.oac-chart')!;

describe('chart grid presets and lifecycle', () => {
  it('builds one widget per preset cell and destroys only the cells a smaller preset drops', () => {
    const created = vi.spyOn(Chart.prototype, 'addSeries');
    const destroyed = vi.spyOn(Chart.prototype, 'destroy');
    const { grid, root, container } = makeGrid({ preset: '1x1' });
    expect(created).toHaveBeenCalledTimes(1);
    const first = grid.cells()[0].widget;
    grid.setPreset('2x2');
    expect(created).toHaveBeenCalledTimes(4);
    expect(grid.cells()).toHaveLength(4);
    expect(grid.cells()[0].widget).toBe(first);
    expect(grid.cells().map(cell => [cell.row, cell.column])).toEqual([[0, 0], [0, 1], [1, 0], [1, 1]]);
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'AAA', 'AAA', 'AAA']);
    expect(root.querySelectorAll('.oac-widget')).toHaveLength(4);
    const kept = grid.cells().slice(0, 2).map(cell => cell.widget);
    const dropped = grid.cells().slice(2).map(cell => cell.widget);
    grid.setPreset('1x2');
    expect(created).toHaveBeenCalledTimes(4);
    expect(destroyed).toHaveBeenCalledTimes(2);
    expect(grid.cells().map(cell => cell.widget)).toEqual(kept);
    expect(dropped.every(widget => widget.isDestroyed)).toBe(true);
    expect(root.querySelectorAll('.oac-grid__cell')).toHaveLength(2);
    expect(grid.layout()).toEqual({ rows: 1, columns: 2, preset: '1x2', rowWeights: [1], columnWeights: [1, 1] });
    grid.destroy();
    expect(destroyed).toHaveBeenCalledTimes(4);
    expect(kept.every(widget => widget.isDestroyed)).toBe(true);
    expect(container.children).toHaveLength(0);
    expect(grid.isDestroyed).toBe(true);
  });

  it('offers every row and column preset and refuses one it does not know', () => {
    const { grid } = makeGrid();
    for (const [name, [rows, columns]] of Object.entries(CHART_GRID_PRESETS)) {
      grid.setPreset(name as keyof typeof CHART_GRID_PRESETS);
      expect(grid.cells()).toHaveLength(rows * columns);
      expect(grid.layout()).toMatchObject({ rows, columns, preset: name });
    }
    // Four by four is a preset since 2.5.10; past it, and a name off the prototype, are not.
    expect(() => grid.setPreset('5x5' as never)).toThrow(/preset/);
    expect(() => grid.setPreset('constructor' as never)).toThrow(/preset/);
  });

  it('keeps the active chart when it survives a smaller preset and moves to the first when it does not', () => {
    const { grid } = makeGrid({ preset: '2x2' });
    grid.setActive(grid.cells()[1].id);
    grid.setPreset('1x2');
    expect(grid.active().id).toBe(grid.cells()[1].id);
    grid.setPreset('2x2');
    grid.setActive(grid.cells()[3].id);
    grid.setPreset('1x2');
    expect(grid.active().id).toBe(grid.cells()[0].id);
  });
});

describe('chart grid data loading', () => {
  it('cancels a removed chart request and never lets its late answer land', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2' });
    // Identical requests share one feed call across the two charts.
    expect(requests).toHaveLength(1);
    grid.cells()[1].widget.setSymbol('BBB');
    expect(requests.map(entry => entry.request.symbol)).toEqual(['AAA', 'BBB']);
    const survivor = grid.cells()[0].widget;
    grid.setPreset('1x1');
    expect(requests[1].request.signal?.aborted).toBe(true);
    expect(requests[0].request.signal?.aborted).toBe(false);
    requests[1].resolve(bars(10, 500));
    requests[0].resolve(bars(20));
    await flush();
    expect(survivor.series.getData()).toHaveLength(20);
    expect(survivor.series.getData()[0].close).toBeLessThan(200);
    survivor.setSymbol('DDD');
    expect(requests[2].request.symbol).toBe('DDD');
    grid.destroy();
    expect(requests[2].request.signal?.aborted).toBe(true);
  });

  it('switches a linked follower to the new instrument and drops the stale answer for the old one', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2', links: { symbol: true } });
    const [leader, follower] = grid.cells().map(cell => cell.widget);
    const symbolEvents = [0, 0];
    leader.on('symbol', () => symbolEvents[0]++);
    follower.on('symbol', () => symbolEvents[1]++);
    leader.setSymbol('CCC', 'BSE');
    expect(symbolEvents).toEqual([1, 1]);
    expect(follower.symbol()).toBe('CCC');
    expect(follower.exchange()).toBe('BSE');
    expect(requests.map(entry => entry.request.symbol)).toEqual(['AAA', 'CCC']);
    expect(requests[0].request.signal?.aborted).toBe(true);
    requests[0].resolve(bars(5, 900));
    await flush();
    expect(leader.series.getData()).toEqual([]);
    expect(follower.series.getData()).toEqual([]);
    requests[1].resolve(bars(12));
    await flush();
    expect(follower.series.getData()).toHaveLength(12);
    expect(follower.chart.getDataContext()).toMatchObject({ symbol: 'CCC', exchange: 'BSE' });
  });

  it('follows a linked interval once in each chart without an echo', () => {
    const { grid } = makeGrid({ preset: '1x3', links: { interval: true } });
    const widgets = grid.cells().map(cell => cell.widget);
    const counts = widgets.map(() => 0);
    widgets.forEach((widget, i) => widget.on('interval', () => counts[i]++));
    widgets[2].setInterval('5m');
    expect(widgets.map(widget => widget.interval())).toEqual(['5m', '5m', '5m']);
    expect(counts).toEqual([1, 1, 1]);
  });
});

describe('chart grid linked navigation', () => {
  it('mirrors a pan once, without echoing back to the leader', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const [a, b] = grid.cells().map(cell => cell.widget.chart);
    grid.cells()[0].widget.series.setData(bars(200));
    grid.cells()[1].widget.series.setData(bars(200));
    await flush();
    const followerSet = vi.spyOn(b, 'setVisibleLogicalRange');
    const leaderSet = vi.spyOn(a, 'setVisibleLogicalRange');
    a.setVisibleLogicalRange({ from: 40, to: 90 });
    expect(followerSet).toHaveBeenCalledTimes(1);
    expect(leaderSet).toHaveBeenCalledTimes(1);
    expect(b.getVisibleLogicalRange()).toEqual(a.getVisibleLogicalRange());
  });

  it('keeps a view set by freshly loaded bars local until the next real navigation', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2', links: { viewport: true, crosshair: false } });
    const [a, b] = grid.cells().map(cell => cell.widget.chart);
    requests[0].resolve(bars(300));
    await flush();
    a.setVisibleLogicalRange({ from: 100, to: 160 });
    expect(b.getVisibleLogicalRange()).toEqual(a.getVisibleLogicalRange());
    const before = a.getVisibleLogicalRange();
    grid.cells()[1].widget.setSymbol('BBB');
    requests[1].resolve(bars(120, 400, 60 + 180 * 60));
    await flush();
    // The follower fitted its new instrument; the leader kept its window.
    expect(b.getVisibleLogicalRange()).not.toEqual(before);
    expect(a.getVisibleLogicalRange()).toEqual(before);
    b.setVisibleLogicalRange({ from: 20, to: 70 });
    expect(a.getVisibleLogicalRange()).not.toEqual(before);
  });
});

describe('chart grid linked appearance and undo', () => {
  it('applies a linked appearance change outside the timeline of the chart following it, and walks it back on every chart', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { appearance: true, crosshair: false, viewport: false } });
    const [leader, follower] = grid.cells().map(cell => cell.widget);
    for (const widget of [leader, follower]) widget.series.setData(bars(120));
    await flush();
    leader.history.clear();
    follower.history.clear();
    const mode = (widget: typeof leader): string | undefined => widget.chart.priceAxisState(0, 'right')?.mode;

    leader.history.transact(() => applyChartSettings(leader.chart, { 'scales.mode': 'logarithmic' }), 'Chart settings');
    expect(mode(follower)).toBe('logarithmic');
    // The leader's step, not the follower's.
    expect(follower.history.canUndo()).toBe(false);
    follower.chart.addIndicator('rsi');
    await flush();
    expect(follower.history.peekUndo()?.changes).toEqual(['study-add']);
    follower.history.undo();
    expect([mode(leader), mode(follower)]).toEqual(['logarithmic', 'logarithmic']);

    leader.history.undo();
    expect([mode(leader), mode(follower)]).toEqual(['linear', 'linear']);
    leader.history.redo();
    expect([mode(leader), mode(follower)]).toEqual(['logarithmic', 'logarithmic']);
  });
});

describe('chart grid theme', () => {
  it('restyles every chart when one chart switches theme, and says so once', () => {
    const { grid, root } = makeGrid({ preset: '1x3' });
    const themes: string[] = [];
    grid.on('theme', ({ theme }) => themes.push(theme));
    grid.cells()[1].widget.setTheme('light');
    expect(grid.cells().map(cell => cell.widget.theme())).toEqual(['light', 'light', 'light']);
    expect(grid.theme()).toBe('light');
    expect(root.dataset.theme).toBe('light');
    expect(themes).toEqual(['light']);
  });
});

describe('chart grid focus and keyboard routing', () => {
  it('sends chords only to the active chart, even with the pointer over another', async () => {
    const { grid, doc } = makeGrid({ preset: '1x2', links: { viewport: false, crosshair: false } });
    const cells = grid.cells();
    for (const cell of cells) cell.widget.series.setData(bars(200));
    await flush();
    const hits = [0, 0];
    cells.forEach((cell, i) => cell.widget.context.keymap.register('x', () => { hits[i]++; return true; }, 'widget'));
    const activated: string[] = [];
    grid.on('active', ({ id }) => activated.push(id));
    expect(grid.setActive(cells[1].id, { focus: true })).toBe(true);
    expect(activated).toEqual([cells[1].id]);
    expect(doc.activeElement).toBe(chartEl(grid, 1));
    expect((cells[1].element as unknown as FakeElement).dataset.active).toBe('true');
    expect((cells[0].element as unknown as FakeElement).dataset.active).toBe('false');
    // The pointer rests on the inactive chart while the focus is in the active one.
    fire(cells[0].widget.root as unknown as FakeElement, 'pointerenter');
    fire(chartEl(grid, 0), 'pointerenter');
    fireKey(doc.activeElement, 'x');
    expect(hits).toEqual([0, 1]);
    const [a, b] = cells.map(cell => cell.widget.chart.getVisibleLogicalRange());
    fireKey(doc.activeElement, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(cells[0].widget.chart.getVisibleLogicalRange()).toEqual(a);
    expect(cells[1].widget.chart.getVisibleLogicalRange()).not.toEqual(b);
  });

  it('routes a key pressed with the focus on the page to the active chart', async () => {
    const { grid, doc, root } = makeGrid({ preset: '1x2', links: { viewport: false, crosshair: false } });
    const cells = grid.cells();
    for (const cell of cells) cell.widget.series.setData(bars(200));
    await flush();
    const hits = [0, 0];
    cells.forEach((cell, i) => cell.widget.context.keymap.register('x', () => { hits[i]++; return true; }, 'widget'));
    grid.setActive(cells[1].id);
    fire(root, 'pointerenter');
    fire(cells[0].widget.root as unknown as FakeElement, 'pointerenter');
    fireKey(doc.body, 'x');
    expect(hits).toEqual([0, 1]);
    const before = cells[1].widget.chart.getVisibleLogicalRange();
    fireKey(doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(cells[1].widget.chart.getVisibleLogicalRange()).not.toEqual(before);
    fire(root, 'pointerleave');
    fireKey(doc.body, 'x');
    expect(hits).toEqual([0, 1]);
  });

  it('activates the chart a pointer presses or the focus enters', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const cells = grid.cells();
    fire(chartEl(grid, 1), 'pointerdown', { button: 0 });
    expect(grid.active().id).toBe(cells[1].id);
    chartEl(grid, 0).focus();
    expect(grid.active().id).toBe(cells[0].id);
    expect((cells[0].element as unknown as FakeElement).getAttribute('aria-current')).toBe('true');
  });
});

describe('chart grid splitters and resizing', () => {
  it('resizes neighbouring tracks by pointer and keyboard within bounds', () => {
    const { grid, root } = makeGrid({ preset: '1x2' });
    const body = root.querySelector('.oac-grid__cells')!;
    body.rect = { left: 0, top: 0, width: 1004, height: 600 };
    const split = root.querySelector('.oac-grid__split')!;
    expect(split.getAttribute('role')).toBe('separator');
    expect(split.getAttribute('aria-orientation')).toBe('vertical');
    expect(split.getAttribute('aria-valuenow')).toBe('50');
    const reasons: string[] = [];
    grid.on('layout', ({ reason }) => reasons.push(reason));
    fire(split, 'pointerdown', { button: 0, clientX: 500 });
    fire(split, 'pointermove', { clientX: 700 });
    fire(split, 'pointerup', { clientX: 700 });
    expect(grid.layout().columnWeights[0]).toBeCloseTo(1.4, 3);
    expect(grid.layout().columnWeights[1]).toBeCloseTo(0.6, 3);
    expect(split.getAttribute('aria-valuenow')).toBe('70');
    expect(body.style.gridTemplateColumns).toBe('minmax(0,1.4fr) 4px minmax(0,0.6fr)');
    fire(split, 'pointerdown', { button: 0, clientX: 700 });
    fire(split, 'pointermove', { clientX: -2000 });
    fire(split, 'pointerup');
    expect(grid.layout().columnWeights).toEqual([0.3, 1.7]);
    split.focus();
    const key = fireKey(split, 'ArrowRight');
    expect(key.defaultPrevented).toBe(true);
    expect(grid.layout().columnWeights).toEqual([0.4, 1.6]);
    fire(split, 'dblclick');
    expect(grid.layout().columnWeights).toEqual([1, 1]);
    expect(reasons.every(reason => reason === 'weights')).toBe(true);
    expect(grid.getWorkspace().layout.columnWeights).toEqual([1, 1]);
  });

  it('names the charts, splitters and tabs through the host translator', () => {
    const translate = (key: string, fallback: string): string => ({
      'Resize columns {first} and {second}': 'Ajustar columnas {first} y {second}', 'Chart {index}': 'Grafico {index}', Charts: 'Graficos',
    } as Record<string, string>)[key] ?? fallback;
    const { grid, root } = makeGrid({ preset: '1x2', translate });
    expect(root.querySelector('.oac-grid__split')!.getAttribute('aria-label')).toBe('Ajustar columnas 1 y 2');
    expect(grid.cells().map(cell => (cell.element as unknown as FakeElement).getAttribute('aria-label'))).toEqual(['Grafico 1', 'Grafico 2']);
    expect(root.querySelector('.oac-grid__tabs')!.getAttribute('aria-label')).toBe('Graficos');
  });

  it('draws a row splitter only where no spanning chart crosses the boundary', () => {
    const { grid, root } = makeGrid();
    const payload = grid.getWorkspace();
    const pane = payload.panes[0];
    payload.layout = { rows: 2, columns: 2, slots: [
      { paneId: 'wide', row: 0, column: 0, rowSpan: 1, columnSpan: 2 },
      { paneId: 'left', row: 1, column: 0, rowSpan: 1, columnSpan: 1 },
      { paneId: 'right', row: 1, column: 1, rowSpan: 1, columnSpan: 1 },
    ] };
    payload.panes = ['wide', 'left', 'right'].map(id => ({ ...pane, id }));
    payload.activePaneId = 'left';
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    const splits = root.querySelectorAll('.oac-grid__split');
    expect(splits.map(split => [split.dataset.axis, split.style.gridArea])).toEqual([
      ['column', '3 / 2 / 4 / 3'],
      ['row', '2 / 1 / 3 / 4'],
    ]);
    expect((grid.cells()[0].element as unknown as FakeElement).style.gridArea).toBe('1 / 1 / 2 / 4');
  });

  it('shows only the active chart with tabs below the compact width and restores the grid above it', () => {
    FakeResizeObserver.all = [];
    const { grid, root } = makeGrid({ preset: '2x2' }, withWindow(fakeWidgetDocument()));
    const reasons: string[] = [];
    grid.on('layout', ({ reason }) => reasons.push(reason));
    grid.cells()[2].widget.setSymbol('ZZZ');
    root.rect = { left: 0, top: 0, width: 1100, height: 700 };
    FakeResizeObserver.fire(root);
    expect(grid.compact()).toBe(false);
    root.rect = { left: 0, top: 0, width: 420, height: 700 };
    FakeResizeObserver.fire(root);
    expect(grid.compact()).toBe(true);
    expect(root.dataset.compact).toBe('true');
    expect(grid.cells().map(cell => (cell.element as unknown as FakeElement).hidden)).toEqual([false, true, true, true]);
    expect(root.querySelectorAll('.oac-grid__split').every(split => split.hidden)).toBe(true);
    const tabs = root.querySelectorAll('.oac-grid__tab');
    expect(tabs.map(tab => tab.textContent)).toEqual(['AAA 1m', 'AAA 1m', 'ZZZ 1m', 'AAA 1m']);
    // Tabs that read the same are named by their place, a unique one by its text.
    expect(tabs.map(tab => tab.getAttribute('aria-label'))).toEqual(['AAA 1m (1)', 'AAA 1m (2)', null, 'AAA 1m (4)']);
    tabs[2].click();
    expect(grid.active().id).toBe(grid.cells()[2].id);
    expect(grid.cells().map(cell => (cell.element as unknown as FakeElement).hidden)).toEqual([true, true, false, true]);
    expect(root.querySelectorAll('.oac-grid__tab')[2].getAttribute('aria-selected')).toBe('true');
    root.rect = { left: 0, top: 0, width: 900, height: 700 };
    FakeResizeObserver.fire(root);
    expect(grid.compact()).toBe(false);
    expect(grid.cells().every(cell => !(cell.element as unknown as FakeElement).hidden)).toBe(true);
    expect((root.querySelector('.oac-grid__tabs') as FakeElement).hidden).toBe(true);
    expect(reasons).toEqual(['compact', 'compact']);
  });
});

describe('chart grid workspaces', () => {
  function desk(): ChartGrid {
    const { grid } = makeGrid({ preset: '2x2', links: { crosshair: true, viewport: false } });
    grid.cells().forEach((cell, i) => cell.widget.setSymbol(['AAA', 'BBB', 'CCC', 'DDD'][i]));
    grid.cells()[3].widget.setInterval('5m');
    grid.cells()[1].widget.chart.addIndicator('ema', { period: 9 });
    grid.setActive(grid.cells()[2].id);
    grid.setTheme('light');
    return grid;
  }

  it('writes a payload the workspace parser accepts and applies it to another grid', () => {
    const source = desk();
    const payload = parseWorkspacePayload(JSON.stringify(source.getWorkspace()));
    expect(payload.layout).toMatchObject({ rows: 2, columns: 2, preset: '2x2', rowWeights: [1, 1], columnWeights: [1, 1] });
    expect(payload.sync).toMatchObject({ crosshair: true, viewport: false, symbol: false, interval: false });
    expect(payload.panes.map(pane => [pane.symbol, pane.interval, pane.settings['widget.theme']])).toEqual([
      ['AAA', '1m', 'light'], ['BBB', '1m', 'light'], ['CCC', '1m', 'light'], ['DDD', '5m', 'light'],
    ]);
    const { grid: target } = makeGrid();
    expect(target.applyWorkspace(payload)).toEqual({ applied: true });
    expect(target.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'BBB', 'CCC', 'DDD']);
    expect(target.cells()[3].widget.interval()).toBe('5m');
    expect(target.active().id).toBe(payload.activePaneId);
    expect(target.theme()).toBe('light');
    expect(target.linkOptions()).toMatchObject({ crosshair: true, viewport: false, symbol: false, interval: false });
    expect(target.cells()[1].widget.chart.getState().indicators).toHaveLength(1);
    const again = parseWorkspacePayload(JSON.stringify(target.getWorkspace()));
    expect(again.layout).toEqual(payload.layout);
    expect(again.panes.map(pane => pane.id)).toEqual(payload.panes.map(pane => pane.id));
  });

  it('persists the workspace and restores it on the next construction', async () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ persist: 'desk', storage, preset: '1x2' });
    grid.cells()[1].widget.setSymbol('BBB');
    grid.setActive(grid.cells()[1].id);
    grid.setLinks({ viewport: false });
    await flush();
    const saved = JSON.parse(storage.map.get('oac-widget:desk:grid')!) as WorkspacePayload;
    expect(saved.panes.map(pane => pane.symbol)).toEqual(['AAA', 'BBB']);
    expect(saved.activePaneId).toBe(grid.cells()[1].id);
    grid.destroy();
    const { grid: restored } = makeGrid({ persist: 'desk', storage });
    expect(restored.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'BBB']);
    expect(restored.active().id).toBe(saved.activePaneId);
    expect(restored.linkOptions().viewport).toBe(false);
    storage.map.set('oac-widget:desk:grid', '{"layout":7}');
    const { grid: fallback } = makeGrid({ persist: 'desk', storage, preset: '1x3' });
    expect(fallback.cells()).toHaveLength(3);
  });

  it('rolls back a failed import: the old charts stay and the staged ones are cancelled', () => {
    const { feed, requests } = pendingFeed();
    const { grid, root } = makeGrid({ feed, preset: '1x2', links: { crosshair: true, viewport: true } });
    const before = grid.cells().map(cell => cell.widget);
    grid.setActive(grid.cells()[1].id);
    const payload = grid.getWorkspace();
    payload.panes = [
      { ...payload.panes[0], id: 'n0', symbol: 'NEW1' },
      { ...payload.panes[0], id: 'n1', symbol: 'NEW2' },
      { ...payload.panes[0], id: 'n2', symbol: 'NEW3', chart: { ...payload.panes[0].chart, version: 99 } as never },
    ];
    payload.layout = { rows: 1, columns: 3, slots: payload.panes.map((pane, column) => ({ paneId: pane.id, row: 0, column, rowSpan: 1, columnSpan: 1 })) };
    payload.activePaneId = 'n0';
    const destroyed = vi.spyOn(Chart.prototype, 'destroy');
    const report = grid.applyWorkspace(payload);
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/n2/);
    expect(destroyed).toHaveBeenCalledTimes(3);
    expect(requests.filter(entry => entry.request.symbol.startsWith('NEW')).every(entry => entry.request.signal?.aborted)).toBe(true);
    expect(grid.cells().map(cell => cell.widget)).toEqual(before);
    expect(before.some(widget => widget.isDestroyed)).toBe(false);
    expect(root.querySelectorAll('.oac-widget')).toHaveLength(2);
    expect(grid.active().id).toBe(grid.cells()[1].id);
    expect(grid.layout()).toMatchObject({ rows: 1, columns: 2 });
    expect(requests[0].request.signal?.aborted).toBe(false);
  });

  it.each([
    ['an unknown interval', (p: WorkspacePayload) => { p.panes[0].interval = '7q'; }, /interval/],
    ['an unknown chart type', (p: WorkspacePayload) => { p.panes[0].chartType = 'nope'; }, /chart type/],
    ['an unavailable study', (p: WorkspacePayload) => { p.panes[0].chart.indicators = [{ indicatorId: 'missing-study', settings: {}, paneIndex: 0 }]; }, /study/],
    ['comparison symbols', (p: WorkspacePayload) => { p.panes[0].comparisons = [{ id: 'c', symbol: 'X', exchange: '', visible: true }]; }, /comparison/],
    ['conflicting linked symbols', (p: WorkspacePayload) => { p.sync.symbol = true; p.panes[1].symbol = 'OTHER'; }, /linked/],
    ['linked symbols on different exchanges', (p: WorkspacePayload) => { p.sync.symbol = true; p.panes[1].exchange = 'BSE'; }, /linked symbols/],
    ['conflicting linked intervals', (p: WorkspacePayload) => { p.sync.interval = true; p.panes[1].interval = '5m'; }, /linked intervals/],
    ['a negative track weight', (p: WorkspacePayload) => { p.layout.columnWeights = [1, -1]; }, /weights/],
    ['track weights that miss a track', (p: WorkspacePayload) => { p.layout.rowWeights = [1, 1]; }, /weights/],
    ['overlapping slots', (p: WorkspacePayload) => { p.layout.slots[1].column = 0; }, /slot/],
    ['a missing active chart', (p: WorkspacePayload) => { p.activePaneId = 'gone'; }, /active/],
  ])('refuses %s before building anything', (_name, change, reason) => {
    const { grid } = makeGrid({ preset: '1x2' });
    const payload = grid.getWorkspace();
    change(payload);
    const created = vi.spyOn(Chart.prototype, 'addSeries');
    const report = grid.applyWorkspace(payload);
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(reason);
    expect(created).not.toHaveBeenCalled();
    expect(grid.cells()).toHaveLength(2);
  });

  it('links the applied charts on their own saved instrument, not the one the grid showed before', () => {
    const { grid } = makeGrid({ preset: '1x2', links: { symbol: true, interval: true } });
    const payload = grid.getWorkspace();
    for (const pane of payload.panes) { pane.symbol = 'ZZZ'; pane.interval = '5m'; }
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.cells().map(cell => [cell.widget.symbol(), cell.widget.interval()])).toEqual([['ZZZ', '5m'], ['ZZZ', '5m']]);
    grid.cells()[0].widget.setSymbol('YYY');
    expect(grid.cells()[1].widget.symbol()).toBe('YYY');
  });

  it('keeps each saved chart on its own instrument when the workspace links viewports', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2' });
    const payload = grid.getWorkspace();
    payload.panes[0].symbol = 'LEFT';
    payload.panes[1].symbol = 'RIGHT';
    payload.panes[1].interval = '5m';
    payload.sync = { crosshair: true, viewport: true, symbol: false, interval: false };
    const count = requests.length;
    expect(grid.applyWorkspace(payload).applied).toBe(true);
    expect(requests.slice(count).map(entry => [entry.request.symbol, entry.request.interval])).toEqual([['LEFT', '1m'], ['RIGHT', '5m']]);
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['LEFT', 'RIGHT']);
    expect(requests.slice(0, count).every(entry => entry.request.signal?.aborted)).toBe(true);
  });

  it('restores saved track weights onto the tracks and the splitters', () => {
    const { grid, root } = makeGrid({ preset: '1x2' });
    const payload = grid.getWorkspace();
    payload.layout.columnWeights = [1.5, 0.5];
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.layout().columnWeights).toEqual([1.5, 0.5]);
    expect(root.querySelector('.oac-grid__cells')!.style.gridTemplateColumns).toBe('minmax(0,1.5fr) 4px minmax(0,0.5fr)');
    expect(root.querySelector('.oac-grid__split')!.getAttribute('aria-valuenow')).toBe('75');
  });

  it('joins applied charts with every link off, so a linked grid cannot overwrite them', () => {
    const { grid } = makeGrid({ preset: '1x2', links: { symbol: true, interval: true } });
    const payload = grid.getWorkspace();
    payload.panes[0].symbol = 'LEFT';
    payload.panes[1].symbol = 'RIGHT';
    payload.panes[1].interval = '5m';
    payload.sync = { crosshair: false, viewport: false, symbol: false, interval: false };
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.cells().map(cell => [cell.widget.symbol(), cell.widget.interval()])).toEqual([['LEFT', '1m'], ['RIGHT', '5m']]);
  });

  it('keeps every price pane on top unless the grid opts in, and then carries a moved one to another grid that did', () => {
    const { grid: pinned } = makeGrid({ preset: '1x2' });
    expect(pinned.cells().map(cell => cell.widget.chart.movablePrimaryPane())).toEqual([false, false]);
    const { grid: source } = makeGrid({ preset: '1x2', movablePrimaryPane: true });
    expect(source.cells().map(cell => cell.widget.chart.movablePrimaryPane())).toEqual([true, true]);
    const chart = source.cells()[1].widget.chart;
    chart.addIndicator('rsi');
    expect(chart.setPrimaryPaneIndex(1)).toBe(true);
    const payload = parseWorkspacePayload(JSON.stringify(source.getWorkspace()));
    expect(payload.panes[1].chart).toMatchObject({ version: 2, primaryPane: 1 });
    // A grid that did not opt in refuses the moved chart and keeps its own.
    const refused = pinned.applyWorkspace(payload);
    expect(refused.applied).toBe(false);
    expect(refused.reason).toMatch(/movablePrimaryPane/);
    const { grid: target } = makeGrid({ preset: '1x2', movablePrimaryPane: true });
    expect(target.applyWorkspace(payload)).toEqual({ applied: true });
    expect(target.cells().map(cell => cell.widget.chart.primaryPaneIndex())).toEqual([0, 1]);
  });

  it('restores each chart drawing magnet and stay mode', () => {
    const { grid } = makeGrid({ preset: '1x2', rail: true });
    const payload = grid.getWorkspace();
    payload.panes[1].magnet = 'strong';
    payload.panes[1].stay = true;
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    const rails = grid.cells().map(cell => cell.widget.getState().rail);
    expect(rails.map(rail => [rail?.magnet, rail?.stay])).toEqual([['off', false], ['strong', true]]);
    expect(grid.getWorkspace().panes.map(pane => [pane.magnet, pane.stay])).toEqual([['off', false], ['strong', true]]);
  });

  it('says the active chart changed when a preset or an applied layout moves it', () => {
    const { grid } = makeGrid({ preset: '2x2' });
    grid.setActive(grid.cells()[3].id);
    const seen: string[] = [];
    grid.on('active', ({ id }) => seen.push(id));
    grid.setPreset('1x2');
    expect(seen).toEqual([grid.cells()[0].id]);
    grid.setPreset('2x2');
    expect(seen).toHaveLength(1);
    const payload = grid.getWorkspace();
    payload.panes = payload.panes.map((pane, i) => ({ ...pane, id: `n${i}` }));
    payload.layout.slots = payload.layout.slots.map((slot, i) => ({ ...slot, paneId: `n${i}` }));
    payload.activePaneId = 'n1';
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(seen).toEqual([seen[0], 'n1']);
  });
});

describe('chart grid history periods', () => {
  /** A feed function that records what each chart was built from and where its requests went. */
  function periodFeeds() {
    const built: Array<{ id: string; historyPeriod?: string }> = [];
    const asked: string[] = [];
    const feed = (chart: { readonly id: string; readonly historyPeriod?: string }): DataFeed => {
      built.push({ ...chart });
      return { getBars: async request => { asked.push(`${request.symbol}:${chart.historyPeriod ?? 'default'}`); return []; } };
    };
    return { feed, built, asked };
  }

  it('builds each chart feed from its saved period and writes the period back', async () => {
    const { feed, built, asked } = periodFeeds();
    const { grid } = makeGrid({ feed, preset: '1x2' });
    expect(built.map(chart => chart.historyPeriod)).toEqual([undefined, undefined]);
    const payload = grid.getWorkspace();
    expect(payload.panes.every(pane => !('historyPeriod' in pane))).toBe(true);
    payload.panes = [{ ...payload.panes[0], id: 'long', symbol: 'LLL', historyPeriod: '5y' }, { ...payload.panes[1], id: 'plain', symbol: 'PPP' }];
    payload.layout.slots = [{ ...payload.layout.slots[0], paneId: 'long' }, { ...payload.layout.slots[1], paneId: 'plain' }];
    payload.activePaneId = 'long';
    expect(grid.applyWorkspace(parseWorkspacePayload(JSON.stringify(payload)))).toEqual({ applied: true });
    await flush();
    expect(built.slice(2)).toEqual([{ id: 'long', historyPeriod: '5y' }, { id: 'plain', historyPeriod: undefined }]);
    expect(asked).toContain('LLL:5y');
    expect(asked).toContain('PPP:default');
    expect(grid.cells().map(cell => cell.historyPeriod)).toEqual(['5y', undefined]);
    const saved = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(saved.panes.map(pane => pane.historyPeriod)).toEqual(['5y', undefined]);
  });

  it('gives a chart a larger preset adds the active chart period with its instrument', () => {
    const { feed, built } = periodFeeds();
    const { grid } = makeGrid({ feed, preset: '1x1' });
    const payload = grid.getWorkspace();
    payload.panes[0].historyPeriod = '1y';
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    grid.setPreset('1x2');
    expect(grid.cells()[1].historyPeriod).toBe('1y');
    expect(built[built.length - 1]).toEqual({ id: grid.cells()[1].id, historyPeriod: '1y' });
  });

  it('refuses a period that is not text before any chart changes', () => {
    const { grid } = makeGrid({ preset: '1x1' });
    const before = grid.cells()[0].widget;
    const payload = grid.getWorkspace();
    (payload.panes[0] as unknown as { historyPeriod: unknown }).historyPeriod = 5;
    expect(grid.applyWorkspace(payload)).toEqual({ applied: false, reason: `${payload.panes[0].id}: invalid chart` });
    expect(grid.cells()[0].widget).toBe(before);
  });
});

describe('chart grid linked exchanges', () => {
  it('carries an exchange-only change to linked charts, so the saved desk restores whole', async () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ persist: 'desk', storage, preset: '1x2', links: { symbol: true } });
    const [leader, follower] = grid.cells().map(cell => cell.widget);
    leader.setSymbol('AAA', 'BSE');
    expect([follower.symbol(), follower.exchange()]).toEqual(['AAA', 'BSE']);
    follower.setSymbol('AAA', 'NSE');
    expect([leader.symbol(), leader.exchange()]).toEqual(['AAA', 'NSE']);
    leader.setSymbol('AAA', 'BSE');
    await flush();
    expect(stored(storage).panes.map(pane => pane.exchange)).toEqual(['BSE', 'BSE']);
    grid.destroy();
    const { grid: restored } = makeGrid({ persist: 'desk', storage, preset: '1x3' });
    expect(restored.cells().map(cell => `${cell.widget.symbol()}:${cell.widget.exchange()}`)).toEqual(['AAA:BSE', 'AAA:BSE']);
  });

  it('adopts the active chart exchange when symbol linking is switched on', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    grid.cells()[1].widget.setSymbol('AAA', 'BSE');
    grid.setActive(grid.cells()[0].id);
    grid.setLinks({ symbol: true });
    expect(grid.cells().map(cell => `${cell.widget.symbol()}:${cell.widget.exchange()}`)).toEqual(['AAA:NSE', 'AAA:NSE']);
    expect(grid.applyWorkspace(grid.getWorkspace())).toEqual({ applied: true });
  });

  it('adopts the active chart symbol and interval, not the last one changed, when linking is switched on', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    const widgets = grid.cells().map(cell => cell.widget);
    widgets[2].setSymbol('CCC');
    widgets[2].setInterval('5m');
    widgets[0].setSymbol('DDD');
    widgets[0].setInterval('15m');
    grid.setActive(grid.cells()[2].id);
    grid.setLinks({ symbol: true, interval: true });
    expect(widgets.map(widget => `${widget.symbol()} ${widget.interval()}`)).toEqual(['CCC 5m', 'CCC 5m', 'CCC 5m']);
  });
});

describe('chart grid persistence timing', () => {
  it('writes a discrete change in the same task, leaving no debounce for a reload to lose', async () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ persist: 'desk', storage, preset: '2x2' });
    await flush();
    expect(stored(storage).layout.columns).toBe(2);
    grid.setPreset('1x2');
    await flush();
    expect(stored(storage).panes).toHaveLength(2);
    grid.setLinks({ symbol: true });
    await flush();
    expect(stored(storage).sync.symbol).toBe(true);
    grid.cells()[1].widget.setSymbol('BBB');
    await flush();
    expect(stored(storage).panes.map(pane => pane.symbol)).toEqual(['BBB', 'BBB']);
  });

  it('flushes a pending save when the page hides, goes away or the grid is destroyed', async () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const doc = withWindow(fakeWidgetDocument());
    const { grid } = makeGrid({ persist: 'desk', storage, preset: '1x2' }, doc);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    vi.advanceTimersByTime(300);
    const from = (): number => (stored(storage).panes[0].chart as { viewport?: { from: number } }).viewport?.from ?? NaN;
    const pan = (at: number): void => grid.cells()[0].widget.chart.setVisibleLogicalRange({ from: at, to: at + 30 });
    pan(100);
    expect(from()).not.toBe(100);
    windowOf(doc).fire('pagehide');
    expect(from()).toBe(100);
    pan(120);
    (doc as unknown as { visibilityState: string }).visibilityState = 'hidden';
    fire(doc as unknown as FakeElement, 'visibilitychange');
    expect(from()).toBe(120);
    pan(140);
    grid.destroy();
    expect(from()).toBe(140);
  });
});

describe('chart grid restore failures', () => {
  it('keeps a saved desk it cannot restore, says why, and writes over it only after a real change', async () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ persist: 'desk', storage, preset: '1x2' });
    grid.cells()[0].widget.chart.addIndicator('ema', { period: 9 });
    grid.destroy();
    const payload = stored(storage);
    payload.panes[0].chart.indicators![0].indicatorId = 'registered-later';
    const text = JSON.stringify(payload);
    storage.map.set(SAVED, text);
    const { grid: fallback, root } = makeGrid({ persist: 'desk', storage, preset: '1x3' });
    expect(fallback.cells()).toHaveLength(3);
    expect(fallback.restored()).toMatchObject({ applied: false, reason: expect.stringMatching(/registered-later/) });
    expect(root.querySelector('.oac-toast__msg')?.textContent).toMatch(/could not be restored.*registered-later/);
    for (const cell of fallback.cells()) cell.widget.series.setData(bars(200));
    fallback.cells()[1].widget.chart.setVisibleLogicalRange({ from: 20, to: 60 });
    fallback.setActive(fallback.cells()[2].id);
    await flush();
    vi.advanceTimersByTime(1000);
    expect(storage.map.get(SAVED)).toBe(text);
    fallback.setPreset('1x2');
    await flush();
    expect(stored(storage).panes).toHaveLength(2);
  });

  it('reports what restoring did: nothing saved, or applied', () => {
    vi.useFakeTimers();
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ persist: 'desk', storage });
    expect(grid.restored()).toBeNull();
    grid.destroy();
    expect(makeGrid({ persist: 'desk', storage }).grid.restored()).toEqual({ applied: true });
  });
});

describe('chart grid keys that belong to the grid', () => {
  async function hovered(options: ChartGridOptions = {}, doc?: FakeDocument) {
    const made = makeGrid({ preset: '1x2', links: { viewport: false, crosshair: false }, ...options }, doc);
    const { grid, root } = made;
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    grid.setActive(grid.cells()[0].id);
    fire(root, 'pointerenter');
    fire(grid.cells()[0].widget.root as unknown as FakeElement, 'pointerenter');
    fire(chartEl(grid, 0), 'pointerenter');
    const range = (): { from: number; to: number } => grid.cells()[0].widget.chart.getVisibleLogicalRange();
    // The setup is live: with the focus on the page, an arrow pans the hovered active chart.
    const before = range();
    fireKey(made.doc.body, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(range()).not.toEqual(before);
    return { ...made, range };
  }

  it('keeps arrow keys on a focused splitter from the charts and from page listeners', async () => {
    const { grid, root, doc, range } = await hovered();
    const heard: string[] = [];
    doc.addEventListener('keydown', (e: { key: string }) => heard.push(e.key));
    const split = root.querySelector('.oac-grid__split')!;
    split.focus();
    const before = range();
    fireKey(split, 'ArrowRight', { code: 'ArrowRight' });
    expect(grid.layout().columnWeights[0]).toBeGreaterThan(1);
    expect(range()).toEqual(before);
    expect(heard).toEqual([]);
  });

  it('keeps arrow keys on a focused tab from the active chart under the pointer', async () => {
    FakeResizeObserver.all = [];
    const { root, range } = await hovered({}, withWindow(fakeWidgetDocument()));
    root.rect = { left: 0, top: 0, width: 420, height: 700 };
    FakeResizeObserver.fire(root);
    const tab = root.querySelectorAll('.oac-grid__tab')[0];
    tab.focus();
    const before = range();
    fireKey(tab, 'ArrowLeft', { code: 'ArrowLeft' });
    expect(range()).toEqual(before);
  });

  it('never goes compact when compactWidth is 0', () => {
    FakeResizeObserver.all = [];
    const { grid, root } = makeGrid({ preset: '2x2', compactWidth: 0 }, withWindow(fakeWidgetDocument()));
    root.rect = { left: 0, top: 0, width: 300, height: 700 };
    FakeResizeObserver.fire(root);
    expect(grid.compact()).toBe(false);
    expect(root.dataset.compact).toBe('false');
  });
});

describe('chart grid linked viewports across hidden charts', () => {
  it('brings a chart that was hidden onto the linked window when it is shown again', async () => {
    const { grid } = makeGrid({ preset: '1x3', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    // Compact: only the first chart has a plot, the others are zero wide.
    charts[1].applySize(0, 400);
    charts[2].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 30, to: 60 });
    charts[2].applySize(600, 400);
    expect(charts[2].getVisibleLogicalRange().from).toBeCloseTo(30, 6);
    expect(charts[2].getVisibleLogicalRange().to).toBeCloseTo(60, 6);
    // Wider again: every chart, the navigated one included, shows the same window.
    charts[0].applySize(900, 400);
    charts[1].applySize(900, 400);
    for (const chart of charts) {
      expect(chart.getVisibleLogicalRange().from).toBeCloseTo(30, 6);
      expect(chart.getVisibleLogicalRange().to).toBeCloseTo(60, 6);
    }
  });

  it('keeps a chart that fitted a new instrument on that view through a resize', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    requests[0].resolve(bars(200));
    await flush();
    charts[0].setVisibleLogicalRange({ from: 30, to: 60 });
    grid.cells()[1].widget.setSymbol('BBB');
    requests[requests.length - 1].resolve(bars(200, 400));
    await flush();
    const fitted = charts[1].getVisibleLogicalRange();
    expect(fitted.from).not.toBeCloseTo(30, 3);
    charts[1].applySize(700, 400);
    expect(charts[1].getVisibleLogicalRange().from).toBeCloseTo(fitted.from, 6);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(fitted.to, 6);
  });

  it('forgets the linked window when the chart holding it changes instrument, and only then', async () => {
    const { grid } = makeGrid({ preset: '1x3', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    const own = charts[2].getVisibleLogicalRange();
    charts[2].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 30, to: 60 });
    // The first chart's own new instrument, on its new bars, is no linked window.
    grid.cells()[0].widget.setSymbol('CCC');
    grid.cells()[0].widget.series.setData(bars(150, 400));
    charts[2].applySize(600, 400);
    expect(charts[2].getVisibleLogicalRange().to).toBeCloseTo(own.to, 6);
    charts[2].applySize(0, 400);
    await flush();
    charts[0].setVisibleLogicalRange({ from: 30, to: 60 });
    // Another chart's new instrument leaves the window the first chart still shows.
    grid.cells()[1].widget.setSymbol('BBB');
    grid.cells()[1].widget.series.setData(bars(150, 400));
    charts[2].applySize(600, 400);
    expect(charts[2].getVisibleLogicalRange().to).toBeCloseTo(60, 6);
  });

  it('keeps a chart whose first bars fitted its view on that view through a resize', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const [a, b] = grid.cells().map(cell => cell.widget.chart);
    grid.cells()[0].widget.series.setData(bars(200));
    await flush();
    a.setVisibleLogicalRange({ from: 30, to: 60 });
    // The second chart had no bars to follow the pan with, and was zoomed while
    // empty; its first bars fit its view afresh.
    b.setVisibleLogicalRange({ from: 0, to: 30 });
    grid.cells()[1].widget.series.setData(bars(200));
    const fitted = b.getVisibleLogicalRange();
    expect(fitted.to - fitted.from).not.toBeCloseTo(30, 3);
    b.applySize(700, 400);
    expect(b.getVisibleLogicalRange().from).toBeCloseTo(fitted.from, 6);
    expect(b.getVisibleLogicalRange().to).toBeCloseTo(fitted.to, 6);
  });

  it('keeps a chart whose first bars came through its feed after a linked pan on their span through a resize', async () => {
    // One feed per chart, so the second chart's history arrives on its own.
    const feeds = new Map<string, Pending[]>();
    const feed = ({ id }: { readonly id: string }): DataFeed => {
      const { feed: own, requests } = pendingFeed();
      feeds.set(id, requests);
      return own;
    };
    const { grid } = makeGrid({ feed, preset: '1x2', links: { viewport: true, crosshair: false } });
    const [first, second] = grid.cells();
    const [a, b] = [first.widget.chart, second.widget.chart];
    feeds.get(first.id)![0].resolve(bars(200));
    await flush();
    a.setVisibleLogicalRange({ from: 150, to: 190 });
    // A splitter drag while the second chart still waits for its history: it
    // keeps the span it showed empty, at a new bar width.
    b.applySize(700, 400);
    const empty = b.getVisibleLogicalRange();
    feeds.get(second.id)![0].resolve(bars(200));
    await flush();
    // Its first bars fit the default candle density, a span no event reported.
    const fitted = b.getVisibleLogicalRange();
    expect(fitted.to - fitted.from).not.toBeCloseTo(empty.to - empty.from, 3);
    b.applySize(600, 400);
    expect(b.getVisibleLogicalRange().from).toBeCloseTo(fitted.from, 6);
    expect(b.getVisibleLogicalRange().to).toBeCloseTo(fitted.to, 6);
  });

  it('leaves a resize to the engine until the linked charts share a window', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const chart = grid.cells()[0].widget.chart;
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    const before = chart.getVisibleLogicalRange(), spacing = chart.timeScale.barSpacing;
    chart.applySize(900, 400);
    // A wider chart shows more bars at the same bar width.
    expect(chart.timeScale.barSpacing).toBe(spacing);
    expect(chart.getVisibleLogicalRange().to).toBeCloseTo(before.to, 6);
    expect(chart.getVisibleLogicalRange().from).toBeLessThan(before.from - 10);
  });

  /** One more bar on every chart, the way a live feed appends it. */
  const tick = (grid: ChartGrid, index: number): void => {
    for (const cell of grid.cells()) cell.widget.series.update(bars(index + 1)[index]);
  };

  it('keeps a resized chart on the right edge while new bars arrive, in step with the others', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    charts[0].setVisibleLogicalRange({ from: 160, to: 203 });
    for (let i = 200; i < 210; i++) tick(grid, i);
    await flush();
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(213, 6);
    // A splitter drag resizes the first chart only.
    charts[0].applySize(700, 400);
    expect(charts[0].getVisibleLogicalRange().to).toBeCloseTo(213, 6);
    expect(charts[0].getVisibleLogicalRange().from).toBeCloseTo(charts[1].getVisibleLogicalRange().from, 6);
    tick(grid, 210);
    for (const chart of charts) expect(chart.getVisibleLogicalRange().to).toBeCloseTo(214, 6);
  });

  it('shows a hidden chart on the window the linked charts reached with new bars, not the last pan', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    charts[1].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 160, to: 203 });
    for (let i = 200; i < 210; i++) tick(grid, i);
    await flush();
    charts[1].applySize(600, 400);
    expect(charts[1].getVisibleLogicalRange().from).toBeCloseTo(170, 6);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(213, 6);
  });

  it('pulls no chart back to a window from before viewport linking was switched off and on', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    charts[0].setVisibleLogicalRange({ from: 30, to: 60 });
    grid.setLinks({ viewport: false });
    charts[1].setVisibleLogicalRange({ from: 120, to: 170 });
    charts[0].setVisibleLogicalRange({ from: 100, to: 150 });
    // Unlinked, a chart shown again keeps its own window.
    charts[1].applySize(0, 400);
    charts[1].applySize(600, 400);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(170, 6);
    charts[1].applySize(0, 400);
    grid.setLinks({ viewport: true });
    charts[0].applySize(700, 400);
    charts[1].applySize(600, 400);
    expect(charts[0].getVisibleLogicalRange().to).toBeCloseTo(150, 6);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(170, 6);
  });

  it('forgets the linked window when the chart it follows is removed', async () => {
    const { grid } = makeGrid({ preset: '1x3', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    const edge = charts[1].getVisibleLogicalRange().to;
    charts[1].applySize(0, 400);
    charts[2].setVisibleLogicalRange({ from: 160, to: 203 });
    grid.setPreset('1x2');
    for (let i = 200; i < 210; i++) tick(grid, i);
    charts[1].applySize(600, 400);
    // The removed chart's window is ten bars behind; the shown chart stays on its right edge.
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(edge + 10, 6);
  });

  it('shows the chart the window was read from on its own window, which followed new bars while hidden', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    for (const cell of grid.cells()) cell.widget.series.setData(bars(200));
    await flush();
    charts[0].setVisibleLogicalRange({ from: 160, to: 203 });
    charts[0].applySize(0, 400);
    for (let i = 200; i < 210; i++) tick(grid, i);
    charts[0].applySize(600, 400);
    expect(charts[0].getVisibleLogicalRange().to).toBeCloseTo(213, 6);
  });

  it('moves the linked window to a chart that takes it, so it follows the bars that chart receives', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    grid.cells()[0].widget.series.setData(bars(205));
    grid.cells()[1].widget.series.setData(bars(200));
    await flush();
    charts[1].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 160, to: 203 });
    // A tab switch: the first chart hides and the second, which ends five bars earlier, shows.
    charts[0].applySize(0, 400);
    charts[1].applySize(600, 400);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(203, 6);
    for (let i = 200; i < 210; i++) grid.cells()[1].widget.series.update(bars(i + 1)[i]);
    charts[1].applySize(0, 400);
    charts[0].applySize(600, 400);
    expect(charts[0].getVisibleLogicalRange().to).toBeCloseTo(213, 6);
  });

  it('keeps the linked window on what a refreshed chart shows, not on its bars before they were re-anchored', async () => {
    const { feed, requests } = pendingFeed();
    const { grid } = makeGrid({ feed, preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(cell => cell.widget.chart);
    requests[0].resolve(bars(200));
    await flush();
    charts[1].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 100, to: 150 });
    void grid.cells()[0].widget.reload();
    await flush();
    requests[requests.length - 1].resolve(bars(210));
    await flush();
    const shown = charts[0].getVisibleLogicalRange();
    charts[1].applySize(600, 400);
    expect(charts[1].getVisibleLogicalRange().from).toBeCloseTo(shown.from, 6);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(shown.to, 6);
  });
});
