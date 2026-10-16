/**
 * Working with the grid's charts as places: maximize and restore, swapping
 * two charts, the grid's chords on the active chart's keymap, dragging a
 * chart by its bar onto another's place, and the dense cells a many-chart
 * layout makes.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/index';
import '../src/indicators/index';
import { parseWorkspacePayload } from '../src/workspace/index';
import type { ChartGrid } from '../src/widget/index';
import { ensureWindowGlobal, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';
import { FakeResizeObserver, MemoryStorage, chartEl, el, flush, makeGrid, topbar, walk, withWindow } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

const hidden = (grid: ChartGrid): boolean[] => grid.cells().map(c => el(c.element).hidden);
const symbols = (grid: ChartGrid): string[] => grid.cells().map(c => c.widget.symbol());
/** Lay the cells out on a 1200 by 800 page so a pointer can land on one. */
function place(grid: ChartGrid): void {
  const spec = grid.layout();
  const w = 1200 / spec.columns, h = 800 / spec.rows;
  for (const c of grid.cells()) el(c.element).rect = { left: c.column * w, top: c.row * h, width: c.columnSpan * w, height: c.rowSpan * h };
}

describe('chart grid maximize and restore', () => {
  it('shows the active chart alone with every other chart alive, and restores the grid', () => {
    const { grid, root } = makeGrid({ preset: '2x2' });
    const reasons: string[] = [];
    grid.on('layout', ({ reason }) => reasons.push(reason));
    const widgets = grid.cells().map(c => c.widget);
    grid.setActive(grid.cells()[2].id);
    expect(grid.maximize()).toBe(true);
    expect(grid.maximized()).toBe(grid.cells()[2].id);
    expect(root.dataset.maximized).toBe('true');
    expect(hidden(grid)).toEqual([true, true, false, true]);
    expect(root.querySelectorAll('.oac-grid__split').every(s => s.hidden)).toBe(true);
    // Tabs switch the chart shown, as they do at the compact width.
    const tabs = root.querySelectorAll('.oac-grid__tab');
    expect(tabs).toHaveLength(4);
    tabs[1].click();
    expect(grid.maximized()).toBe(grid.cells()[1].id);
    expect(hidden(grid)).toEqual([true, false, true, true]);
    expect(widgets.every(w => !w.isDestroyed)).toBe(true);
    grid.restore();
    expect(grid.maximized()).toBeNull();
    expect(hidden(grid)).toEqual([false, false, false, false]);
    expect(el(root.querySelector('.oac-grid__tabs')).hidden).toBe(true);
    expect(reasons).toEqual(['maximize', 'maximize']);
    grid.restore();
    expect(reasons).toHaveLength(2);
  });

  it('walks the tabs of a maximized grid with the arrows, Home and End, one tab stop for the row', () => {
    const { grid, root, doc } = makeGrid({ preset: '2x2' });
    grid.maximize(grid.cells()[1].id);
    const tabs = (): FakeElement[] => root.querySelectorAll('.oac-grid__tab');
    expect(tabs().map(t => t.getAttribute('tabindex'))).toEqual(['-1', '0', '-1', '-1']);
    tabs()[1].focus();
    fireKey(doc.activeElement, 'ArrowRight');
    expect(grid.maximized()).toBe(grid.cells()[2].id);
    expect(doc.activeElement).toBe(tabs()[2]);
    expect(tabs().map(t => t.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true', 'false']);
    fireKey(doc.activeElement, 'End');
    expect(grid.maximized()).toBe(grid.cells()[3].id);
    fireKey(doc.activeElement, 'ArrowRight');
    expect(grid.maximized()).toBe(grid.cells()[0].id);
    expect(doc.activeElement).toBe(tabs()[0]);
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(grid.maximized()).toBe(grid.cells()[3].id);
    fireKey(doc.activeElement, 'Home');
    expect(grid.maximized()).toBe(grid.cells()[0].id);
    expect(tabs().map(t => t.getAttribute('tabindex'))).toEqual(['0', '-1', '-1', '-1']);
  });

  it('maximizes a named chart, and refuses an unknown one or a grid of one', () => {
    const { grid } = makeGrid({ preset: '1x3' });
    expect(grid.maximize('nope')).toBe(false);
    expect(grid.maximize(grid.cells()[1].id)).toBe(true);
    expect(grid.active().id).toBe(grid.cells()[1].id);
    grid.setPreset('1x1');
    expect(grid.maximized()).toBeNull();
    expect(grid.maximize()).toBe(false);
  });

  it('is a view, not a layout: a preset, an applied desk and the saved payload all see the grid', () => {
    const { grid, root } = makeGrid({ preset: '2x2' });
    grid.maximize(grid.cells()[3].id);
    const payload = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(payload.layout.slots).toHaveLength(4);
    expect(grid.applyWorkspace(payload)).toEqual({ applied: true });
    expect(grid.maximized()).toBeNull();
    expect(root.dataset.maximized).toBe('false');
    expect(hidden(grid)).toEqual([false, false, false, false]);
    grid.maximize();
    grid.setPreset('1x3');
    expect(grid.maximized()).toBeNull();
    expect(hidden(grid)).toEqual([false, false, false]);
  });

  it('brings a chart hidden behind the maximized one back onto its group window', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: true, crosshair: false } });
    const charts = grid.cells().map(c => c.widget.chart);
    for (const c of grid.cells()) c.widget.series.setData(walk(200));
    await flush();
    grid.maximize(grid.cells()[0].id);
    // The hidden chart has no plot; the maximized one is navigated meanwhile.
    charts[1].applySize(0, 400);
    charts[0].setVisibleLogicalRange({ from: 40, to: 90 });
    grid.restore();
    charts[1].applySize(600, 400);
    expect(charts[1].getVisibleLogicalRange().from).toBeCloseTo(40, 6);
    expect(charts[1].getVisibleLogicalRange().to).toBeCloseTo(90, 6);
  });
});

describe('chart grid swap', () => {
  it('trades the places of two charts of different sizes without rebuilding either', () => {
    const { grid, root } = makeGrid({ preset: '1x1' });
    grid.setPreset('left-3');
    grid.cells().forEach((c, i) => c.widget.setSymbol(['BIG', 'ONE', 'TWO', 'SIX'][i]));
    const created = vi.spyOn(Chart.prototype, 'addSeries');
    const reasons: string[] = [];
    grid.on('layout', ({ reason }) => reasons.push(reason));
    const big = grid.cells()[0], two = grid.cells()[2];
    expect(grid.swap(big.id, two.id)).toBe(true);
    expect(created).not.toHaveBeenCalled();
    // Reading order follows the places: the small chart now fills the large slot.
    expect(symbols(grid)).toEqual(['TWO', 'ONE', 'BIG', 'SIX']);
    expect(grid.cells()[0]).toMatchObject({ id: two.id, row: 0, column: 0, rowSpan: 3 });
    expect(grid.cells()[2]).toMatchObject({ id: big.id, row: 1, column: 1, rowSpan: 1 });
    expect(el(grid.cells()[0].element).style.gridArea).toBe('1 / 1 / 6 / 2');
    expect(grid.cells().map(c => el(c.element).getAttribute('aria-label'))).toEqual(['Chart 1', 'Chart 2', 'Chart 3', 'Chart 4']);
    const saved = parseWorkspacePayload(JSON.stringify(grid.getWorkspace()));
    expect(saved.layout.slots.find(s => s.paneId === two.id)).toMatchObject({ row: 0, column: 0, rowSpan: 3, columnSpan: 1 });
    expect(saved.layout.preset).toBe('left-3');
    expect(reasons).toEqual(['swap']);
    expect(root.querySelectorAll('.oac-grid__cell')).toHaveLength(4);
  });

  it('keeps the page order the reading order, which Tab and a screen reader follow, after a swap and an uneven layout', () => {
    const { grid, root } = makeGrid({ preset: '2x2' });
    const inPage = (): string[] => root.querySelectorAll('.oac-grid__cell').map(node => node.dataset.paneId as string);
    const [a, , , d] = grid.cells();
    grid.swap(a.id, d.id);
    expect(inPage()).toEqual(grid.cells().map(c => c.id));
    expect(inPage()[0]).toBe(d.id);
    // The active chart takes the large slot first in reading order, and first in the page.
    grid.setActive(grid.cells()[2].id);
    grid.setPreset('left-3');
    expect(grid.cells()[0].id).toBe(grid.active().id);
    expect(inPage()).toEqual(grid.cells().map(c => c.id));
  });

  it('refuses an unknown chart or a chart with itself', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const [a] = grid.cells();
    expect(grid.swap(a.id, 'nope')).toBe(false);
    expect(grid.swap(a.id, a.id)).toBe(false);
  });
});

describe('chart grid chords', () => {
  async function focused(preset: Parameters<ChartGrid['setPreset']>[0], index: number) {
    const made = makeGrid({ preset, links: { viewport: false, crosshair: false } });
    for (const c of made.grid.cells()) c.widget.series.setData(walk(120));
    await flush();
    made.grid.setActive(made.grid.cells()[index].id, { focus: true });
    return made;
  }

  it('maximizes and restores the active chart with Alt+Enter, and restores with Escape', async () => {
    const { grid, doc } = await focused('2x2', 1);
    const key = fireKey(doc.activeElement, 'Enter', { altKey: true });
    expect(key.defaultPrevented).toBe(true);
    expect(grid.maximized()).toBe(grid.cells()[1].id);
    fireKey(doc.activeElement, 'Enter', { altKey: true });
    expect(grid.maximized()).toBeNull();
    grid.maximize();
    // A tool in hand takes the first Escape; the grid is restored by the next.
    grid.cells()[1].widget.draw.setTool('trend-line');
    fireKey(doc.activeElement, 'Escape');
    expect(grid.cells()[1].widget.draw.activeTool()).toBeNull();
    expect(grid.maximized()).toBe(grid.cells()[1].id);
    fireKey(doc.activeElement, 'Escape');
    expect(grid.maximized()).toBeNull();
    // Escape on a grid that is not maximized is not the grid's.
    expect(fireKey(doc.activeElement, 'Escape').defaultPrevented).toBe(false);
  });

  it('moves to the neighbouring chart with Alt+Shift and an arrow, a spanning chart reaching the nearest', async () => {
    const { grid, doc } = await focused('left-3', 0);
    const at = (): number => grid.cells().findIndex(c => c.id === grid.active().id);
    const press = async (key: string): Promise<void> => { fireKey(doc.activeElement, key, { altKey: true, shiftKey: true }); await flush(); };
    await press('ArrowRight');
    expect(at()).toBe(1);
    expect(doc.activeElement).toBe(chartEl(grid, 1));
    // One step per press: the chart made active does not take the same key again.
    await press('ArrowDown');
    expect(at()).toBe(2);
    await press('ArrowLeft');
    expect(at()).toBe(0);
    // Nothing to the left of the first column: declined, so the key goes on to the page.
    expect(fireKey(doc.activeElement, 'ArrowLeft', { altKey: true, shiftKey: true }).defaultPrevented).toBe(false);
    expect(at()).toBe(0);
  });

  it('swaps the active chart with its neighbour with Ctrl and Shift and an arrow, the chart keeping the focus', async () => {
    const { grid, doc } = await focused('2x2', 0);
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB', 'CCC', 'DDD'][i]));
    const moving = grid.active().id;
    fireKey(doc.activeElement, 'ArrowRight', { ctrlKey: true, shiftKey: true });
    expect(symbols(grid)).toEqual(['BBB', 'AAA', 'CCC', 'DDD']);
    expect(grid.active().id).toBe(moving);
    fireKey(doc.activeElement, 'ArrowDown', { metaKey: true, shiftKey: true });
    expect(symbols(grid)).toEqual(['BBB', 'DDD', 'CCC', 'AAA']);
    // One chart on screen: nothing to swap with in view, so the chord is declined.
    grid.maximize();
    expect(fireKey(doc.activeElement, 'ArrowLeft', { ctrlKey: true, shiftKey: true }).defaultPrevented).toBe(false);
    expect(symbols(grid)).toEqual(['BBB', 'DDD', 'CCC', 'AAA']);
  });

  it('answers only on the active chart, with the pointer over another', async () => {
    const { grid, doc } = await focused('1x2', 0);
    fire(el(grid.cells()[1].widget.root), 'pointerenter');
    fire(chartEl(grid, 1), 'pointerenter');
    fireKey(doc.activeElement, 'Enter', { altKey: true });
    expect(grid.maximized()).toBe(grid.cells()[0].id);
  });

  it('lists its chords in a Chart grid section and collides with no chord of the widget or the engine', () => {
    const { grid } = makeGrid({ preset: '2x2', rail: true });
    for (const cell of grid.cells()) {
      const km = cell.widget.context.keymap;
      const section = km.describe().find(g => g.group === 'Chart grid');
      expect(section?.rows.map(r => r.combo)).toEqual([
        'Alt+Enter', 'Escape', 'Alt+Shift+ArrowLeft', 'Mod+Shift+ArrowLeft', 'Alt+Shift+ArrowRight', 'Mod+Shift+ArrowRight',
        'Alt+Shift+ArrowUp', 'Mod+Shift+ArrowUp', 'Alt+Shift+ArrowDown', 'Mod+Shift+ArrowDown',
      ]);
      const mine = new Set(section?.rows.map(r => r.combo));
      expect(km.conflicts().filter(c => mine.has(c.combo))).toEqual([]);
    }
  });

  it('takes its chords away with a chart the grid drops', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    const km = grid.cells()[1].widget.context.keymap;
    grid.setPreset('1x1');
    expect(km.list().filter(b => b.group === 'Chart grid')).toEqual([]);
  });
});

describe('chart grid shared chords', () => {
  const KEY = 'oac-widget:desk:keymap';
  const chords = (grid: ChartGrid): Array<string | null> => grid.cells().map(c => c.widget.context.keymap.chord('tool:trend-line'));

  it('moves a chord the user changed in one chart in every chart, keeps it for the desk, and resets it everywhere', () => {
    const storage = new MemoryStorage();
    const { grid } = makeGrid({ preset: '1x2', persist: 'desk', storage });
    const [first, second] = grid.cells();
    expect(second.widget.context.keymap.rebind('tool:trend-line', 'Alt+Y').ok).toBe(true);
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
    expect(JSON.parse(storage.map.get(KEY)!)).toEqual({ 'tool:trend-line': 'Alt+y' });
    // A chart a preset adds takes the desk's chords too.
    grid.setPreset('1x3');
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y', 'Alt+y']);
    // A new grid on the same store opens with them.
    const again = makeGrid({ preset: '1x2', persist: 'desk', storage }).grid;
    expect(chords(again)).toEqual(['Alt+y', 'Alt+y']);
    again.destroy();
    first.widget.context.keymap.resetAll();
    expect(chords(grid)).toEqual(['Alt+t', 'Alt+t', 'Alt+t']);
    expect(storage.map.has(KEY)).toBe(false);
  });

  it('shares nothing when the shortcuts editor is off', () => {
    const storage = new MemoryStorage();
    storage.setItem(KEY, JSON.stringify({ 'tool:trend-line': 'Alt+y' }));
    const { grid } = makeGrid({ preset: '1x2', persist: 'desk', storage, shortcutsEditor: false });
    expect(chords(grid)).toEqual(['Alt+t', 'Alt+t']);
  });
});

describe('chart grid dragging a chart by its bar', () => {
  const press = (target: FakeElement, x: number, y: number) => fire(target, 'pointerdown', { button: 0, clientX: x, clientY: y, pointerId: 7 });
  const move = (target: FakeElement, x: number, y: number) => fire(target, 'pointermove', { clientX: x, clientY: y, pointerId: 7 });
  const release = (target: FakeElement, x: number, y: number) => fire(target, 'pointerup', { clientX: x, clientY: y, pointerId: 7 });

  it('drops a chart onto another place, marking the target while it moves', () => {
    const { grid, root } = makeGrid({ preset: '2x2' });
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB', 'CCC', 'DDD'][i]));
    place(grid);
    const reasons: string[] = [];
    grid.on('layout', ({ reason }) => reasons.push(reason));
    const head = topbar(grid, 0);
    press(head, 100, 20);
    move(head, 103, 21);
    // Under the threshold nothing is dragging yet.
    expect(root.dataset.dragging).toBeUndefined();
    move(head, 900, 600);
    expect(root.getAttribute('data-dragging')).toBe('true');
    expect(el(grid.cells()[0].element).getAttribute('data-dragging')).toBe('true');
    expect(el(grid.cells()[3].element).getAttribute('data-drop')).toBe('true');
    move(head, 900, 100);
    expect(el(grid.cells()[3].element).getAttribute('data-drop')).toBeNull();
    expect(el(grid.cells()[1].element).getAttribute('data-drop')).toBe('true');
    release(head, 900, 100);
    expect(symbols(grid)).toEqual(['BBB', 'AAA', 'CCC', 'DDD']);
    expect(root.getAttribute('data-dragging')).toBeNull();
    expect(grid.cells().every(c => el(c.element).getAttribute('data-drop') === null && el(c.element).getAttribute('data-dragging') === null)).toBe(true);
    expect(reasons).toEqual(['swap']);
  });

  it('leaves a press on a control of the bar to the control, and a short press to a click', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    place(grid);
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB'][i]));
    const pill = topbar(grid, 0).querySelector('.oac-pills button')!;
    press(pill, 100, 20);
    move(pill, 900, 300);
    release(pill, 900, 300);
    expect(symbols(grid)).toEqual(['AAA', 'BBB']);
    const head = topbar(grid, 0);
    press(head, 100, 20);
    release(head, 102, 20);
    expect(symbols(grid)).toEqual(['AAA', 'BBB']);
  });

  it('drops the drag where it started on Escape or a cancelled pointer', () => {
    const { grid, doc, root } = makeGrid({ preset: '1x2' });
    place(grid);
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB'][i]));
    const head = topbar(grid, 0);
    press(head, 100, 20);
    move(head, 900, 300);
    const key = fireKey(doc.body, 'Escape');
    expect(key.defaultPrevented).toBe(true);
    expect(root.getAttribute('data-dragging')).toBeNull();
    release(head, 900, 300);
    expect(symbols(grid)).toEqual(['AAA', 'BBB']);
    press(head, 100, 20);
    move(head, 900, 300);
    fire(head, 'pointercancel', { pointerId: 7 });
    release(head, 900, 300);
    expect(symbols(grid)).toEqual(['AAA', 'BBB']);
  });

  it('does not drag while the grid shows one chart, and a double click on the bar maximizes and restores', () => {
    const { grid } = makeGrid({ preset: '1x2' });
    place(grid);
    grid.cells().forEach((c, i) => c.widget.setSymbol(['AAA', 'BBB'][i]));
    const head = topbar(grid, 1);
    fire(head, 'dblclick');
    expect(grid.maximized()).toBe(grid.cells()[1].id);
    press(head, 900, 20);
    move(head, 100, 300);
    release(head, 100, 300);
    expect(symbols(grid)).toEqual(['AAA', 'BBB']);
    fire(head, 'dblclick');
    expect(grid.maximized()).toBeNull();
    // A double click on a control is the control's.
    fire(topbar(grid, 1).querySelector('.oac-pills button')!, 'dblclick');
    expect(grid.maximized()).toBeNull();
  });
});

describe('chart grid maximize keeps what the chart shows', () => {
  it('keeps the maximized chart on its window as it grows and as it shrinks back, with no viewport link', async () => {
    const { grid } = makeGrid({ preset: '1x2', links: { viewport: false, crosshair: false } });
    const chart = grid.cells()[0].widget.chart;
    for (const c of grid.cells()) c.widget.series.setData(walk(200));
    await flush();
    chart.setVisibleLogicalRange({ from: 120, to: 180 });
    grid.maximize(grid.cells()[0].id);
    // The page lays the chart out over the whole grid; its window stays the one the user was reading.
    chart.applySize(1200, 800);
    expect(chart.getVisibleLogicalRange().from).toBeCloseTo(120, 6);
    expect(chart.getVisibleLogicalRange().to).toBeCloseTo(180, 6);
    grid.restore();
    chart.applySize(600, 400);
    expect(chart.getVisibleLogicalRange().from).toBeCloseTo(120, 6);
    // A later resize of the page is the engine's own again: the hold lasts one resize.
    chart.applySize(900, 400);
    expect(chart.getVisibleLogicalRange().to - chart.getVisibleLogicalRange().from).toBeGreaterThan(80);
  });
});

describe('chart grid dense cells', () => {
  it('gives a maximized chart its full chrome back, and marks it dense again on restore', () => {
    const doc = withWindow();
    const { grid, root } = makeGrid({ preset: '2x2' }, doc);
    const small = { left: 0, top: 0, width: 400, height: 300 }, whole = { left: 0, top: 0, width: 1200, height: 800 };
    for (const c of grid.cells()) {
      // What a browser does: the maximized cell takes the grid's whole area.
      Object.defineProperty(el(c.element), 'rect', { configurable: true, get: () => (root.dataset.maximized === 'true' && !el(c.element).hidden ? whole : small) });
    }
    root.rect = whole;
    FakeResizeObserver.fire(root);
    expect(grid.cells().map(c => el(c.element).dataset.dense)).toEqual(['true', 'true', 'true', 'true']);
    grid.maximize(grid.cells()[1].id);
    expect(el(grid.cells()[1].element).dataset.dense).toBe('false');
    grid.restore();
    expect(el(grid.cells()[1].element).dataset.dense).toBe('true');
  });


  it('marks a cell dense below the size a full bar and rail fit, and clears it when the cell grows', () => {
    const doc = withWindow();
    const { grid, root } = makeGrid({ preset: '1x2' }, doc);
    const [a, b] = grid.cells().map(c => el(c.element));
    a.rect = { left: 0, top: 0, width: 700, height: 500 };
    b.rect = { left: 700, top: 0, width: 400, height: 500 };
    root.rect = { left: 0, top: 0, width: 1100, height: 500 };
    FakeResizeObserver.fire(root);
    expect([a.dataset.dense, b.dataset.dense]).toEqual(['false', 'true']);
    b.rect = { left: 700, top: 0, width: 700, height: 300 };
    FakeResizeObserver.fire(root);
    expect(b.dataset.dense).toBe('true');
    b.rect = { left: 700, top: 0, width: 700, height: 500 };
    FakeResizeObserver.fire(root);
    expect(b.dataset.dense).toBe('false');
  });
});
