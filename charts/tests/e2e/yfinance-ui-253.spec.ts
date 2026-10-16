import { test, expect } from '@playwright/test';

const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=AAPL&interval=1d&period=1mo';
let serverUp: boolean | null = null;

test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
});

test('the right price axis follows newly visible candles with autofit enabled', async ({ page }, info) => {
  await page.evaluate(() => {
    const chart = (window as any).__oac.app.chart;
    chart.primarySeries().setData(Array.from({ length: 200 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100, high: i === 90 ? 250 : 102, low: 98, close: 101,
    })));
    chart.setVisibleLogicalRange({ from: 100, to: 199 });
    chart.setAutoScale(true);
  });
  const settings = page.getByRole('button', { name: 'Chart settings (or right-click the chart)', exact: true });
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Axes', exact: true }).click();
  await page.locator('[data-key="scales.autoScale"]').check();
  await page.locator('#cset-ok').click();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.panes()[0].priceScale.priceRange().max)).toBeLessThan(120);
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('Chart is not visible');
  await page.mouse.move(box.x + 250, box.y + 180);
  await page.mouse.down();
  await page.mouse.move(box.x + 450, box.y + 181, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.panes()[0].priceScale.autoScale)).toBe(true);
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.panes()[0].priceScale.priceRange().max)).toBeGreaterThan(250);
  await info.attach('right axis follows visible candles', {
    body: await page.screenshot({ path: info.outputPath('example-autofit.png') }), contentType: 'image/png',
  });
  await page.mouse.move(box.x + 450, box.y + 181);
  await page.mouse.down();
  await page.mouse.move(box.x + 250, box.y + 180, { steps: 6 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => (window as any).__oac.app.chart.panes()[0].priceScale.priceRange().max)).toBeLessThan(120);
  await info.attach('right axis contracts after the extreme leaves view', {
    body: await page.screenshot({ path: info.outputPath('example-autofit-contracted.png') }), contentType: 'image/png',
  });
  await settings.click();
  await page.locator('#cset-tabs').getByRole('button', { name: 'Axes', exact: true }).click();
  await expect(page.locator('[data-key="scales.autoScale"]')).toBeChecked();
});

test('the selected chart shares a resizable Data and Objects dock', async ({ page }) => {
  const plot = page.locator('#chart');
  const before = await plot.evaluate(element => element.getBoundingClientRect().width);
  await page.getByRole('button', { name: 'Data window', exact: true }).click();
  const dock = page.locator('#inspect-layout-1 .oac-panel-dock');
  await expect(dock).toBeVisible();
  await expect(dock).toContainText('Open');
  expect(await plot.evaluate(element => element.getBoundingClientRect().width)).toBeLessThan(before);
  await page.getByRole('button', { name: 'Chart objects', exact: true }).click();
  await expect(dock.getByRole('searchbox', { name: 'Search objects' })).toBeVisible();
  await dock.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dock).toBeHidden();
});

test('symbol results preserve an explicit venue and direct interval entry owns the focused chart', async ({ page }) => {
  await page.getByRole('button', { name: /^Change symbol, / }).click();
  const input = page.getByPlaceholder('Symbol or expression');
  await input.fill('reliance');
  await page.getByRole('option', { name: /NSE:RELIANCE\.NS/ }).click();
  // The request names the symbol as the load starts, and the host ignores
  // direct entry until that load has finished, so wait for both.
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.req?.symbol === 'RELIANCE.NS' && !app.loading && app.currentBars.length > 0;
  });
  await page.locator('#chart').focus();
  await page.keyboard.press('1');
  const interval = page.locator('.oac-quick-entry__input');
  await expect(interval).toBeVisible();
  await interval.fill('15');
  await interval.press('Enter');
  await page.waitForFunction(() => (window as any).__oac?.app?.req?.interval === '15m');
});

test('the shared indicator picker manages duplicate running instances independently', async ({ page }) => {
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  const ema = page.locator('.oac-pick__row[data-id="ema"]');
  await ema.click();
  await ema.click();
  const before = await page.evaluate(() => (window as any).__oac.app.chart.indicators().filter((item: any) => item.indicatorId === 'ema').map((item: any) => item.id));
  expect(before).toHaveLength(2);
  const running = page.locator(before.map((id: string) => `.oac-pick__running-row[data-instance-id="${id}"]`).join(', '));
  await expect(running).toHaveCount(2);
  await page.locator(`.oac-pick__running-row[data-instance-id="${before[0]}"]`).getByRole('button', { name: /Remove/ }).click();
  const after = await page.evaluate(() => (window as any).__oac.app.chart.indicators().filter((item: any) => item.indicatorId === 'ema').map((item: any) => item.id));
  expect(after).toHaveLength(1);
  expect(before).toContain(after[0]);
});
