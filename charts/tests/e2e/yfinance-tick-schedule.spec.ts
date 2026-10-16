import { test, expect, type Page } from '@playwright/test';

// The reference host on the fixture server's BANDED instrument: 0.01 below
// 100 and 0.05 from 100, rules the host supplies from src/ticks.js.
const PAGE = '/examples/yfinance/index.html?test=1';
const PROBE = '/api/history?symbol=BANDED&interval=1d&period=1mo';
let serverUp: boolean | null = null;

interface HostOrder { price: number }
interface HostBracket { entry: number; target: number; stop: number }
interface HostTicks { round(price: number): number; step(price: number, ticks: number): number; minMove: number }

test.use({ viewport: { width: 1280, height: 900 } });
test.beforeEach(async ({ request, page }) => {
  if (serverUp === null) serverUp = await request.get(PROBE).then(response => response.ok(), () => false);
  test.skip(!serverUp, 'The reference fixture server is unavailable');
  await page.goto(PAGE);
  await page.waitForFunction(() => Boolean((window as any).__oac?.app?.currentBars?.length));
  await page.locator('#shellbar button', { hasText: 'AAPL' }).click();
  const symbol = page.getByPlaceholder('Symbol or expression');
  await symbol.fill('BANDED');
  await expect(symbol).toHaveAttribute('aria-expanded', 'false');
  await symbol.press('Enter');
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.req?.symbol === 'BANDED' && !app.loading && app.currentBars.length > 0 && app.ticks !== null;
  });
});

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** Keep the boundary on screen: the fixture's latest bars can sit either side of it. */
async function pinRange(page: Page, min: number, max: number): Promise<void> {
  await page.evaluate(({ min, max }) => (window as any).__oac.app.chart.panes()[0].priceScale.setFixedRange({ min, max }), { min, max });
  await paint(page);
}

async function point(page: Page, price: number, across = 0.93): Promise<{ x: number; y: number; price: number }> {
  return page.evaluate(({ price, across }) => {
    const chart = (window as any).__oac.app.chart;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    const y = Math.round(rect.top + chart.priceToCoordinate(price, 0));
    return { x: Math.round(rect.left + (rect.width - 72) * across), y, price: chart.coordinateToPrice(y - rect.top, 0) };
  }, { price, across });
}

const round = (page: Page, price: number): Promise<number> =>
  page.evaluate(price => ((window as any).__oac.app.ticks as HostTicks).round(price), price);
const onGrid = (price: number): boolean => {
  const units = price >= 100 ? price * 20 : price * 100;
  return Math.abs(units - Math.round(units)) < 1e-6;
};
const orders = (page: Page): Promise<HostOrder[]> => page.evaluate(() => (window as any).__oac.app.orders.map((o: HostOrder) => ({ price: o.price })));
const status = (page: Page): Promise<string> => page.locator('#status').innerText();

test('right-click entry and a dragged order line follow the band each price is in', async ({ page }, info) => {
  // The host instrument's price tick, the grid both bands lie on. The market
  // guess for this symbol is 0.01 too, so this is a smoke check only: the
  // choice between them is covered by examples/yfinance/tests/ticks.test.js.
  expect(await page.evaluate(() => (window as any).__oac.app.chart.panes()[0].priceScale.options.minMove)).toBe(0.01);
  await pinRange(page, 99, 101);
  const upper = await point(page, 100.33, 0.5);
  await page.mouse.click(upper.x, upper.y, { button: 'right' });
  const buy = page.locator('#ctxmenu button[data-side="BUY"][data-type="LIMIT"]');
  await expect(buy).toBeVisible();
  const menuPrice = Number((await buy.innerText()).replace(/^Buy limit @ /, '').replace(/,/g, ''));
  expect(menuPrice).toBe(await round(page, upper.price));
  expect(Math.round(menuPrice * 100) % 5).toBe(0);
  await buy.click();
  expect((await orders(page))[0].price).toBe(menuPrice);
  expect(await status(page)).toContain(', tick 0.05');

  const from = await point(page, menuPrice);
  const lower = await point(page, 99.63);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(lower.x, lower.y, { steps: 12 });
  await page.mouse.up();
  await paint(page);
  const dropped = (await orders(page))[0].price;
  expect(dropped).toBe(await round(page, lower.price));
  expect(dropped).toBeLessThan(100);
  expect(onGrid(dropped)).toBe(true);
  expect(await status(page)).toMatch(/order -> 99\.\d\d, tick 0\.01$/);
  await page.screenshot({ path: info.outputPath('host-order-lower-band.png') });

  const back = await point(page, 100.41);
  const at = await point(page, dropped);
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(back.x, back.y, { steps: 12 });
  await page.mouse.up();
  await paint(page);
  const raised = (await orders(page))[0].price;
  expect(raised).toBe(await round(page, back.price));
  expect(Math.round(raised * 100) % 5).toBe(0);
  expect(await status(page)).toMatch(/, tick 0\.05$/);
  await page.screenshot({ path: info.outputPath('host-order-upper-band.png') });
});

test('bracket legs snap in their own band and keep one tick from the entry', async ({ page }, info) => {
  await page.locator('#shellbar .tbtn--buy').click();
  await page.waitForFunction(() => (window as any).__oac.app.bracket !== null);
  const opened = await page.evaluate(() => (window as any).__oac.app.bracket as HostBracket);
  for (const price of [opened.entry, opened.target, opened.stop]) expect(onGrid(price)).toBe(true);
  await pinRange(page, Math.min(opened.stop, 99) - 0.5, Math.max(opened.target, 101) + 0.5);
  // The entry pill moves the whole bracket; its Qty label is not a button.
  const handle = page.locator('#bk-entry span').first();
  const box = (await handle.boundingBox())!;
  const target = await point(page, 100.33);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, target.y, { steps: 14 });
  await page.mouse.up();
  await paint(page);
  const moved = await page.evaluate(() => (window as any).__oac.app.bracket as HostBracket);
  expect(moved.entry).toBeGreaterThanOrEqual(100);
  expect(Math.round(moved.entry * 100) % 5).toBe(0);
  for (const price of [moved.target, moved.stop]) expect(onGrid(price)).toBe(true);
  expect(moved.target).toBeGreaterThan(moved.entry);
  expect(moved.stop).toBeLessThan(moved.entry);

  // Dragging the stop above the entry parks it one tick below, in the band below the entry.
  const stopHandle = page.locator('#bk-sl span').first();
  const stopBox = (await stopHandle.boundingBox())!;
  const above = await point(page, moved.entry + 0.5);
  await page.mouse.move(stopBox.x + stopBox.width / 2, stopBox.y + stopBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(stopBox.x + stopBox.width / 2, above.y, { steps: 14 });
  await page.mouse.up();
  await paint(page);
  const parked = await page.evaluate(() => (window as any).__oac.app.bracket as HostBracket);
  expect(parked.stop).toBe(await page.evaluate(entry => ((window as any).__oac.app.ticks as HostTicks).step(entry, -1), parked.entry));
  await page.screenshot({ path: info.outputPath('host-bracket-across-boundary.png') });
});

test('a price alert dragged into the upper band lands on the tick of that band', async ({ page }, info) => {
  await pinRange(page, 99, 101);
  expect(await page.evaluate(() => (window as any).__oac.app.chart.tickSchedule()?.bands.length)).toBe(2);
  const id = await page.evaluate(() => (window as any).__oac.app.alerts.add({ source: { kind: 'price', price: 99.4 }, title: 'Band alert' }).id);
  await paint(page);
  const stored = (): Promise<number> => page.evaluate(alertId => (window as any).__oac.app.alerts.list()
    .find((alert: { id: string }) => alert.id === alertId).source.price, id);
  const from = await point(page, 99.4, 0.35), to = await point(page, 100.33, 0.35);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.up();
  await paint(page);
  const dropped = await stored();
  expect(dropped).toBeGreaterThan(100);
  expect(Math.round(dropped * 100) % 5).toBe(0);
  expect(dropped).toBe(await round(page, to.price));
  await page.screenshot({ path: info.outputPath('host-alert-upper-band.png') });
});
