import { afterEach, describe, expect, it } from 'vitest';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import { WatchlistRepository, createMemoryWatchlistStorage } from '../src/workspace/index';
import type { NewsFeed, NewsRequest, QuoteFeed, QuoteStreamHandlers } from '../src/feed/types';
import { fakeWidgetDocument, fakeContainer, ensureWindowGlobal, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
const widgets: Widget[] = [];
afterEach(() => { for (const widget of widgets.splice(0)) widget.destroy(); });

function sources() {
  const streams = new Map<string, QuoteStreamHandlers>();
  const quotes: QuoteFeed = {
    getQuotes: async ({ instruments }) => instruments.map(i => ({ ...i, last: 10, previousClose: 9 })),
    subscribeQuotes(instruments, handlers) {
      const id = `${instruments[0].symbol}@${instruments[0].exchange}`;
      streams.set(id, handlers);
      handlers.onStatus?.('live');
      return () => { streams.delete(id); };
    },
  };
  const newsCalls: NewsRequest[] = [];
  const news: NewsFeed = { getNews: async request => { newsCalls.push(request); return { items: [{ id: `${request.symbol}-1`, headline: `${request.symbol} headline`, time: 1700000000 }] }; } };
  let n = 0;
  const store = new WatchlistRepository(createMemoryWatchlistStorage(), 'user', { id: () => `l${++n}`, now: () => 1 });
  return { streams, quotes, news, newsCalls, store };
}

function make(options: Partial<WidgetOptions> = {}) {
  ensureWindowGlobal();
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc, 1000) as unknown as HTMLElement, { document: doc as unknown as Document,
    symbol: 'INFY', exchange: 'NSE', shortcuts: false, mobile: 'never',
    pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} }, ...options });
  widgets.push(widget);
  (widget.root as unknown as FakeElement).rect = { left: 0, top: 0, width: 1000, height: 600 };
  const root = widget.root as unknown as FakeElement;
  const topButton = (label: string) => root.querySelector('.oac-topbar')!.querySelectorAll('button').find(b => b.textContent === label) ?? null;
  return { widget, root, topButton };
}

describe('widget watchlist and news', () => {
  it('has no watchlist or news controls unless the host supplies their sources', () => {
    const { widget, topButton, root } = make();
    expect(topButton('Watchlist')).toBeNull();
    expect(topButton('News')).toBeNull();
    expect(widget.openWatchlist()).toBe(false);
    expect(widget.openNews()).toBe(false);
    widget.openDataWindow();
    expect(root.querySelectorAll('.oac-panel-dock__tabs button').map(b => b.textContent)).toEqual(['Data', 'Objects']);
  });

  it('opens the watchlist from the top bar, streams its rows and charts a chosen row', async () => {
    const s = sources();
    const list = await s.store.createList('Tech', [{ symbol: 'INFY', exchange: 'NSE' }, { symbol: 'TCS', exchange: 'NSE' }]);
    const { widget, topButton, root } = make({ watchlist: { store: s.store, quotes: s.quotes } });
    topButton('Watchlist')!.click();
    await flush();
    expect(widget.getState().panels?.panel).toBe('watchlist');
    expect(root.querySelectorAll('.oac-watchlist tbody tr').map(row => row.dataset.symbol)).toEqual(['INFY', 'TCS']);
    expect([...s.streams.keys()]).toEqual(['INFY@NSE', 'TCS@NSE']);
    (root.querySelectorAll('.oac-watchlist__open')[1] as FakeElement).click();
    expect(widget.symbol()).toBe('TCS');
    expect(widget.exchange()).toBe('NSE');
    expect((await s.store.load()).lists[0].id).toBe(list.id);
    // Switching to another panel releases every stream the watchlist held.
    widget.openDataWindow();
    expect(s.streams.size).toBe(0);
    widget.openWatchlist();
    await flush();
    expect(s.streams.size).toBe(2);
    widget.destroy();
    expect(s.streams.size).toBe(0);
  });

  it('treats a row as the instrument the widget will chart, so case never splits one instrument in two', async () => {
    const s = sources();
    await s.store.createList('Mixed', [{ symbol: 'infy', exchange: 'NSE' }, { symbol: 'TCS', exchange: 'NSE' }]);
    const { widget, root } = make({
      watchlist: { store: s.store, quotes: s.quotes },
      symbolSearch: () => [{ symbol: 'wipro', exchange: 'NSE' }],
    });
    widget.openWatchlist();
    await flush();
    const rows = () => root.querySelectorAll('.oac-watchlist tbody tr');
    const entries = async () => (await s.store.load()).lists[0].entries;
    // The widget charts INFY for this row, so it is the chart's own row and INFY is already listed.
    expect(rows()[0].getAttribute('aria-current')).toBe('true');
    expect((root.querySelector('.oac-watchlist__add-current') as FakeElement).disabled).toBe(true);
    const input = root.querySelector('.oac-watchlist__add input') as FakeElement;
    input.value = 'infy';
    fireKey(input, 'Enter');
    await flush();
    expect(root.querySelector('.oac-watchlist__message')!.textContent).toBe('INFY on NSE is already in this list');
    expect(await entries()).toEqual([{ symbol: 'infy', exchange: 'NSE' }, { symbol: 'TCS', exchange: 'NSE' }]);
    // A search result is saved as the widget will chart it.
    input.focus(); input.value = 'wi'; fire(input, 'input');
    await new Promise(resolve => setTimeout(resolve, 250));
    fireKey(input, 'Enter');
    await flush();
    expect(await entries()).toEqual([{ symbol: 'infy', exchange: 'NSE' }, { symbol: 'TCS', exchange: 'NSE' }, { symbol: 'WIPRO', exchange: 'NSE' }]);
    (root.querySelectorAll('.oac-watchlist__open')[0] as FakeElement).click();
    await flush();
    expect(widget.symbol()).toBe('INFY');
    expect(rows()[0].getAttribute('aria-current')).toBe('true');
  });

  it('keeps the watchlist sort when the panel is switched away and back without persistence', async () => {
    const s = sources();
    await s.store.createList('Tech', [{ symbol: 'INFY', exchange: 'NSE' }, { symbol: 'TCS', exchange: 'NSE' }]);
    const { widget, root } = make({ watchlist: { store: s.store, quotes: s.quotes } });
    widget.openWatchlist();
    await flush();
    const percent = () => root.querySelector('.oac-watchlist th[data-sort="percent"]') as FakeElement;
    (percent().querySelector('button') as FakeElement).click();
    expect(percent().getAttribute('aria-sort')).toBe('descending');
    widget.openDataWindow();
    widget.openWatchlist();
    await flush();
    expect(percent().getAttribute('aria-sort')).toBe('descending');
  });

  it('opens news for the chart instrument and follows a symbol change', async () => {
    const s = sources();
    const { widget, topButton, root } = make({ news: { feed: s.news } });
    topButton('News')!.click();
    await flush();
    expect(s.newsCalls.map(call => [call.symbol, call.exchange])).toEqual([['INFY', 'NSE']]);
    expect(root.querySelector('.oac-news__headline')!.textContent).toBe('INFY headline');
    widget.setSymbol('WIPRO', 'BSE');
    await flush();
    expect(s.newsCalls.map(call => [call.symbol, call.exchange])).toEqual([['INFY', 'NSE'], ['WIPRO', 'BSE']]);
    expect(root.querySelector('.oac-news__headline')!.textContent).toBe('WIPRO headline');
    expect(widget.getState().panels?.panel).toBe('news');
  });

  it('restores the open panel, and keeps it closed where its source is missing', async () => {
    const s = sources();
    const first = make({ watchlist: { store: s.store }, news: { feed: s.news } });
    first.widget.openNews();
    const second = make({ watchlist: { store: s.store }, news: { feed: s.news } });
    second.widget.restoreState(first.widget.getState());
    await flush();
    expect(second.widget.getState().panels?.panel).toBe('news');
    expect(second.root.querySelector('.oac-news')).not.toBeNull();
    // A saved panel whose source this host lacks stays closed rather than empty.
    const bare = make();
    bare.widget.restoreState(first.widget.getState());
    expect(bare.widget.getState().panels?.panel).toBeNull();
  });
});
