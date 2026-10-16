import { test, expect, type Page } from '@playwright/test';

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/quotes?symbols=AAPL';
let serverUp: boolean | null = null;

async function open(page: Page, width: number, height: number): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
  return errors;
}

const quoteFeed = (page: Page, call: string, arg?: unknown) => page.evaluate(async ({ call, arg }) => {
  const path = '/examples/yfinance/src/market-panels.js';
  const feed = (await import(path)).referenceQuotes();
  return feed[call](arg);
}, { call, arg });

test.beforeEach(async ({ request }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server with quotes is unavailable');
});

test('the reference watchlist shows fixture quotes, charts a chosen row and goes stale when quotes drop', async ({ page }, info) => {
  const errors = await open(page, 1440, 900);
  await page.getByRole('button', { name: 'Watchlists and quotes', exact: true }).click();
  const dock = page.locator('#inspect-layout-1 .oac-panel-dock');
  const panel = dock.locator('.oac-watchlist');
  // A first visit gets the seeded list, saved in IndexedDB.
  await expect(panel.locator('tbody tr')).toHaveCount(8);
  await expect(panel.getByRole('combobox', { name: 'Watchlist' })).toHaveValue(/.+/);
  await expect(panel.locator('tr[data-symbol="AAPL"] .oac-watchlist__last')).toHaveText(/^\d[\d,]*\.\d{2}$/);
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Live quotes');
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-symbol', 'AAPL');
  // An arithmetic symbol has no quote source: its row says so instead of borrowing a close.
  await panel.getByRole('searchbox', { name: 'Add symbol' }).fill('aapl/msft');
  // Enter waits while the lookup runs, as in the top bar; once it has found nothing, the typed text is added.
  await expect(async () => {
    await panel.getByRole('searchbox', { name: 'Add symbol' }).press('Enter');
    await expect(panel.locator('tr[data-symbol="AAPL/MSFT"]')).toHaveCount(1, { timeout: 500 });
  }).toPass();
  await expect(panel.locator('tr[data-symbol="AAPL/MSFT"]')).toHaveAttribute('data-state', 'unavailable');
  await expect(panel.locator('tr[data-symbol="AAPL/MSFT"] .oac-watchlist__last')).toHaveText('n/a');
  await page.screenshot({ path: info.outputPath('reference-watchlist.png') });

  // Sort, then chart a row: the host rebuilds the dock for the new symbol, and the sort stays.
  const percent = panel.locator('th[data-sort="percent"]');
  await percent.getByRole('button').click();
  await expect(percent).toHaveAttribute('aria-sort', 'descending');
  await panel.getByRole('button', { name: 'RELIANCE.NS', exact: true }).click();
  await page.waitForFunction(() => (window as any).__oac.app.req?.symbol === 'RELIANCE.NS' && !(window as any).__oac.app.loading);
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-symbol', 'RELIANCE.NS');
  await expect(percent).toHaveAttribute('aria-sort', 'descending');
  // This host rebuilds its chart for a new symbol, and the dock's panel with it:
  // held quotes go stale only once the new panel has some to hold.
  await expect(panel.locator('tr[data-symbol="AAPL"]')).toHaveAttribute('data-state', 'live', { timeout: 10000 });

  await quoteFeed(page, 'setOffline', true);
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Reconnecting. Quotes shown may be stale.', { timeout: 10000 });
  await expect(panel.locator('tr[data-symbol="AAPL"]')).toHaveAttribute('data-state', 'stale');
  await page.screenshot({ path: info.outputPath('reference-watchlist-stale.png') });
  await quoteFeed(page, 'setOffline', false);
  await expect(panel.locator('tr[data-symbol="AAPL"]')).toHaveAttribute('data-state', 'live', { timeout: 10000 });

  // The lists live in IndexedDB: a reload keeps the added row.
  await page.reload();
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
  if (!(await page.locator('#inspect-layout-1 .oac-watchlist').isVisible())) {
    await page.getByRole('button', { name: 'Watchlists and quotes', exact: true }).click();
  }
  await expect(page.locator('#inspect-layout-1 .oac-watchlist tbody tr')).toHaveCount(9);
  expect(errors).toEqual([]);
});

test('the reference news reader pages fixture news as text and opens only safe links', async ({ page }, info) => {
  const errors = await open(page, 1440, 900);
  await page.getByRole('button', { name: 'News for this symbol', exact: true }).click();
  const panel = page.locator('#inspect-layout-1 .oac-news');
  await expect(panel.locator('.oac-news__instrument')).toHaveText('AAPL');
  await expect(panel.locator('.oac-news__item')).toHaveCount(20);
  expect(await panel.locator('.oac-news__list b, .oac-news__list img').count()).toBe(0);
  const markup = panel.locator('.oac-news__headline', { hasText: '<b>guidance</b>' });
  if (await markup.count() > 0) {
    await markup.first().click();
    await expect(panel.locator('.oac-news__detail a')).toHaveCount(0);
    await expect(panel.locator('.oac-news__detail')).toContainText('No article link');
    await panel.getByRole('button', { name: 'Back to news', exact: true }).click();
  }
  await page.screenshot({ path: info.outputPath('reference-news.png') });
  await panel.getByRole('button', { name: 'Load older news', exact: true }).click();
  await expect.poll(() => panel.locator('.oac-news__item').count()).toBeGreaterThan(20);
  const ids = await panel.locator('.oac-news__open').evaluateAll(nodes => nodes.map(node => (node as HTMLElement).dataset.id));
  expect(new Set(ids).size).toBe(ids.length);
  const safe = panel.locator('.oac-news__open').first();
  await safe.click();
  const link = panel.locator('.oac-news__detail a');
  if (await link.count() > 0) {
    await expect(link).toHaveAttribute('href', /^https:\/\/example\.com\/news\/AAPL\/\d+$/);
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  }
  await panel.getByRole('button', { name: 'Back to news', exact: true }).click();
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'MSFT';
    await (window as any).__oac.app.load();
  });
  await expect(panel.locator('.oac-news__instrument')).toHaveText('MSFT');
  await expect(panel.locator('.oac-news__headline').first()).toContainText('MSFT');
  expect(errors).toEqual([]);
});

test('at phone width the reference watchlist and news open as a sheet', async ({ page }, info) => {
  const errors = await open(page, 390, 844);
  await page.getByRole('button', { name: 'Watchlists and quotes', exact: true }).click();
  // A sheet lives in the overlay layer, not beside the chart.
  const dock = page.locator('.oac-panel-dock[data-sheet="true"]');
  await expect(dock).toBeVisible();
  await expect(dock.locator('.oac-watchlist tbody tr')).toHaveCount(8);
  await expect(dock.locator('tr[data-symbol="AAPL"] .oac-watchlist__last')).toHaveText(/^\d/);
  const box = await dock.boundingBox();
  expect(box!.width).toBeGreaterThanOrEqual(380);
  await page.screenshot({ path: info.outputPath('reference-watchlist-390.png') });
  await dock.getByRole('button', { name: 'News', exact: true }).click();
  await expect(dock.locator('.oac-news__item').first()).toBeVisible();
  await expect.poll(() => quoteFeed(page, 'subscribed')).toEqual([]);
  await page.screenshot({ path: info.outputPath('reference-news-390.png') });
  await dock.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dock).toBeHidden();
  expect(errors).toEqual([]);
});

test('the grid view offers the watchlist and news in each chart', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/examples/yfinance/grid.html?test=1');
  await page.waitForFunction(() => (window as any).__grid?.cells().length === 4);
  const cell = page.locator('.oac-grid__cell').first();
  await cell.locator('.oac-topbar').getByRole('button', { name: 'Watchlist', exact: true }).click();
  const panel = cell.locator('.oac-watchlist');
  await expect(panel.locator('tbody tr')).toHaveCount(8);
  await expect(panel.locator('tr[data-symbol="MSFT"] .oac-watchlist__last')).toHaveText(/^\d[\d,]*\.\d{2}$/);
  await expect(panel.locator('.oac-watchlist__status')).toHaveText('Live quotes');
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-symbol', 'AAPL');
  await page.screenshot({ path: info.outputPath('grid-watchlist.png') });
  await panel.getByRole('button', { name: 'MSFT', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__grid.cells()[0].widget.symbol())).toBe('MSFT');
  await expect(panel.locator('tr[aria-current="true"]')).toHaveAttribute('data-symbol', 'MSFT');
  await cell.locator('.oac-panel-dock__tabs').getByRole('button', { name: 'News', exact: true }).click();
  await expect(cell.locator('.oac-news__instrument')).toHaveText('MSFT');
  await expect(cell.locator('.oac-news__item').first()).toBeVisible();
  await page.screenshot({ path: info.outputPath('grid-news.png') });
  // Another chart has its own dock and its own instrument.
  const second = page.locator('.oac-grid__cell').nth(1);
  await second.locator('.oac-topbar').getByRole('button', { name: 'News', exact: true }).click();
  await expect(second.locator('.oac-news__instrument')).toHaveText(await page.evaluate(() => (window as any).__grid.cells()[1].widget.symbol()));
  expect(errors).toEqual([]);
});
