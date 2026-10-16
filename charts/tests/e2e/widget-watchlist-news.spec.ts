import { expect, test, type Page } from '@playwright/test';

const FIXTURE = '/tests/e2e/widget-watchlist-news-fixture.html';

async function mount(page: Page, width = 1280, height = 800): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height });
  await page.goto(FIXTURE);
  await page.waitForFunction(() => Boolean((window as any).__market?.widget));
  return errors;
}

const subscribed = (page: Page) => page.evaluate(() => (window as any).__market.quotes.subscribed() as string[]);

/** The rows whose box overlaps the scroller, as the observer should report them. */
const onScreen = (page: Page) => page.evaluate(() => {
  const scroll = document.querySelector('.oac-watchlist__scroll')!.getBoundingClientRect();
  return [...document.querySelectorAll<HTMLElement>('.oac-watchlist tbody tr')]
    .filter(row => { const r = row.getBoundingClientRect(); return r.bottom > scroll.top && r.top < scroll.bottom; })
    .map(row => `${row.dataset.symbol}@${row.dataset.exchange}`).sort();
});

const order = (page: Page) => page.evaluate(() => [...document.querySelectorAll<HTMLElement>('.oac-watchlist tbody tr')].map(row => ({
  key: `${row.dataset.symbol}@${row.dataset.exchange}`,
  percent: Number.parseFloat(row.querySelector('.oac-watchlist__percent')!.textContent || 'NaN'),
})));

test('watchlist rows stream only while on screen, sort stably and release on switch and close', async ({ page }, info) => {
  const errors = await mount(page);
  await page.locator('.oac-topbar').getByRole('button', { name: 'Watchlist', exact: true }).click();
  const panel = page.locator('.oac-watchlist');
  await expect(panel.locator('tbody tr')).toHaveCount(40);
  await expect(panel.locator('tbody tr').first().locator('.oac-watchlist__last')).toHaveText(/^\d[\d,]*\.\d{2}$/);
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Live quotes');
  // Only the rows on screen hold a stream, and they all do.
  await expect.poll(async () => { const [a, b] = await Promise.all([subscribed(page), onScreen(page)]); return a.length > 0 && a.join() === b.join(); }).toBe(true);
  expect((await subscribed(page)).length).toBeLessThan(40);
  expect(await subscribed(page)).not.toContain('S38@DEMO');
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-symbol', 'NOVA');
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-exchange', 'DEMO');
  await page.screenshot({ path: info.outputPath('watchlist-desktop.png') });

  await panel.locator('.oac-watchlist__scroll').evaluate(element => { element.scrollTop = element.scrollHeight; });
  await expect.poll(() => subscribed(page)).toContain('NOVA@ALT');
  expect(await subscribed(page)).not.toContain('NOVA@DEMO');
  await expect.poll(async () => (await subscribed(page)).join() === (await onScreen(page)).join()).toBe(true);
  await panel.locator('.oac-watchlist__scroll').evaluate(element => { element.scrollTop = 0; });

  // Percent change, high first; ties and unknowns keep a stable place.
  await panel.getByRole('button', { name: 'Chg%', exact: true }).click();
  await expect(panel.locator('th[data-sort="percent"]')).toHaveAttribute('aria-sort', 'descending');
  await page.mouse.move(5, 400);
  await expect.poll(async () => {
    const rows = await order(page);
    return rows.every((row, i) => i === 0 || !(row.percent > rows[i - 1].percent));
  }).toBe(true);
  // Under the pointer the values move but the rows stay put.
  const row = panel.locator('tbody tr').nth(2);
  await row.hover();
  const held = (await order(page)).map(item => item.key);
  const heldPrices = await panel.locator('.oac-watchlist__last').allTextContents();
  await expect.poll(async () => (await panel.locator('.oac-watchlist__last').allTextContents()).join() !== heldPrices.join(), { timeout: 5000 }).toBe(true);
  expect((await order(page)).map(item => item.key)).toEqual(held);
  await page.mouse.move(5, 400);

  // Choosing a row charts that instrument, on its own venue.
  await panel.getByRole('button', { name: 'S03 on DEMO', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__market.widget.symbol())).toBe('S03');

  await panel.getByRole('combobox', { name: 'Watchlist' }).selectOption({ label: 'Banks' });
  await expect(panel.locator('tbody tr')).toHaveCount(3);
  await expect.poll(() => subscribed(page)).toEqual(['BANKA@DEMO', 'BANKB@DEMO', 'BANKC@DEMO']);
  await page.locator('.oac-panel-dock').getByRole('button', { name: 'Close', exact: true }).click();
  await expect.poll(() => subscribed(page)).toEqual([]);
  expect(errors).toEqual([]);
});

test('a reconnecting stream shows its quotes as stale until it is live again', async ({ page }, info) => {
  const errors = await mount(page);
  await page.evaluate(() => (window as any).__market.widget.openWatchlist());
  const panel = page.locator('.oac-watchlist');
  await expect(panel.locator('tbody tr').first()).toHaveAttribute('data-state', 'live');
  const snapshots = await page.evaluate(() => (window as any).__market.quotes.snapshots as number);
  await page.evaluate(() => (window as any).__market.quotes.setStatus('reconnecting'));
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Reconnecting. Quotes shown may be stale.');
  await expect(panel.locator('tbody tr').first()).toHaveAttribute('data-state', 'stale');
  await expect(panel.locator('tbody tr').first().locator('.oac-watchlist__last')).toHaveText(/^\d/);
  await page.screenshot({ path: info.outputPath('watchlist-stale.png') });
  await page.evaluate(() => (window as any).__market.quotes.setStatus('live'));
  await expect(panel.locator('tbody tr').first()).toHaveAttribute('data-state', 'live');
  // Reconnecting asked for fresh snapshots rather than trusting the held quotes.
  expect(await page.evaluate(() => (window as any).__market.quotes.snapshots as number)).toBeGreaterThan(snapshots);
  expect(errors).toEqual([]);
});

test('news shows provider text as text, pages older items and opens only safe links', async ({ page }, info) => {
  const errors = await mount(page);
  await page.locator('.oac-topbar').getByRole('button', { name: 'News', exact: true }).click();
  const panel = page.locator('.oac-news');
  await expect(panel.locator('.oac-news__item')).toHaveCount(6);
  await expect(panel.locator('.oac-news__instrument')).toHaveText('NOVA');
  await expect(panel.locator('.oac-news__headline').nth(1)).toHaveText('<img src=x onerror="window.__xss=1">Rates <b>cut</b>');
  expect(await panel.locator('img, b, script').count()).toBe(0);
  await expect(panel.locator('.oac-news__item time').first()).toHaveAttribute('datetime', /^2025-09-25T/);
  await page.screenshot({ path: info.outputPath('news-desktop.png') });

  await panel.locator('.oac-news__open').nth(1).click();
  await expect(panel.locator('.oac-news__detail')).toBeVisible();
  await expect(panel.locator('.oac-news__detail a')).toHaveCount(0);
  await expect(panel.locator('.oac-news__detail')).toContainText('No article link');
  await panel.getByRole('button', { name: 'Back to news', exact: true }).click();
  await expect(panel.locator('.oac-news__open').nth(1)).toBeFocused();
  await panel.locator('.oac-news__open').first().click();
  const link = panel.locator('.oac-news__detail a');
  await expect(link).toHaveAttribute('href', 'https://example.com/NOVA/0');
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(panel.locator('.oac-news__detail-summary')).toHaveText('Summary 0 for NOVA.\nSecond line.');
  await page.screenshot({ path: info.outputPath('news-detail.png') });
  await panel.getByRole('button', { name: 'Back to news', exact: true }).click();

  await panel.getByRole('button', { name: 'Load older news', exact: true }).click();
  // Six more, one of which repeats the previous page: eleven distinct items.
  await expect(panel.locator('.oac-news__item')).toHaveCount(11);
  await expect(panel.locator('.oac-news__end')).toHaveText('No older news');
  await page.evaluate(() => (window as any).__market.widget.setSymbol('S07', 'DEMO'));
  await expect(panel.locator('.oac-news__instrument')).toHaveText('S07');
  await expect(panel.locator('.oac-news__headline').first()).toHaveText('S07 story 0');
  expect(await page.evaluate(() => (window as any).__xss)).toBeUndefined();
  expect(errors).toEqual([]);
});

test('at phone width the watchlist and news open as a sheet from More', async ({ page }, info) => {
  const errors = await mount(page, 390, 844);
  const more = page.locator('[data-mobile-action="more"]');
  await expect(more).toBeVisible();
  await more.click();
  await page.locator('[data-mobile-action="watchlist"]').click();
  const dock = page.locator('.oac-panel-dock');
  await expect(dock).toHaveAttribute('data-sheet', 'true');
  const box = await dock.boundingBox();
  expect(box!.width).toBeGreaterThanOrEqual(388);
  await expect(dock.locator('.oac-watchlist tbody tr').first().locator('.oac-watchlist__last')).toHaveText(/^\d/);
  await expect.poll(async () => (await subscribed(page)).length).toBeGreaterThan(0);
  expect((await subscribed(page)).length).toBeLessThan(40);
  await page.screenshot({ path: info.outputPath('watchlist-390.png') });
  await dock.getByRole('button', { name: 'News', exact: true }).click();
  await expect(dock.locator('.oac-news__item')).toHaveCount(6);
  await expect.poll(() => subscribed(page)).toEqual([]);
  await page.screenshot({ path: info.outputPath('news-390.png') });
  await dock.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dock).toBeHidden();
  expect(errors).toEqual([]);
});

test('IndexedDB watchlists survive a reload and refuse a second tab\'s stale write', async ({ page, context }) => {
  const modulePath = '/dist/openalgo-charts.workspace.mjs';
  await page.goto('/tests/e2e/fixture.html');
  await page.evaluate(async modulePath => {
    const { WatchlistRepository, createIndexedDbWatchlistStorage } = await import(modulePath);
    const storage = createIndexedDbWatchlistStorage(indexedDB, 'watchlist-e2e');
    const repo = new WatchlistRepository(storage, 'account', { id: () => 'desk', now: () => 1 });
    const list = await repo.createList('Desk', [{ symbol: 'RELIANCE', exchange: 'NSE' }, { symbol: 'RELIANCE', exchange: 'BSE' }]);
    await repo.setActiveList(list.id);
    await storage.close();
  }, modulePath);
  await page.reload();
  const other = await context.newPage();
  await other.goto('/tests/e2e/fixture.html');
  const saved = await page.evaluate(async modulePath => {
    const { WatchlistRepository, createIndexedDbWatchlistStorage } = await import(modulePath);
    (window as any).__storage = createIndexedDbWatchlistStorage(indexedDB, 'watchlist-e2e');
    return new WatchlistRepository((window as any).__storage, 'account').load();
  }, modulePath);
  expect(saved.activeListId).toBe('desk');
  expect(saved.lists[0].entries).toEqual([{ symbol: 'RELIANCE', exchange: 'NSE' }, { symbol: 'RELIANCE', exchange: 'BSE' }]);
  await other.evaluate(async modulePath => {
    const { createIndexedDbWatchlistStorage } = await import(modulePath);
    (window as any).__storage = createIndexedDbWatchlistStorage(indexedDB, 'watchlist-e2e');
  }, modulePath);
  const writes = await Promise.all([page, other].map((tab, i) => tab.evaluate(async ({ revision, name }) => {
    const storage = (window as any).__storage;
    const catalog = { version: 1, revision: revision + 1, activeListId: null, lists: [{ id: 'desk', name, entries: [], createdAt: 1, updatedAt: 2 }] };
    try { await storage.write('account', catalog, revision); return 'saved'; }
    catch (error) { return (error as Error).name; }
  }, { revision: saved.revision, name: `Tab ${i}` })));
  expect(writes.sort()).toEqual(['WatchlistConflictError', 'saved']);
  await Promise.all([page, other].map(tab => tab.evaluate(() => (window as any).__storage.close())));
});

test('the website example prices its rows and its chart from one simulated exchange', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1000, height: 640 });
  await page.route('**/watchlist-example.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:960px;height:560px}</style></head><body><div id="example"></div></body></html>' }));
  await page.goto('/watchlist-example.html');
  const [page_, market] = await Promise.all([
    page.request.get('/website/pages/examples.mdx').then(response => response.text()),
    page.request.get('/website/components/synthetic-market.ts').then(response => response.text()),
  ]);
  // The same code the site runs: the section's template, with the shared bar generator spliced in.
  const template = page_.split('## Watchlists and news')[1].split('code={`')[1].split('`} />')[0];
  const code = template.replace('${STOCK_BARS_SOURCE}', market.split('STOCK_BARS_SOURCE = `')[1].split('`;')[0]);
  await page.evaluate(async source => {
    const all = '/dist/openalgo-charts.all.mjs', tier = '/dist/openalgo-charts.widget.mjs', studies = '/dist/openalgo-charts.indicators.mjs';
    const [lib, widget] = await Promise.all([import(all), import(tier), import(studies)]);
    const run = new Function('el', 'lib', source) as (el: HTMLElement, lib: unknown) => unknown;
    (window as any).__example = run(document.getElementById('example')!, { ...lib, createWidget: (host: HTMLElement, options: object) => widget.createWidget(host, { theme: 'dark', ...options }) });
  }, code);
  const panel = page.locator('#example .oac-watchlist');
  await expect(panel.locator('tbody tr')).toHaveCount(8);
  await expect(panel.locator('tr[data-symbol="NOVA"] .oac-watchlist__last')).toHaveText(/^\d[\d,]*\.\d{2}$/);
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Live quotes');
  // The chart's forming bar and the NOVA row read the same exchange, tick for tick.
  await expect.poll(() => page.evaluate(() => {
    const text = document.querySelector('#example tr[data-symbol="NOVA"] .oac-watchlist__last')!.textContent!.replace(/,/g, '');
    const bars = (window as any).__example.series.getData();
    return Math.abs(Number(text) - bars[bars.length - 1].close) < 0.005;
  }), { timeout: 10_000 }).toBe(true);
  await page.locator('#example').screenshot({ path: info.outputPath('website-watchlist-example.png') });
  expect(errors).toEqual([]);
});
