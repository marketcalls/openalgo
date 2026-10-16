/**
 * The chart grid over an asynchronous store, the default since the widget's
 * storage moved to IndexedDB: the grid is built from its preset out of sight
 * and asks the feed for nothing until the store has answered, then opens the
 * saved desk (or loads the preset's charts) with the desk's chords, and a
 * write the store refuses is reported on the active chart's status line. A
 * desk an earlier release left in `localStorage` opens from IndexedDB.
 */
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { BarsRequest, DataFeed } from '../src/index';
import { SAVE_DEBOUNCE_MS, type ChartGrid, type ChartGridOptions } from '../src/widget/index';
import { ensureWindowGlobal, fire, type FakeElement } from './helpers/fake-dom-widget';
import { FakeAsyncStore, settle } from './helpers/fake-async-store';
import { FakeIndexedDb } from './helpers/fake-indexeddb';
import { MemoryStorage, makeGrid as buildGrid, walk } from './widget-grid-harness';

beforeAll(ensureWindowGlobal);

function recordingFeed(): { feed: DataFeed; asked: string[] } {
  const asked: string[] = [];
  const bars = walk(120, 640);
  return { asked, feed: { getBars: async (request: BarsRequest) => { asked.push(`${request.symbol} ${request.interval}`); return bars; } } };
}

const makeGrid = (options: ChartGridOptions = {}): ChartGrid => buildGrid(options).grid;
const visibility = (grid: ChartGrid): string => String((grid.root as unknown as FakeElement).style.visibility ?? '');
const CHORDS = 'oac-widget:desk:keymap';
const chords = (grid: ChartGrid): Array<string | null> => grid.cells().map(cell => cell.widget.context.keymap.chord('tool:trend-line'));

/** A desk saved over a synchronous store: two charts, the second on BBB and active, viewport links off, one chord moved. */
async function savedDesk(): Promise<MemoryStorage> {
  const sync = new MemoryStorage();
  const grid = makeGrid({ persist: 'desk', storage: sync, preset: '1x2', feed: recordingFeed().feed });
  grid.cells()[1].widget.setSymbol('BBB');
  grid.setActive(grid.cells()[1].id);
  grid.setLinks({ viewport: false });
  expect(grid.cells()[0].widget.context.keymap.rebind('tool:trend-line', 'Alt+Y').ok).toBe(true);
  await settle();
  grid.destroy();
  return sync;
}

async function asyncDesk(): Promise<FakeAsyncStore> {
  const store = new FakeAsyncStore();
  for (const [k, v] of (await savedDesk()).map) store.map.set(k, v);
  return store;
}

describe('the chart grid over an asynchronous store', () => {
  it('builds the preset out of sight asking for nothing, then opens the saved desk with its chords', async () => {
    const store = await asyncDesk();
    store.hold = true;
    const { feed, asked } = recordingFeed();
    const grid = makeGrid({ persist: 'desk', storage: store, feed, preset: '2x2' });
    await settle();
    expect(visibility(grid)).toBe('hidden');
    expect(grid.cells()).toHaveLength(4);
    expect(asked).toEqual([]);
    expect(grid.restored()).toBeNull();
    store.release();
    await grid.ready;
    await settle();
    expect(visibility(grid)).toBe('');
    expect(grid.restored()).toEqual({ applied: true });
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'BBB']);
    expect(grid.active().id).toBe(grid.cells()[1].id);
    expect(grid.linkOptions().viewport).toBe(false);
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
    // The desk's instruments alone: never the grid's AAA four times over.
    expect(asked.sort()).toEqual(['AAA 1m', 'BBB 1m']);
    // The grid's copy follows other tabs' changes while it lives, and lets go with it.
    expect(store.listeners.size).toBe(1);
    grid.destroy();
    expect(store.listeners.size).toBe(0);
  });

  it('gives the preset charts the desk chords and the grid instrument when the store holds no desk', async () => {
    const store = new FakeAsyncStore();
    store.map.set(CHORDS, JSON.stringify({ 'tool:trend-line': 'Alt+y' }));
    store.hold = true;
    const { feed, asked } = recordingFeed();
    const grid = makeGrid({ persist: 'desk', storage: store, feed, preset: '1x2' });
    await settle();
    expect(asked).toEqual([]);
    expect(chords(grid)).toEqual(['Alt+t', 'Alt+t']);
    store.hold = false;
    store.release();
    await grid.ready;
    await settle();
    expect(grid.restored()).toBeNull();
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'AAA']);
    // One request for both charts on one instrument, as over a synchronous store.
    expect(asked).toEqual(['AAA 1m']);
    expect(grid.cells().map(cell => cell.widget.series.getData().length)).toEqual([120, 120]);
    // The preset desk is written once it holds its charts' instrument, and the
    // chords it read are not written back.
    await vi.waitFor(() => expect(JSON.parse(store.map.get('oac-widget:desk:grid') ?? '{}').panes?.map((pane: { symbol: string }) => pane.symbol)).toEqual(['AAA', 'AAA']));
    expect(store.writes().filter(call => call.includes(CHORDS))).toEqual([]);
  });

  it('writes nothing before the store answers, and keeps a desk it cannot restore', async () => {
    vi.useFakeTimers();
    const store = new FakeAsyncStore();
    const refused = JSON.stringify({ layout: 7 });
    store.map.set('oac-widget:desk:grid', refused);
    store.hold = true;
    const grid = makeGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    grid.setLinks({ crosshair: false });
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 4);
    expect(store.writes()).toEqual([]);
    store.hold = false;
    store.release();
    await grid.ready;
    expect(grid.restored()?.applied).toBe(false);
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS * 4);
    expect(store.map.get('oac-widget:desk:grid')).toBe(refused);
    expect(grid.cells()).toHaveLength(2);
  });

  it('keeps a workspace the host applied before the store answered, and writes it', async () => {
    const store = await asyncDesk();
    store.hold = true;
    const grid = makeGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    const handed = grid.getWorkspace();
    handed.panes.forEach(pane => { pane.symbol = 'CCC'; });
    handed.layout.preset = 'handed';
    expect(grid.applyWorkspace(handed)).toEqual({ applied: true });
    store.hold = false;
    store.release();
    await grid.ready;
    await settle();
    expect(grid.restored()).toBeNull();
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['CCC', 'CCC']);
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
    await vi.waitFor(() => expect(JSON.parse(store.map.get('oac-widget:desk:grid')!).layout.preset).toBe('handed'));
  });

  it('puts a write the store refused on the active chart status line', async () => {
    vi.useFakeTimers();
    const store = new FakeAsyncStore();
    const grid = makeGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    await grid.ready;
    const statuses: string[] = [];
    grid.active().widget.on('status', e => statuses.push(`${e.kind} ${e.text}`));
    store.failWrites = new Error('quota exceeded');
    grid.cells()[0].widget.setSymbol('CCC');
    await vi.advanceTimersByTimeAsync(SAVE_DEBOUNCE_MS + 10);
    expect(statuses).toContain('error Saved chart settings could not be written: quota exceeded');
  });

  it('opens the preset and raises a toast when the store cannot be read', async () => {
    const store = new FakeAsyncStore();
    store.failEntries = new Error('the database is gone');
    const { feed, asked } = recordingFeed();
    const grid = makeGrid({ persist: 'desk', storage: store, feed, preset: '1x2' });
    await grid.ready;
    await settle();
    expect(asked).toEqual(['AAA 1m']);
    const toast = (grid.root as unknown as FakeElement).querySelector('.oac-toast__msg');
    expect(toast?.textContent).toBe('Saved chart settings could not be read, so changes are kept for this session only: the database is gone');
    // Nothing is written over a store that could not be read.
    grid.cells()[0].widget.setSymbol('CCC');
    await settle();
    expect(store.writes()).toEqual([]);
  });

  it('journals and sends what is pending when the page hides, and when it is destroyed', async () => {
    const store = new FakeAsyncStore();
    const journal = new MemoryStorage();
    store.journal = journal;
    const { grid, doc } = buildGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    await grid.ready;
    await settle();
    const before = store.writes().length;
    // A pan waits for the debounce; hiding the page writes it at once, and
    // journals it, since the store may not answer before the page goes.
    grid.cells()[0].widget.chart.emit('pan', {});
    Object.assign(doc, { visibilityState: 'hidden' });
    fire(doc, 'visibilitychange');
    expect(journal.map.has('oac-widget-journal:desk')).toBe(true);
    await settle();
    expect(store.writes().length).toBeGreaterThan(before);
    expect(journal.map.has('oac-widget-journal:desk')).toBe(false);
    const hidden = store.writes().length;
    grid.cells()[1].widget.setSymbol('DDD');
    grid.destroy();
    expect(journal.map.get('oac-widget-journal:desk')).toContain('DDD');
    await settle();
    expect(store.writes().slice(hidden).some(call => call.includes('DDD'))).toBe(true);
  });

  it('writes nothing when the page hides with no change pending, so a desk another tab saved stays', async () => {
    const store = new FakeAsyncStore();
    const { grid, doc } = buildGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    await grid.ready;
    // The first loads' own saves, past the debounce.
    await new Promise(resolve => setTimeout(resolve, SAVE_DEBOUNCE_MS + 20));
    await settle();
    // Another tab on the same desk saves a newer one, then this tab is left for it.
    const newer = JSON.stringify({ ...grid.getWorkspace(), activePaneId: grid.cells()[1].id });
    store.external('oac-widget:desk:grid', newer);
    Object.assign(doc, { visibilityState: 'hidden' });
    fire(doc, 'visibilitychange');
    await settle();
    expect(store.map.get('oac-widget:desk:grid')).toBe(newer);
  });

  it('keeps a synchronous store the host passes: the desk is back before createChartGrid returns', async () => {
    const sync = await savedDesk();
    const grid = makeGrid({ persist: 'desk', storage: sync, feed: recordingFeed().feed });
    expect(visibility(grid)).toBe('');
    expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'BBB']);
    expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
    await grid.ready;
  });
});

/** A synchronous store at its quota: every write throws until `full` is cleared, the way `localStorage` does. */
class FullStorage extends MemoryStorage {
  public full = false;
  public override setItem(k: string, v: string): void {
    if (this.full) throw new Error('QuotaExceededError');
    super.setItem(k, v);
  }
}

describe('the chart grid over a synchronous store', () => {
  it('says on the active chart that a refused save lost the desk, once per run of refusals', async () => {
    const store = new FullStorage();
    const grid = makeGrid({ persist: 'desk', storage: store, feed: recordingFeed().feed, preset: '1x2' });
    await grid.ready;
    await settle();
    const statuses: string[] = [];
    for (const cell of grid.cells()) cell.widget.on('status', e => { if (e.kind === 'error') statuses.push(e.text); });
    store.full = true;
    grid.cells()[0].widget.setSymbol('CCC');
    await settle();
    expect(statuses).toEqual(['The chart layout could not be saved']);
    // Still full: the next refused save is the same failure, not a new one to say.
    grid.cells()[1].widget.setSymbol('DDD');
    await settle();
    expect(statuses).toHaveLength(1);
    // A save that lands ends the run, so the next refusal is said again.
    store.full = false;
    grid.setPreset('1x1');
    await settle();
    expect(store.map.get('oac-widget:desk:grid')).toContain('"CCC"');
    store.full = true;
    grid.setPreset('1x2');
    await settle();
    expect(statuses).toEqual(['The chart layout could not be saved', 'The chart layout could not be saved']);
  });
});

class PageStorage extends MemoryStorage {
  public get length(): number { return this.map.size; }
  public key(i: number): string | null { return [...this.map.keys()][i] ?? null; }
  public clear(): void { this.map.clear(); }
}

describe('the chart grid default store', () => {
  it('uses IndexedDB when the page has it, opening a desk 2.5.9 saved in localStorage', async () => {
    const g = globalThis as { indexedDB?: unknown; localStorage?: unknown };
    const db = new FakeIndexedDb();
    const page = new PageStorage();
    // What 2.5.9 left: the desk, its drawings and the chords, under the grid's namespace in the page's storage.
    for (const [k, v] of (await savedDesk()).map) page.setItem(k, v);
    g.indexedDB = db;
    g.localStorage = page;
    try {
      const { feed, asked } = recordingFeed();
      const grid = makeGrid({ persist: 'desk', feed });
      expect(grid.restored()).toBeNull();
      await grid.ready;
      await settle();
      expect(grid.restored()).toEqual({ applied: true });
      expect(grid.cells().map(cell => cell.widget.symbol())).toEqual(['AAA', 'BBB']);
      expect(chords(grid)).toEqual(['Alt+y', 'Alt+y']);
      expect(asked.sort()).toEqual(['AAA 1m', 'BBB 1m']);
      const records = db.records('openalgo-charts-widget');
      // Copied in once; the chords read are not written back.
      expect(records.get(CHORDS)).toBe(page.getItem(CHORDS));
      grid.cells()[0].widget.setSymbol('EEE');
      grid.destroy();
      await settle();
      expect(JSON.parse(records.get('oac-widget:desk:grid') as string).panes[0].symbol).toBe('EEE');
      // The old copy stays as the earlier release left it, for going back to it.
      expect(JSON.parse(page.getItem('oac-widget:desk:grid')!).panes[0].symbol).toBe('AAA');
    } finally {
      delete g.indexedDB;
      delete g.localStorage;
    }
  });
});
