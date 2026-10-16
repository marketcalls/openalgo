import { test, expect, type Page } from '@playwright/test';

/**
 * Extended hours in the reference host, against the fixture server: the
 * session menu asks the source for its own pre and post market bars, the
 * chart draws them, and an interval without them is reported with a way back
 * to regular hours instead of regular bars under the extended label.
 */

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

const app = (page: Page, read: string): Promise<unknown> =>
  page.evaluate(expression => new Function('app', `return ${expression}`)((window as any).__oac.app), read);

test('extended hours load as the source serves them and an interval without them says so', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const history: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/history')) history.push(request.url()); });

  // Intraday first: extended hours exist only for intraday bars.
  await page.locator('#shellbar .pills').getByRole('button', { name: '5M', exact: true }).click();
  await expect.poll(() => app(page, 'app.req.interval + ":" + app.currentBars.length + ":" + Boolean(app.loading)')).toMatch(/^5m:\d+:false$/);
  const regularBars = await app(page, 'app.currentBars.length') as number;
  const sessionMenu = page.locator('#session-menu');
  await expect(sessionMenu).toContainText('Regular hours');

  await sessionMenu.click();
  const extendedRow = page.locator('.menu button', { hasText: 'Extended hours' });
  await expect(extendedRow).toBeEnabled();
  await page.screenshot({ path: info.outputPath('host-session-menu.png') });
  await extendedRow.click();
  await expect.poll(() => app(page, 'app.req.session === "extended" && !app.loading && app.currentBars.length')).toBeGreaterThan(regularBars);
  expect(history.some(url => url.includes('interval=5m') && url.includes('session=extended'))).toBe(true);
  expect(await app(page, 'app.chart.getDataContext().variant')).toEqual({ session: 'extended' });
  await expect(sessionMenu).toContainText('Extended hours');
  await page.screenshot({ path: info.outputPath('host-extended.png') });

  // Daily bars have no extended hours here: nothing is fetched as extended,
  // and the card offers the choice that will load.
  const before = history.length;
  await page.locator('#shellbar .pills').getByRole('button', { name: '1D', exact: true }).click();
  const card = page.locator('#chartstate');
  await expect(card).toBeVisible();
  await expect(card).toContainText('Extended hours are not available for AAPL');
  const back = page.locator('#cs-retry');
  await expect(back).toHaveText('Use regular hours');
  expect(history.slice(before).some(url => url.includes('session=extended'))).toBe(false);
  await page.screenshot({ path: info.outputPath('host-session-unsupported.png') });
  await back.click();
  await expect(card).toBeHidden();
  await expect.poll(() => app(page, '!app.loading && app.req.interval === "1d" && app.req.session === undefined && app.currentBars.length')).toBeGreaterThan(0);
  await expect(sessionMenu).toContainText('Regular hours');
  // And the extended row is greyed, with the reason, where it cannot load.
  await sessionMenu.click();
  await expect(page.locator('.menu button', { hasText: 'Extended hours' })).toBeDisabled();
  expect(errors).toEqual([]);
});

test('an extended-hours chart names the pre and post market on its status line', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.locator('#shellbar .pills').getByRole('button', { name: '5M', exact: true }).click();
  await expect.poll(() => app(page, 'app.req.interval + ":" + Boolean(app.loading)')).toBe('5m:false');
  // 07:30 in New York on a Wednesday: the regular market is shut, the extended session trading.
  await page.clock.setFixedTime(new Date('2024-01-10T12:30:00Z'));
  const legend = (): Promise<string> => page.evaluate(() => (window as any).__oac.chart.exportSVG());
  await expect.poll(async () => (await legend()).includes('Market closed')).toBe(true);
  await page.locator('#session-menu').click();
  await page.locator('.menu button', { hasText: 'Extended hours' }).click();
  await expect.poll(() => app(page, 'app.req.session === "extended" && !app.loading')).toBe(true);
  await expect.poll(async () => (await legend()).includes('Pre-market')).toBe(true);
  await page.screenshot({ path: info.outputPath('host-pre-market.png') });
  await page.clock.setFixedTime(new Date('2024-01-10T22:30:00Z'));
  await expect.poll(async () => (await legend()).includes('Post-market')).toBe(true);
  await page.clock.setFixedTime(new Date('2024-01-11T02:30:00Z'));
  await expect.poll(async () => (await legend()).includes('Market closed')).toBe(true);
  expect(errors).toEqual([]);
});
