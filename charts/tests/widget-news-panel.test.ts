import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { mountNewsPanel, safeNewsUrl } from '../src/widget/news-panel';
import type { WidgetContext } from '../src/widget/context';
import type { NewsFeed, NewsItem, NewsPage, NewsRequest } from '../src/feed/types';
import { fakeWidgetDocument, fakeContainer, type FakeElement } from './helpers/fake-dom-widget';

const flush = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function manualFeed() {
  const calls: Array<{ request: NewsRequest; resolve(page: NewsPage): void; reject(error: Error): void }> = [];
  const feed: NewsFeed = { getNews: request => new Promise((resolve, reject) => { calls.push({ request, resolve, reject }); }) };
  return { feed, calls };
}

function rig(feed: NewsFeed) {
  const doc = fakeWidgetDocument(), root = fakeContainer(doc);
  const chart = new Chart(root as unknown as HTMLElement, { document: doc as unknown as Document,
    shortcuts: false, pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: '1m' });
  const ctx = {
    chart, document: doc, root, locale: 'en-US',
    symbol: () => ({ symbol: chart.getDataContext()?.symbol ?? '', exchange: chart.getDataContext()?.exchange ?? '' }),
  } as unknown as WidgetContext;
  const host = doc.createElement('div'); root.appendChild(host);
  const panel = mountNewsPanel(ctx, host as unknown as HTMLElement, { feed, pageSize: 2 });
  const q = (selector: string) => (host as FakeElement).querySelector(selector)!;
  const all = (selector: string) => (host as FakeElement).querySelectorAll(selector);
  const byText = (label: string) => (host as FakeElement).querySelectorAll('button').find(b => b.textContent === label || b.getAttribute('aria-label') === label)!;
  return { doc, chart, host: host as FakeElement, panel, q, all, byText };
}

const hostile: NewsItem = { id: 'x1', headline: '<img src=x onerror="alert(1)">Rates <b>cut</b>', source: 'Wire <i>desk</i>',
  time: 1700000000, summary: 'First line.\nSecond <script>line</script>.', url: 'https://news.example.com/a?b=1' };

describe('news panel', () => {
  it('lists headline, source and time for the chart instrument as text, never markup', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    expect(calls[0].request).toMatchObject({ symbol: 'INFY', exchange: 'NSE', limit: 2 });
    expect(r.q('.oac-news__status').textContent).toBe('Loading news for INFY');
    calls[0].resolve({ items: [hostile] });
    await flush();
    expect(r.all('img')).toHaveLength(0);
    expect(r.all('b')).toHaveLength(0);
    expect(r.all('script')).toHaveLength(0);
    const item = r.all('.oac-news__item')[0];
    expect(item.querySelector('.oac-news__headline')!.textContent).toBe('<img src=x onerror="alert(1)">Rates <b>cut</b>');
    expect(item.querySelector('.oac-news__source')!.textContent).toBe('Wire <i>desk</i>');
    const time = item.querySelector('time')!;
    // 1700000000 is 22:13 UTC on the 14th: the chart's default zone, IST, reads it on the 15th.
    expect(time.textContent).toBe('Nov 15, 2023, 3:43 AM');
    expect(time.getAttribute('datetime')).toBe('2023-11-14T22:13:20.000Z');
    r.panel.destroy();
  });

  it('opens a detail view whose article link is safe, and returns to the item', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    calls[0].resolve({ items: [hostile, { id: 'x2', headline: 'Scripted link', time: 1699990000, url: 'javascript:alert(1)' }] });
    await flush();
    const open = r.all('.oac-news__open');
    open[0].click();
    const detail = r.q('.oac-news__detail');
    expect(detail.hidden).toBe(false);
    expect(r.q('.oac-news__list').hidden).toBe(true);
    expect(detail.querySelector('.oac-news__detail-summary')!.textContent).toBe('First line.\nSecond <script>line</script>.');
    const link = detail.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('https://news.example.com/a?b=1');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.getAttribute('referrerpolicy')).toBe('no-referrer');
    r.byText('Back to news').click();
    expect(detail.hidden).toBe(true);
    expect(r.doc.activeElement).toBe(r.all('.oac-news__open')[0]);
    r.all('.oac-news__open')[1].click();
    expect(r.q('.oac-news__detail').querySelector('a')).toBeNull();
    expect(r.q('.oac-news__detail').textContent).toContain('No article link');
    r.panel.destroy();
  });

  it('accepts only absolute http and https article links without credentials', () => {
    expect(safeNewsUrl('https://example.com/x')).toBe('https://example.com/x');
    expect(safeNewsUrl('http://example.com/x')).toBe('http://example.com/x');
    expect(safeNewsUrl('javascript:alert(1)')).toBeNull();
    expect(safeNewsUrl('JAVASCRIPT:alert(1)')).toBeNull();
    expect(safeNewsUrl('data:text/html,hi')).toBeNull();
    expect(safeNewsUrl('/relative/path')).toBeNull();
    expect(safeNewsUrl('https://user:pass@example.com/')).toBeNull();
    expect(safeNewsUrl(undefined)).toBeNull();
  });

  it('pages older news on request and says when there is no more', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    calls[0].resolve({ items: [{ id: 'a', headline: 'A', time: 30 }, { id: 'b', headline: 'B', time: 20 }], nextCursor: 'p2' });
    await flush();
    r.byText('Load older news').click();
    expect(calls[1].request.cursor).toBe('p2');
    expect(r.byText('Loading older news').disabled).toBe(true);
    calls[1].resolve({ items: [{ id: 'b', headline: 'B', time: 20 }, { id: 'c', headline: 'C', time: 10 }] });
    await flush();
    expect(r.all('.oac-news__headline').map(node => node.textContent)).toEqual(['A', 'B', 'C']);
    const end = r.q('.oac-news__end');
    expect(end.hidden).toBe(false);
    expect(end.textContent).toBe('No older news');
    expect(r.byText('Load older news').hidden).toBe(true);
    r.panel.destroy();
  });

  it('shows empty, error with retry, and stale states', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    calls[0].resolve({ items: [] });
    await flush();
    expect(r.q('.oac-news__status').textContent).toBe('No news for INFY');
    r.byText('Refresh news').click();
    calls[1].reject(new Error('upstream 502'));
    await flush();
    expect(r.q('.oac-news__status').textContent).toBe('News could not load: upstream 502');
    expect(r.q('.oac-news__status').dataset.state).toBe('error');
    r.byText('Refresh news').click();
    calls[2].resolve({ items: [{ id: 'a', headline: 'A', time: 30 }] });
    await flush();
    r.byText('Refresh news').click();
    calls[3].reject(new Error('timeout'));
    await flush();
    expect(r.all('.oac-news__item')).toHaveLength(1);
    expect(r.q('.oac-news__status').textContent).toBe('Showing earlier news. Refresh failed: timeout');
    expect(r.q('.oac-news__status').dataset.state).toBe('stale');
    r.panel.destroy();
  });

  it('follows the chart instrument, cancelling the previous request, and stops on destroy', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    r.chart.setDataContext({ symbol: 'TCS', exchange: 'NSE', interval: '1m' });
    await flush();
    expect(calls[0].request.signal!.aborted).toBe(true);
    expect(calls[1].request).toMatchObject({ symbol: 'TCS', exchange: 'NSE' });
    calls[0].resolve({ items: [{ id: 'old', headline: 'INFY story', time: 5 }] });
    calls[1].resolve({ items: [{ id: 'new', headline: 'TCS story', time: 6 }] });
    await flush();
    expect(r.all('.oac-news__headline').map(node => node.textContent)).toEqual(['TCS story']);
    expect(r.q('.oac-news__instrument').textContent).toBe('TCS');
    r.chart.setDataContext({ symbol: 'TCS', exchange: 'NSE', interval: '5m' });
    await flush();
    // A new interval is the same instrument: no refetch.
    expect(calls).toHaveLength(2);
    r.byText('Refresh news').click();
    r.panel.destroy();
    expect(calls[2].request.signal!.aborted).toBe(true);
    expect(r.host.querySelector('.oac-news')).toBeNull();
    r.chart.setDataContext({ symbol: 'WIPRO', exchange: 'NSE', interval: '5m' });
    await flush();
    expect(calls).toHaveLength(3);
  });

  it('rewrites every shown time when the chart timezone changes, the open detail included', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    calls[0].resolve({ items: [{ id: 'a', headline: 'A', time: 1700000000, source: 'Desk' }] });
    await flush();
    r.all('.oac-news__open')[0].click();
    r.chart.setTimezone('UTC');
    expect(r.q('.oac-news__detail-meta time').textContent).toBe('Nov 14, 2023, 10:13 PM');
    r.byText('Back to news').click();
    expect(r.all('.oac-news__item time')[0].textContent).toBe('Nov 14, 2023, 10:13 PM');
    r.panel.destroy();
  });

  it('asks for nothing without a chart symbol', async () => {
    const { feed, calls } = manualFeed();
    const r = rig(feed);
    r.chart.setDataContext(undefined);
    await flush();
    expect(r.q('.oac-news__status').textContent).toBe('Choose a symbol to see its news');
    expect(calls[0].request.signal!.aborted).toBe(true);
    expect(calls).toHaveLength(1);
    r.panel.destroy();
  });
});
