import { expect, test, type Page, type Route } from '@playwright/test';

const FIXTURE = '/tests/e2e/widget-feed-events-fixture.html';

/** A seeded random walk of daily bars that looks like a traded stock. */
function dailyBars(count: number, seed: number): Array<Record<string, number>> {
  let state = seed;
  const next = (): number => { state = (state * 1664525 + 1013904223) % 4294967296; return state / 4294967296; };
  const end = Date.UTC(2026, 8, 25) / 1000;
  let close = 2840;
  return Array.from({ length: count }, (_, i) => {
    const open = close;
    close = Math.max(1, open * (1 + (next() - 0.49) * 0.03));
    const high = Math.max(open, close) * (1 + next() * 0.008);
    const low = Math.min(open, close) * (1 - next() * 0.008);
    const round = (value: number): number => Math.round(value * 20) / 20;
    return { timestamp: end - (count - 1 - i) * 86400, open: round(open), high: round(high), low: round(low), close: round(close), volume: Math.round(2e6 + next() * 3e6) };
  });
}

/** Rows in the platform's search shape. */
const row = (symbol: string, exchange: string, name: string, expiry = '') => ({ symbol, brsymbol: symbol, name, exchange, brexchange: exchange, token: '1', expiry, strike: -1, lotsize: 1, instrumenttype: 'EQ', tick_size: 0.05 });
const SEARCH: Record<string, unknown[]> = {
  INFY: [row('INFY', 'BSE', 'INFOSYS LIMITED'), row('INFY', 'NSE', 'INFOSYS LIMITED')],
  NIFTY: [
    row('NIFTY', 'NSE_INDEX', 'NIFTY'),
    row('NIFTY28OCT26FUT', 'NFO', 'NIFTY', '28-OCT-26'),
    ...[24800, 24900, 25000, 25100].flatMap(strike => ['CE', 'PE'].map(side => row(`NIFTY28OCT26${strike}${side}`, 'NFO', 'NIFTY', '28-OCT-26'))),
    row('NIFTY25NOV2625000CE', 'NFO', 'NIFTY', '25-NOV-26'),
  ],
};

interface Traffic { searches: Array<Record<string, unknown>>; failed: string[]; held: Route[] }

async function mount(page: Page): Promise<Traffic> {
  const traffic: Traffic = { searches: [], failed: [], held: [] };
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('requestfailed', request => { if (request.url().endsWith('/api/v1/search')) traffic.failed.push(JSON.parse(request.postData() ?? '{}').query); });
  await page.route('**/api/v1/history', route => route.fulfill({ json: { status: 'success', data: dailyBars(160, 11) } }));
  await page.route('**/api/v1/search', async route => {
    const body = JSON.parse(route.request().postData() ?? '{}') as Record<string, unknown>;
    traffic.searches.push(body);
    const query = String(body.query).toUpperCase();
    // Held until the page gives up on it, to show a superseded query is cancelled.
    if (query === 'NIF') { traffic.held.push(route); return; }
    if (query === 'BROKEN') { await route.fulfill({ status: 500, json: { status: 'error', message: 'An unexpected error occurred' } }); return; }
    await route.fulfill({ json: { status: 'success', data: SEARCH[query] ?? [] } });
  });
  await page.setViewportSize({ width: 1180, height: 720 });
  await page.goto(FIXTURE);
  await page.waitForFunction(() => ((window as any).__feedEvents?.widget.series.getData().length ?? 0) > 100);
  expect(errors).toEqual([]);
  return traffic;
}

test('the widget searches through the OpenAlgo feed with no host lookup', async ({ page }, info) => {
  const traffic = await mount(page);
  const input = page.locator('.oac-sym__input');
  const results = page.locator('.oac-symbol-picker');

  // A superseded query is cancelled in flight, not merely ignored.
  // Emptied first: a click leaves the caret after the symbol in some engines.
  await input.fill('');
  await input.pressSequentially('NIF');
  await expect.poll(() => traffic.held.length).toBe(1);
  await input.pressSequentially('TY');
  await expect.poll(() => traffic.failed).toEqual(['NIF']);
  for (const route of traffic.held) await route.fulfill({ json: { status: 'success', data: [] } }).catch(() => {});

  // Index, future and one row per option expiry, with each expiry opening onto its strikes.
  await expect(results.locator('.oac-symbol-picker__row')).toHaveCount(4);
  await expect(results.locator('.oac-symbol-picker__row .oac-menu__label')).toHaveText(['NSE_INDEX:NIFTY', 'NFO:NIFTY28OCT26FUT', 'NFO:NIFTY 28-OCT-26', 'NFO:NIFTY25NOV2625000CE']);
  await expect(results.getByRole('button', { name: 'Options', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('symbol-search-results.png') });
  await results.locator('.oac-symbol-picker__row').nth(2).click();
  await expect(results.locator('.oac-symbol-picker__row')).toHaveCount(8);
  await page.screenshot({ path: info.outputPath('symbol-search-contracts.png') });
  await results.locator('.oac-symbol-picker__row', { hasText: 'NIFTY28OCT2625000PE' }).click();
  await expect.poll(() => page.evaluate(() => { const w = (window as any).__feedEvents.widget; return `${w.exchange()}:${w.symbol()}`; })).toBe('NFO:NIFTY28OCT2625000PE');
  expect(traffic.searches.every(body => body.apikey === 'placeholder-key' && Object.keys(body).sort().join() === 'apikey,query')).toBe(true);

  // The exact symbol on the chart's exchange is first, so Enter keeps the venue.
  await page.evaluate(() => (window as any).__feedEvents.widget.setSymbol('RELIANCE', 'NSE'));
  await input.click();
  await input.fill('INFY');
  await expect(results.locator('.oac-symbol-picker__row .oac-menu__label')).toHaveText(['NSE:INFY', 'BSE:INFY']);
  await input.press('Enter');
  await expect.poll(() => page.evaluate(() => { const w = (window as any).__feedEvents.widget; return `${w.exchange()}:${w.symbol()}`; })).toBe('NSE:INFY');

  // A failed lookup says so and leaves typed entry working.
  await input.click();
  await input.fill('BROKEN');
  await expect(results.locator('.oac-symbol-picker__status')).toHaveText('Search unavailable');
  await page.screenshot({ path: info.outputPath('symbol-search-failed.png') });
  await input.press('Enter');
  await expect.poll(() => page.evaluate(() => (window as any).__feedEvents.widget.symbol())).toBe('BROKEN');
});

test('event details render feed content as text and run host actions', async ({ page }, info) => {
  await mount(page);
  const point = await page.evaluate(() => {
    const { widget } = (window as any).__feedEvents;
    const bars = widget.series.getData();
    (window as any).__xss = 0;
    widget.chart.setEvents([{
      id: 'q2', time: bars[bars.length - 30].time, type: 'earnings', label: 'E', title: 'Quarterly results (sample data)',
      details: {
        summary: 'Sample event for the reference fixture, not a real announcement.',
        fields: [{ label: 'EPS', value: '31.40' }, { label: 'Revenue', value: '2.31 L Cr' }],
        blocks: [
          { type: 'heading', text: 'Highlights <img src=x onerror="window.__xss=1">' },
          { type: 'paragraph', text: [{ text: 'Margins ' }, { text: 'widened', strong: true }, { text: ' on lower input costs. ', em: true },
            { text: 'Filing', href: 'https://example.com/filings/q2' }, { text: ' and ' }, { text: 'a script link', href: 'javascript:window.__xss=1' }] },
          { type: 'list', items: ['Retail volume up 9%', '<script>window.__xss=1</script>', [{ text: 'Guidance kept', strong: true }]] },
        ],
      },
    }]);
    const rect = document.querySelector('#host .oac-chart')!.getBoundingClientRect();
    return new Promise<{ x: number; y: number } | null>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => {
      const markers = widget.chart.eventMarkers();
      for (let y = 0; y < rect.height; y++) for (let x = 0; x < rect.width; x++) {
        if (markers.hitTest(x, y)) { resolve({ x: rect.left + x, y: rect.top + y }); return; }
      }
      resolve(null);
    })));
  });
  expect(point).not.toBeNull();
  await page.mouse.click(point!.x, point!.y);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.oac-event-details__subhead')).toHaveText('Highlights <img src=x onerror="window.__xss=1">');
  await expect(dialog.locator('.oac-event-details__list li')).toHaveText(['Retail volume up 9%', '<script>window.__xss=1</script>', 'Guidance kept']);
  await expect(dialog.locator('img, script')).toHaveCount(0);
  await expect(dialog.locator('strong')).toHaveText(['widened', 'Guidance kept']);
  const links = dialog.locator('a');
  await expect(links).toHaveCount(1);
  await expect(links).toHaveAttribute('href', 'https://example.com/filings/q2');
  await expect(links).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(links).toHaveAttribute('target', '_blank');
  await expect(dialog).toContainText('Filing and a script link');
  await dialog.getByText('a script link').click();
  expect(await page.evaluate(() => (window as any).__xss)).toBe(0);
  await page.screenshot({ path: info.outputPath('event-details-rich.png') });

  await dialog.getByRole('button', { name: 'Add to watchlist', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect(await page.evaluate(() => (window as any).__feedEvents.actions)).toEqual(['q2']);
});
