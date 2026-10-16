import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { mountWatchlistPanel, type WatchlistPanelOptions } from '../src/widget/watchlist-panel';
import { createOverlayStack, WidgetBus, WidgetStorage, type WidgetContext } from '../src/widget/context';
import {
  WatchlistRepository, WatchlistConflictError, createMemoryWatchlistStorage, type WatchlistStore, type WatchlistStorage,
} from '../src/workspace/index';
import type { InstrumentKey, QuoteFeed, QuoteSnapshot, QuoteStreamHandlers } from '../src/feed/types';
import { fakeWidgetDocument, fakeContainer, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

const nse = (symbol: string): InstrumentKey => ({ symbol, exchange: 'NSE' });
const flush = async () => {
  if (vi.isFakeTimers()) { await vi.advanceTimersByTimeAsync(0); return; }
  for (let i = 0; i < 6; i++) await new Promise(resolve => setTimeout(resolve, 0));
};

class FakeObserver {
  static last: FakeObserver | null = null;
  readonly observed = new Set<FakeElement>();
  constructor(private readonly callback: (entries: Array<{ target: FakeElement; isIntersecting: boolean }>) => void) { FakeObserver.last = this; }
  observe(target: FakeElement) { this.observed.add(target); }
  unobserve(target: FakeElement) { this.observed.delete(target); }
  disconnect() { this.observed.clear(); }
  report(visible: FakeElement[]) { this.callback([...this.observed].map(target => ({ target, isIntersecting: visible.includes(target) }))); }
}

function streamingFeed() {
  const streams = new Map<string, QuoteStreamHandlers>();
  const log: string[] = [];
  const feed: QuoteFeed = {
    getQuotes: async ({ instruments }) => instruments.map(i => ({ ...i, last: 100, previousClose: 100 })),
    subscribeQuotes(instruments, handlers) {
      const id = instruments.map(i => `${i.symbol}@${i.exchange}`).join(',');
      log.push(`+${id}`); streams.set(id, handlers);
      handlers.onStatus?.('live');
      return () => { log.push(`-${id}`); streams.delete(id); };
    },
  };
  const push = (symbol: string, last: number, previousClose = 100, exchange = 'NSE') =>
    streams.get(`${symbol}@${exchange}`)!.onQuote({ symbol, exchange, last, previousClose } as QuoteSnapshot);
  return { feed, streams, log, push };
}

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); FakeObserver.last = null; vi.useRealTimers(); });

async function rig(options: {
  store?: WatchlistStore; storage?: WatchlistStorage; quotes?: QuoteFeed | null; observer?: boolean; lists?: Array<[string, InstrumentKey[]]>;
  panel?: Partial<WatchlistPanelOptions>; search?: WidgetContext['symbolSearch']; translate?: WidgetContext['translate'];
} = {}) {
  const doc = fakeWidgetDocument();
  if (options.observer) (doc as unknown as { defaultView: unknown }).defaultView = { IntersectionObserver: FakeObserver };
  const root = fakeContainer(doc);
  const chart = new Chart(root as unknown as HTMLElement, { document: doc as unknown as Document,
    shortcuts: false, pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: '1m' });
  // Bars with a distinctive close: a panel that relabelled the last candle as a quote would show it.
  chart.addSeries('candlestick').setData([{ time: 1700000000, open: 9, high: 999.5, low: 8, close: 987.65 }]);
  const stack = createOverlayStack(root as unknown as HTMLElement, doc as unknown as Document);
  const ctx = {
    chart, document: doc, root, locale: 'en-US', overlays: stack, openOverlay: stack.open, storage: new WidgetStorage('t', null),
    tips: { attach: () => () => {} }, bus: new WidgetBus(), symbolSearch: options.search, translate: options.translate,
    symbol: () => ({ symbol: chart.getDataContext()?.symbol ?? '', exchange: chart.getDataContext()?.exchange ?? '' }),
  } as unknown as WidgetContext;
  let n = 0;
  const store = options.store ?? new WatchlistRepository(options.storage ?? createMemoryWatchlistStorage(), 'user', { id: () => `l${++n}`, now: () => 1000 });
  for (const [name, entries] of options.lists ?? []) await store.createList(name, entries);
  const host = doc.createElement('div'); root.appendChild(host);
  const quotes = options.quotes === undefined ? streamingFeed() : null;
  const onSelect = vi.fn();
  const panel = mountWatchlistPanel(ctx, host as unknown as HTMLElement, { store, quotes: options.quotes ?? quotes?.feed, onSelect, ...options.panel });
  await flush();
  const rows = () => (host as FakeElement).querySelectorAll('tbody tr');
  const cell = (row: FakeElement, name: string) => row.querySelector(`.oac-watchlist__${name}`)!;
  const symbols = () => rows().map(row => row.dataset.symbol);
  const button = (label: string) => (host as FakeElement).querySelectorAll('button').find(b => (b.getAttribute('aria-label') ?? b.textContent) === label)!;
  return { doc, root, chart, ctx, host: host as FakeElement, store, panel, quotes, onSelect, rows, cell, symbols, button };
}

describe('watchlist panel', () => {
  it('renders the active list with streamed quotes and updates cells in place', async () => {
    const r = await rig({ lists: [['Tech', [nse('INFY'), nse('TCS')]]] });
    expect(r.symbols()).toEqual(['INFY', 'TCS']);
    const first = r.rows()[0];
    r.quotes!.push('INFY', 1500, 1480);
    await flush();
    expect(r.rows()[0]).toBe(first);
    expect(r.cell(first, 'last').textContent).toBe('1,500.00');
    expect(r.cell(first, 'change').textContent).toBe('+20.00');
    expect(r.cell(first, 'percent').textContent).toBe('+1.35%');
    expect(first.dataset.state).toBe('live');
    expect(r.host.querySelector('.oac-watchlist__status')!.textContent).toBe('Live quotes');
    r.quotes!.push('INFY', 1470, 1480);
    await flush();
    expect(r.rows()[0]).toBe(first);
    expect(r.cell(first, 'change').textContent).toBe('-10.00');
    expect(r.cell(first, 'change').classList.contains('is-down')).toBe(true);
    // The exchange's time, in the chart's zone (IST by default), not the browser's clock.
    r.quotes!.streams.get('TCS@NSE')!.onQuote({ symbol: 'TCS', exchange: 'NSE', last: 3500, previousClose: 3400, time: 1700000000 });
    await flush();
    expect(r.cell(r.rows()[1], 'last').title).toBe('Live 3:43:20 AM');
    r.panel.destroy();
  });

  it('names its rows and empty prices in the host language', async () => {
    const words: Record<string, string> = {
      'schema.ui.watchlist.entry': '{symbol} en {exchange}', 'schema.ui.watchlist.noQuote': 'sin dato',
    };
    const r = await rig({ quotes: null, lists: [['Tech', [nse('INFY')]]], translate: (key, fallback) => words[key] ?? fallback });
    const row = r.rows()[0]!;
    expect(r.cell(row, 'last').textContent).toBe('sin dato');
    expect(row.querySelector('.oac-watchlist__open')?.getAttribute('aria-label')).toBe('INFY en NSE');
    r.panel.destroy();
  });

  it('shows no price without a quote source, even with bars on the chart', async () => {
    const r = await rig({ quotes: null, lists: [['Tech', [nse('INFY')]]] });
    const row = r.rows()[0];
    expect(row.dataset.state).toBe('unavailable');
    expect(r.host.textContent).not.toContain('987.65');
    expect(r.cell(row, 'last').textContent).toBe('n/a');
    expect(r.host.querySelector('.oac-watchlist__status')!.textContent).toBe('No quote source. Rows show symbols only.');
    r.panel.destroy();
  });

  it('subscribes only rows reported visible, and releases them on a list switch and on destroy', async () => {
    const r = await rig({ observer: true, lists: [['Long', [nse('A'), nse('B'), nse('C')]], ['Short', [nse('Z')]]] });
    const io = FakeObserver.last!;
    expect(io.observed.size).toBe(3);
    expect(r.quotes!.log).toEqual([]);
    io.report([r.rows()[0], r.rows()[1]]);
    await flush();
    expect(r.quotes!.log).toEqual(['+A@NSE', '+B@NSE']);
    // Scrolling on: A leaves, C arrives.
    io.report([r.rows()[1], r.rows()[2]]);
    await flush();
    expect(r.quotes!.log).toEqual(['+A@NSE', '+B@NSE', '-A@NSE', '+C@NSE']);
    const select = r.host.querySelector('select') as FakeElement;
    select.value = 'l2';
    fire(select, 'change');
    await flush();
    expect(r.symbols()).toEqual(['Z']);
    expect(r.quotes!.log.slice(4).sort()).toEqual(['-B@NSE', '-C@NSE']);
    expect(io.observed.size).toBe(1);
    io.report([r.rows()[0]]);
    await flush();
    expect(r.quotes!.log.slice(-1)).toEqual(['+Z@NSE']);
    expect((await r.store.load()).activeListId).toBe('l2');
    r.panel.destroy();
    expect(r.quotes!.log.slice(-1)).toEqual(['-Z@NSE']);
    expect(r.quotes!.streams.size).toBe(0);
  });

  it('pauses every stream while the page is hidden', async () => {
    const r = await rig({ lists: [['Tech', [nse('INFY'), nse('TCS')]]] });
    expect(r.quotes!.streams.size).toBe(2);
    (r.doc as unknown as { hidden: boolean }).hidden = true;
    fire(r.doc as unknown as FakeElement, 'visibilitychange');
    await flush();
    expect(r.quotes!.streams.size).toBe(0);
    (r.doc as unknown as { hidden: boolean }).hidden = false;
    fire(r.doc as unknown as FakeElement, 'visibilitychange');
    await flush();
    expect(r.quotes!.streams.size).toBe(2);
    r.panel.destroy();
  });

  it('sorts stably by percent change, keeps list order for ties, and holds order under the pointer', async () => {
    const r = await rig({ lists: [['Mix', [nse('A'), nse('B'), nse('C'), nse('D')]]] });
    r.quotes!.push('A', 101); r.quotes!.push('B', 103); r.quotes!.push('C', 101);
    r.quotes!.streams.get('D@NSE')!.onQuote({ symbol: 'D', exchange: 'NSE', last: 50 });
    await flush();
    const header = r.host.querySelector('th[data-sort="percent"] button') as FakeElement;
    header.click(); await flush();
    // D has no reference close: unknown sorts last in either direction.
    expect(r.symbols()).toEqual(['B', 'A', 'C', 'D']);
    expect(header.parentElement!.getAttribute('aria-sort')).toBe('descending');
    header.click(); await flush();
    expect(r.symbols()).toEqual(['A', 'C', 'B', 'D']);
    const rowsBody = r.host.querySelector('tbody') as FakeElement;
    fire(rowsBody, 'pointerenter');
    r.quotes!.push('C', 105);
    await flush();
    // The value moves at once; the row does not jump out from under the pointer.
    expect(r.symbols()).toEqual(['A', 'C', 'B', 'D']);
    expect(r.cell(r.rows()[1], 'percent').textContent).toBe('+5.00%');
    fire(rowsBody, 'pointerleave');
    await flush();
    expect(r.symbols()).toEqual(['A', 'B', 'C', 'D']);
    header.click(); await flush();
    expect(header.parentElement!.getAttribute('aria-sort')).toBe('none');
    expect(r.symbols()).toEqual(['A', 'B', 'C', 'D']);
    r.panel.destroy();
  });

  it('adds the chart instrument, refuses a repeat, and removes a row', async () => {
    const r = await rig({ lists: [['Tech', [nse('TCS')]]] });
    const add = r.button('Add INFY');
    expect(add.disabled).toBe(false);
    add.click(); await flush();
    expect(r.symbols()).toEqual(['TCS', 'INFY']);
    expect(r.button('Add INFY').disabled).toBe(true);
    expect((await r.store.load()).lists[0].entries).toEqual([nse('TCS'), nse('INFY')]);
    r.button('Remove TCS on NSE').click(); await flush();
    expect(r.symbols()).toEqual(['INFY']);
    expect((await r.store.load()).lists[0].entries).toEqual([nse('INFY')]);
    r.panel.destroy();
  });

  it('adds a typed symbol on the chart\'s exchange, and starts a first list when there is none', async () => {
    const r = await rig();
    expect(r.host.querySelector('.oac-watchlist__empty')!.textContent).toContain('No watchlists yet');
    const input = r.host.querySelector('.oac-watchlist__add input') as FakeElement;
    input.value = 'wipro';
    fireKey(input, 'Enter'); await flush();
    const catalog = await r.store.load();
    expect(catalog.lists.map(list => list.name)).toEqual(['Watchlist']);
    expect(catalog.lists[0].entries).toEqual([nse('WIPRO')]);
    expect(catalog.activeListId).toBe(catalog.lists[0].id);
    expect(r.symbols()).toEqual(['WIPRO']);
    expect(input.value).toBe('');
    r.panel.destroy();
  });

  it('waits for a pending lookup before Enter saves the typed text', async () => {
    vi.useFakeTimers();
    let answer!: (hits: readonly InstrumentKey[]) => void;
    const r = await rig({ lists: [['Tech', [nse('TCS')]]], search: () => new Promise(resolve => { answer = resolve; }) });
    const input = r.host.querySelector('.oac-watchlist__add input') as FakeElement;
    input.focus(); input.value = 'wip'; fire(input, 'input');
    fireKey(input, 'Enter'); await flush();
    await vi.advanceTimersByTimeAsync(150);
    fireKey(input, 'Enter'); await flush();
    expect(r.symbols()).toEqual(['TCS']);
    answer([{ symbol: 'WIPRO', exchange: 'BSE' }]); await flush();
    fireKey(input, 'Enter'); await flush();
    expect((await r.store.load()).lists[0]!.entries).toEqual([nse('TCS'), { symbol: 'WIPRO', exchange: 'BSE' }]);
    r.panel.destroy();
  });

  it('creates, renames and deletes lists through inline forms', async () => {
    const r = await rig({ lists: [['Tech', [nse('TCS')]]] });
    r.button('New list').click();
    const name = r.host.querySelector('.oac-watchlist__name input') as FakeElement;
    expect(r.doc.activeElement).toBe(name);
    name.value = 'Banks';
    fire(r.host.querySelector('.oac-watchlist__name')!, 'submit'); await flush();
    let catalog = await r.store.load();
    expect(catalog.lists.map(list => list.name)).toEqual(['Tech', 'Banks']);
    expect(catalog.activeListId).toBe(catalog.lists[1].id);
    expect(r.symbols()).toEqual([]);
    r.button('Rename list').click();
    expect(name.value).toBe('Banks');
    name.value = 'Lenders';
    fire(r.host.querySelector('.oac-watchlist__name')!, 'submit'); await flush();
    expect((await r.store.load()).lists[1].name).toBe('Lenders');
    r.button('Delete list').click();
    expect(r.host.querySelector('.oac-watchlist__confirm')!.hidden).toBe(false);
    r.button('Keep list').click();
    expect((await r.store.load()).lists).toHaveLength(2);
    r.button('Delete list').click();
    r.button('Delete Lenders').click(); await flush();
    catalog = await r.store.load();
    expect(catalog.lists.map(list => list.name)).toEqual(['Tech']);
    expect(r.symbols()).toEqual(['TCS']);
    r.panel.destroy();
  });

  it('runs on a store that implements only what the panel calls', async () => {
    let n = 0;
    const repo = new WatchlistRepository(createMemoryWatchlistStorage(), 'user', { id: () => `l${++n}`, now: () => 1000 });
    // A server-backed store owes the panel these members and no others (typecheck holds this).
    const store: WatchlistStore = {
      load: () => repo.load(), subscribe: listener => repo.subscribe(listener),
      createList: (name, entries, options) => repo.createList(name, entries, options),
      renameList: (id, name, options) => repo.renameList(id, name, options),
      removeList: (id, options) => repo.removeList(id, options),
      setActiveList: (id, options) => repo.setActiveList(id, options),
      addEntry: (id, entry, options) => repo.addEntry(id, entry, options),
      removeEntry: (id, entry, options) => repo.removeEntry(id, entry, options),
      moveEntry: (id, entry, index, options) => repo.moveEntry(id, entry, index, options),
    };
    const r = await rig({ store, lists: [['Tech', [nse('TCS')]]] });
    r.button('Add INFY').click(); await flush();
    const open = r.rows()[1].querySelector('.oac-watchlist__open') as FakeElement;
    fireKey(open, 'ArrowUp', { altKey: true }); await flush();
    expect(r.symbols()).toEqual(['INFY', 'TCS']);
    expect((await repo.load()).lists[0].entries).toEqual([nse('INFY'), nse('TCS')]);
    r.panel.destroy();
  });

  it('reports a storage conflict and shows the saved lists instead of the local guess', async () => {
    const storage = createMemoryWatchlistStorage();
    let n = 0;
    const repo = new WatchlistRepository(storage, 'user', { id: () => `l${++n}`, now: () => 1000 });
    const store: WatchlistStore = Object.assign(Object.create(repo) as WatchlistStore, {
      addEntry: async () => {
        // Another session edits the same list, then this session's write loses the race.
        await new WatchlistRepository(storage, 'user').addEntry('l1', nse('HDFC'));
        throw new WatchlistConflictError();
      },
    });
    const r = await rig({ store, lists: [['Tech', [nse('TCS')]]] });
    r.button('Add INFY').click(); await flush();
    const alert = r.host.querySelector('.oac-watchlist__message')!;
    expect(alert.hidden).toBe(false);
    expect(alert.getAttribute('role')).toBe('alert');
    expect(alert.textContent).toBe('The watchlists changed in another session. The saved lists are shown.');
    expect(r.symbols()).toEqual(['TCS', 'HDFC']);
    r.panel.destroy();
  });

  it('reorders with Alt+Arrow in list order, refusing a move computed from an older revision', async () => {
    const storage = createMemoryWatchlistStorage();
    const r = await rig({ storage, lists: [['Order', [nse('A'), nse('B'), nse('C')]]] });
    const open = (i: number) => r.rows()[i].querySelector('.oac-watchlist__open') as FakeElement;
    open(0).focus();
    fireKey(open(0), 'ArrowDown', { altKey: true }); await flush();
    expect(r.symbols()).toEqual(['B', 'A', 'C']);
    expect(r.doc.activeElement).toBe(open(1));
    fireKey(open(1), 'ArrowDown'); await flush();
    expect(r.doc.activeElement).toBe(open(2));
    // Another session reorders first; the stale move is refused and the saved order shown.
    await new WatchlistRepository(storage, 'user').moveEntry('l1', nse('C'), 0);
    fireKey(open(2), 'ArrowUp', { altKey: true }); await flush();
    expect(r.host.querySelector('.oac-watchlist__message')!.textContent).toContain('changed in another session');
    expect(r.symbols()).toEqual(['C', 'B', 'A']);
    r.panel.destroy();
  });

  it('lands two quick Alt+Arrow moves in turn instead of calling the second a conflict', async () => {
    const r = await rig({ lists: [['Order', [nse('A'), nse('B'), nse('C')]]] });
    const a = r.rows()[0].querySelector('.oac-watchlist__open') as FakeElement;
    a.focus();
    // A held key repeats before the first move is saved.
    fireKey(a, 'ArrowDown', { altKey: true });
    fireKey(a, 'ArrowDown', { altKey: true });
    await flush();
    expect(r.host.querySelector('.oac-watchlist__message')!.hidden).toBe(true);
    expect(r.symbols()).toEqual(['B', 'C', 'A']);
    expect((await r.store.load()).lists[0].entries).toEqual([nse('B'), nse('C'), nse('A')]);
    r.panel.destroy();
  });

  it('keeps taking Alt+Arrow moves after one fails in a way its own handler cannot report', async () => {
    let n = 0;
    const repo = new WatchlistRepository(createMemoryWatchlistStorage(), 'user', { id: () => `l${++n}`, now: () => 1000 });
    let broken = true;
    const store: WatchlistStore = {
      load: () => repo.load(), subscribe: listener => repo.subscribe(listener),
      createList: (name, entries, options) => repo.createList(name, entries, options),
      renameList: (id, name, options) => repo.renameList(id, name, options),
      removeList: (id, options) => repo.removeList(id, options),
      setActiveList: (id, options) => repo.setActiveList(id, options),
      addEntry: (id, entry, options) => repo.addEntry(id, entry, options),
      removeEntry: (id, entry, options) => repo.removeEntry(id, entry, options),
      moveEntry: (id, entry, index, options) => {
        // A rejection with no text in it throws again inside the panel's own failure handler.
        if (broken) { broken = false; return Promise.reject(Object.create(null)); }
        return repo.moveEntry(id, entry, index, options);
      },
    };
    const r = await rig({ store, lists: [['Order', [nse('A'), nse('B'), nse('C')]]] });
    const a = () => r.rows().find(row => row.dataset.symbol === 'A')!.querySelector('.oac-watchlist__open') as FakeElement;
    fireKey(a(), 'ArrowDown', { altKey: true }); await flush();
    expect(r.symbols()).toEqual(['A', 'B', 'C']);
    fireKey(a(), 'ArrowDown', { altKey: true }); await flush();
    expect(r.symbols()).toEqual(['B', 'A', 'C']);
    expect((await repo.load()).lists[0].entries).toEqual([nse('B'), nse('A'), nse('C')]);
    r.panel.destroy();
  });

  it('opens the chosen instrument and marks the chart\'s own row', async () => {
    const r = await rig({ lists: [['Dual', [nse('INFY'), { symbol: 'INFY', exchange: 'BSE' }]]] });
    expect(r.rows()[0].getAttribute('aria-current')).toBe('true');
    expect(r.rows()[1].getAttribute('aria-current')).toBeNull();
    (r.rows()[1].querySelector('.oac-watchlist__open') as FakeElement).click();
    expect(r.onSelect).toHaveBeenCalledWith({ symbol: 'INFY', exchange: 'BSE' });
    r.chart.setDataContext({ symbol: 'INFY', exchange: 'BSE', interval: '1m' });
    await flush();
    expect(r.rows()[1].getAttribute('aria-current')).toBe('true');
    expect(r.rows()[0].getAttribute('aria-current')).toBeNull();
    r.panel.destroy();
  });

  it('marks quotes stale while the stream reconnects', async () => {
    const r = await rig({ lists: [['Tech', [nse('INFY')]]] });
    r.quotes!.push('INFY', 1500);
    await flush();
    r.quotes!.streams.get('INFY@NSE')!.onStatus!('reconnecting');
    await flush();
    expect(r.rows()[0].dataset.state).toBe('stale');
    expect(r.cell(r.rows()[0], 'last').textContent).toBe('1,500.00');
    expect(r.host.querySelector('.oac-watchlist__status')!.textContent).toBe('Reconnecting. Quotes shown may be stale.');
    r.panel.destroy();
  });

  it('builds one time formatter per zone however many quotes repaint the rows', async () => {
    const r = await rig({ lists: [['Tech', [nse('INFY'), nse('TCS'), nse('WIPRO')]]] });
    const Real = Intl.DateTimeFormat;
    let built = 0;
    const counting = function (this: unknown, ...args: ConstructorParameters<typeof Intl.DateTimeFormat>) { built++; return new Real(...args); };
    Intl.DateTimeFormat = counting as unknown as typeof Intl.DateTimeFormat;
    try {
      for (let step = 0; step < 10; step++) {
        for (const symbol of ['INFY', 'TCS', 'WIPRO']) {
          r.quotes!.streams.get(`${symbol}@NSE`)!.onQuote({ symbol, exchange: 'NSE', last: 100 + step, previousClose: 100, time: 1700000000 + step });
        }
        await flush();
      }
    } finally { Intl.DateTimeFormat = Real; }
    expect(r.cell(r.rows()[2], 'last').title).toBe('Live 3:43:29 AM');
    expect(built).toBeLessThanOrEqual(1);
    r.panel.destroy();
  });

  it('shows row times in a new chart timezone at once, without waiting for the next quote', async () => {
    const r = await rig({ lists: [['Tech', [nse('INFY')]]] });
    r.quotes!.streams.get('INFY@NSE')!.onQuote({ symbol: 'INFY', exchange: 'NSE', last: 1500, previousClose: 1480, time: 1700000000 });
    await flush();
    expect(r.cell(r.rows()[0], 'last').title).toBe('Live 3:43:20 AM');
    r.chart.setTimezone('UTC');
    await flush();
    expect(r.cell(r.rows()[0], 'last').title).toBe('Live 10:13:20 PM');
    r.panel.destroy();
  });

  it('does not call values stale when a broken source never showed one', async () => {
    const handlers: QuoteStreamHandlers[] = [];
    const feed: QuoteFeed = {
      getQuotes: async () => { throw new Error('quotes are served only with --fixture'); },
      subscribeQuotes(_instruments, stream) { handlers.push(stream); stream.onStatus?.('disconnected'); return () => {}; },
    };
    const r = await rig({ quotes: feed, lists: [['Tech', [nse('INFY')]]] });
    const status = () => r.host.querySelector('.oac-watchlist__status')!.textContent;
    expect(r.cell(r.rows()[0], 'last').textContent).toBe('n/a');
    expect(status()).toBe('Quotes disconnected.');
    handlers[0].onStatus!('reconnecting');
    await flush();
    expect(status()).toBe('Reconnecting to quotes.');
    // Once a value is on screen, the warning is about it.
    handlers[0].onStatus!('live');
    handlers[0].onQuote({ symbol: 'INFY', exchange: 'NSE', last: 1500 });
    handlers[0].onStatus!('disconnected');
    await flush();
    expect(status()).toBe('Quotes disconnected. Values shown are stale.');
    r.panel.destroy();
  });

  it('repaints once when its snapshots age into stale, then does no work while the board sits idle', async () => {
    vi.useFakeTimers();
    const feed: QuoteFeed = { getQuotes: async ({ instruments }) => instruments.map(i => ({ ...i, last: 100, previousClose: 99 })) };
    const r = await rig({ quotes: feed, panel: { pollMs: 0, staleAfterMs: 1000 }, lists: [['Tech', [nse('INFY'), nse('TCS')]]] });
    expect(r.rows().map(row => row.dataset.state)).toEqual(['snapshot', 'snapshot']);
    // Every paint reads the chart's instrument once, which makes it countable.
    const paints = vi.spyOn(r.ctx, 'symbol');
    await vi.advanceTimersByTimeAsync(1001);
    expect(r.rows().map(row => row.dataset.state)).toEqual(['stale', 'stale']);
    expect(paints).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(paints).toHaveBeenCalledTimes(1);
    r.panel.destroy();
  });
});
