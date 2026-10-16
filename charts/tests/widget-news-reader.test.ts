import { afterEach, describe, expect, it, vi } from 'vitest';
import { NewsReader } from '../src/widget/news-reader';
import type { NewsFeed, NewsItem, NewsPage, NewsRequest } from '../src/feed/types';

const item = (id: string, time: number, extra: Partial<NewsItem> = {}): NewsItem => ({ id, headline: `Headline ${id}`, time, source: 'Desk', ...extra });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

function manualFeed() {
  const calls: Array<{ request: NewsRequest; resolve(page: NewsPage): void; reject(error: Error): void }> = [];
  const feed: NewsFeed = { getNews: request => new Promise((resolve, reject) => { calls.push({ request, resolve, reject }); }) };
  return { feed, calls };
}

afterEach(() => { vi.useRealTimers(); });

describe('news reader', () => {
  it('pages older news with the provider cursor and drops items repeated across pages', async () => {
    const { feed, calls } = manualFeed();
    const reader = new NewsReader({ feed, pageSize: 2 });
    reader.setInstrument({ symbol: 'INFY', exchange: 'NSE' });
    expect(reader.snapshot().status).toBe('loading');
    expect(calls[0].request).toMatchObject({ symbol: 'INFY', exchange: 'NSE', limit: 2 });
    expect(calls[0].request.cursor).toBeUndefined();
    calls[0].resolve({ items: [item('a', 300), item('b', 200)], nextCursor: 'c1' });
    await tick();
    expect(reader.snapshot()).toMatchObject({ status: 'ready', hasMore: true, stale: false, error: null });
    void reader.loadMore();
    void reader.loadMore();
    // A second press while the page loads is not a second request.
    expect(calls).toHaveLength(2);
    expect(reader.snapshot().loadingMore).toBe(true);
    expect(calls[1].request.cursor).toBe('c1');
    // The provider shifted: 'b' is repeated on the next page.
    calls[1].resolve({ items: [item('b', 200), item('c', 100)], nextCursor: null });
    await tick();
    const snap = reader.snapshot();
    expect(snap.items.map(i => i.id)).toEqual(['a', 'b', 'c']);
    expect(snap).toMatchObject({ hasMore: false, loadingMore: false });
    await reader.loadMore();
    expect(calls).toHaveLength(2);
    reader.destroy();
  });

  it('reports empty and error states, and keeps items as stale when a refresh fails', async () => {
    const { feed, calls } = manualFeed();
    const reader = new NewsReader({ feed });
    reader.setInstrument({ symbol: 'EMPTY', exchange: '' });
    calls[0].resolve({ items: [] });
    await tick();
    expect(reader.snapshot()).toMatchObject({ status: 'empty', items: [], hasMore: false });
    reader.setInstrument({ symbol: 'FAIL', exchange: '' });
    calls[1].reject(new Error('upstream 502'));
    await tick();
    expect(reader.snapshot()).toMatchObject({ status: 'error', error: 'upstream 502', items: [] });
    reader.setInstrument({ symbol: 'OK', exchange: '' });
    calls[2].resolve({ items: [item('x', 10)] });
    await tick();
    void reader.refresh();
    // The items stay on screen while the newest page reloads.
    expect(reader.snapshot()).toMatchObject({ status: 'loading', items: [{ id: 'x' }] });
    calls[3].reject(new Error('timeout'));
    await tick();
    expect(reader.snapshot()).toMatchObject({ status: 'ready', stale: true, error: 'timeout', items: [{ id: 'x' }] });
    void reader.refresh();
    calls[4].resolve({ items: [item('y', 20), item('x', 10)] });
    await tick();
    expect(reader.snapshot()).toMatchObject({ status: 'ready', stale: false, error: null });
    expect(reader.snapshot().items.map(i => i.id)).toEqual(['y', 'x']);
    reader.destroy();
  });

  it('flags news older than the stale window and announces it without a new request', async () => {
    vi.useFakeTimers();
    let now = 0;
    const onChange = vi.fn();
    const feed: NewsFeed = { getNews: async () => ({ items: [item('a', 1)] }) };
    const reader = new NewsReader({ feed, staleAfterMs: 1000, now: () => now, onChange });
    reader.setInstrument({ symbol: 'A', exchange: '' });
    await vi.advanceTimersByTimeAsync(0);
    expect(reader.snapshot().stale).toBe(false);
    onChange.mockClear();
    now = 1500;
    await vi.advanceTimersByTimeAsync(1500);
    expect(onChange).toHaveBeenCalled();
    expect(reader.snapshot().stale).toBe(true);
    reader.destroy();
  });

  it('cancels on an instrument switch and on destroy, and ignores answers the provider sends anyway', async () => {
    const { feed, calls } = manualFeed();
    const onChange = vi.fn();
    const reader = new NewsReader({ feed, onChange });
    reader.setInstrument({ symbol: 'A', exchange: 'NSE' });
    reader.setInstrument({ symbol: 'A', exchange: 'NSE' });
    expect(calls).toHaveLength(1);
    reader.setInstrument({ symbol: 'A', exchange: 'BSE' });
    expect(calls[0].request.signal!.aborted).toBe(true);
    calls[0].resolve({ items: [item('old', 5)] });
    calls[1].resolve({ items: [item('new', 6)] });
    await tick();
    expect(reader.snapshot().items.map(i => i.id)).toEqual(['new']);
    expect(reader.snapshot().instrument).toEqual({ symbol: 'A', exchange: 'BSE' });
    void reader.refresh();
    reader.destroy();
    expect(calls[2].request.signal!.aborted).toBe(true);
    onChange.mockClear();
    calls[2].resolve({ items: [item('late', 9)] });
    await tick();
    expect(onChange).not.toHaveBeenCalled();
    reader.setInstrument(null);
    expect(calls).toHaveLength(3);
  });

  it('keeps only valid items as plain text, newest first, and leaves link safety to the view', async () => {
    const feed: NewsFeed = { getNews: async () => ({ items: [
      item('old', 100),
      { id: '', headline: 'No id', time: 5 },
      { id: 'blank', headline: '   ', time: 5 },
      { id: 'nan', headline: 'Bad time', time: Number.NaN },
      null as unknown as NewsItem,
      { id: 'new', headline: '  <b>Bold</b>\nclaim  ', time: 900, source: ' Wire\u0007 ', summary: 'Line one\r\nline two', url: 'javascript:alert(1)' },
    ] }) };
    const reader = new NewsReader({ feed });
    reader.setInstrument({ symbol: 'A', exchange: '' });
    await tick();
    const items = reader.snapshot().items;
    expect(items.map(i => i.id)).toEqual(['new', 'old']);
    expect(items[0]).toEqual({ id: 'new', headline: '<b>Bold</b> claim', time: 900, source: 'Wire', summary: 'Line one\nline two', url: 'javascript:alert(1)' });
    reader.destroy();
  });

  it('stops paging when a provider makes no progress', async () => {
    const pages: NewsPage[] = [
      { items: [item('a', 3)], nextCursor: 'same' },
      { items: [item('b', 2)], nextCursor: 'same' },
    ];
    const feed: NewsFeed = { getNews: async () => pages.shift() ?? { items: [], nextCursor: 'more' } };
    const reader = new NewsReader({ feed });
    reader.setInstrument({ symbol: 'A', exchange: '' });
    await tick();
    await reader.loadMore();
    expect(reader.snapshot()).toMatchObject({ hasMore: false });
    expect(reader.snapshot().items.map(i => i.id)).toEqual(['a', 'b']);
    const empty = new NewsReader({ feed });
    empty.setInstrument({ symbol: 'B', exchange: '' });
    await tick();
    // An empty page that still offers a cursor is not progress either.
    expect(empty.snapshot()).toMatchObject({ status: 'empty', hasMore: false });
    reader.destroy(); empty.destroy();
  });

  it('bounds the items it holds and reports an older-page failure without discarding news', async () => {
    let n = 0;
    let fail = false;
    const feed: NewsFeed = { getNews: async () => {
      if (fail) throw new Error('page failed');
      const items = Array.from({ length: 3 }, () => { n++; return item(`i${n}`, 10000 - n); });
      return { items, nextCursor: `c${n}` };
    } };
    const reader = new NewsReader({ feed, maxItems: 5 });
    reader.setInstrument({ symbol: 'A', exchange: '' });
    await tick();
    await reader.loadMore();
    expect(reader.snapshot()).toMatchObject({ hasMore: false });
    expect(reader.snapshot().items).toHaveLength(5);
    const other = new NewsReader({ feed });
    other.setInstrument({ symbol: 'B', exchange: '' });
    await tick();
    fail = true;
    await other.loadMore();
    expect(other.snapshot()).toMatchObject({ status: 'ready', hasMore: true, loadingMore: false, error: 'page failed' });
    expect(other.snapshot().items).toHaveLength(3);
    reader.destroy(); other.destroy();
  });
});
