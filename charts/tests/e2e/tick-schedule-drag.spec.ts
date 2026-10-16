import { expect, test, type Page } from '@playwright/test';
import type { Chart, Instrument, InstrumentMetadata, TickSchedule } from '../../src/index';

declare global {
  interface Window {
    __ticks: {
      chart: Chart; ticks: TickSchedule; banded: InstrumentMetadata;
      Instrument: new (metadata: unknown) => Instrument;
      events: { type: string; id?: string; price?: number; newPrice?: number; previousPrice?: number; orderId?: string; bracketRole?: string }[];
      preview(id: string): number | undefined;
    };
  }
}

const pageErrors = new WeakMap<Page, string[]>();
test.use({ viewport: { width: 1200, height: 900 } });
test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/tests/e2e/tick-schedule-drag-fixture.html');
  await page.waitForFunction(() => !!window.__ticks);
  await paint(page);
});
test.afterEach(async ({ page }, info) => {
  const errors = pageErrors.get(page) ?? [];
  if (info.status !== info.expectedStatus || errors.length) await page.screenshot({ path: info.outputPath('failure.png') });
  expect(errors).toEqual([]);
});

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** A page point on a price, near the right end of the order lines. */
async function point(page: Page, price: number): Promise<{ x: number; y: number; price: number }> {
  return page.evaluate(price => {
    const { chart } = window.__ticks;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    const y = Math.round(rect.top + chart.priceToCoordinate(price, 0)!);
    return { x: Math.round(rect.left + (rect.width - 72) * 0.93), y, price: chart.coordinateToPrice(y - rect.top, 0)! };
  }, price);
}

/** The grid a price lies on: whole cents below 100, whole nickels from 100. */
function onGrid(price: number): boolean {
  const units = price >= 100 ? price * 20 : price * 100;
  return Math.abs(units - Math.round(units)) < 1e-6;
}

test('a dragged order previews and commits the tick of the band it crosses into', async ({ page }, info) => {
  const from = await point(page, 99.5);
  const up = await point(page, 100.33);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(up.x, up.y, { steps: 10 });
  await paint(page);
  const raw = await page.evaluate(() => window.__ticks.events.filter(event => event.type === 'drag').at(-1)!.price!);
  const preview = await page.evaluate(() => window.__ticks.preview('ord:limit')!);
  // The pointer's own price is not on the 0.05 grid; the line is.
  expect(raw).toBeGreaterThan(100);
  expect(preview).toBe(await page.evaluate(price => window.__ticks.ticks.round(price), raw));
  expect(onGrid(preview)).toBe(true);
  expect(Math.round(preview * 100) % 5).toBe(0);
  await page.screenshot({ path: info.outputPath('tick-schedule-drag-upper-band.png') });

  const down = await point(page, 99.73);
  await page.mouse.move(down.x, down.y, { steps: 10 });
  await paint(page);
  const lower = await page.evaluate(() => window.__ticks.preview('ord:limit')!);
  expect(lower).toBeLessThan(100);
  expect(onGrid(lower)).toBe(true);
  await page.mouse.move(up.x, up.y, { steps: 10 });
  await page.mouse.up();
  await paint(page);

  const modify = await page.evaluate(() => window.__ticks.events.filter(event => event.type === 'order'));
  expect(modify).toHaveLength(1);
  expect(modify[0]).toMatchObject({ orderId: 'limit', previousPrice: 99.5, newPrice: preview });
  expect(await page.evaluate(() => window.__ticks.chart.trading.getOrders().find(order => order.id === 'limit')!.price)).toBe(preview);
  await page.screenshot({ path: info.outputPath('tick-schedule-order-released.png') });
});

test('a dragged bracket leg lands on the finer grid below the boundary', async ({ page }, info) => {
  const from = await point(page, 101.5);
  const to = await point(page, 99.87);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.up();
  await paint(page);
  const bracket = await page.evaluate(() => window.__ticks.events.filter(event => event.type === 'bracket'));
  expect(bracket).toHaveLength(1);
  const expected = await page.evaluate(price => window.__ticks.ticks.round(price), to.price);
  expect(bracket[0]).toMatchObject({ bracketRole: 'tp', newPrice: expected });
  expect(bracket[0].newPrice!).toBeLessThan(100);
  expect(onGrid(bracket[0].newPrice!)).toBe(true);
  await page.screenshot({ path: info.outputPath('tick-schedule-bracket-released.png') });
});

/** Drag the limit order from where it rests to `price`; the release's order event and the drag's raw price. */
async function dragOrder(page: Page, price: number): Promise<{ raw: number; newPrice: number }> {
  const current = await page.evaluate(() => window.__ticks.chart.trading.getOrders().find(order => order.id === 'limit')!.price);
  const from = await point(page, current);
  const to = await point(page, price);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(to.x, to.y, { steps: 10 });
  await page.mouse.up();
  await paint(page);
  return page.evaluate(() => {
    const { events } = window.__ticks;
    return { raw: events.filter(event => event.type === 'drag').at(-1)!.price!,
      newPrice: events.filter(event => event.type === 'order').at(-1)!.newPrice! };
  });
}

test('an instrument applied before the trading layer exists snaps its drags until a constant tick replaces it', async ({ page }, info) => {
  await page.goto('/tests/e2e/tick-schedule-drag-fixture.html?via=instrument');
  await page.waitForFunction(() => !!window.__ticks);
  await paint(page);
  const upper = await dragOrder(page, 100.33);
  expect(upper.raw).toBeGreaterThan(100);
  expect(upper.newPrice).toBe(await page.evaluate(price => window.__ticks.ticks.round(price), upper.raw));
  expect(Math.round(upper.newPrice * 100) % 5).toBe(0);
  await page.screenshot({ path: info.outputPath('instrument-applied-drag.png') });

  // The same symbol on a constant tick: no bands are left behind on the drag.
  await page.evaluate(() => {
    const { banded, Instrument, chart } = window.__ticks;
    new Instrument({ ...banded, tickBands: undefined, priceTick: 0.05 }).applyTo(chart, '1m');
  });
  const constant = await dragOrder(page, 99.73);
  expect(constant.newPrice).toBe(constant.raw);
});

test('a dragged price alert lands on the tick of the band it is dropped in', async ({ page }, info) => {
  await page.goto('/tests/e2e/tick-schedule-drag-fixture.html?via=instrument');
  await page.waitForFunction(() => !!window.__ticks);
  const id = await page.evaluate(async () => {
    const { chart } = window.__ticks;
    const lib = await import('/dist/openalgo-charts.mjs' as string);
    const alerts = new lib.AlertController(chart);
    (window as unknown as { __alerts: typeof alerts }).__alerts = alerts;
    return alerts.add({ source: { kind: 'price', price: 99.2 }, title: 'Band alert' }).id as string;
  });
  expect(await page.evaluate(() => window.__ticks.chart.tickSchedule()?.bands.length)).toBe(2);
  await paint(page);
  const stored = () => page.evaluate(alertId => (window as unknown as { __alerts: { list(): { id: string; source: { price: number } }[] } })
    .__alerts.list().find(alert => alert.id === alertId)!.source.price, id);
  // Well left of the order pills, which sit near the price axis.
  const grab = async (price: number) => { const p = await point(page, price); return { x: p.x - 500, y: p.y, price: p.price }; };
  const from = await grab(99.2), up = await grab(100.33);
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move(up.x, up.y, { steps: 10 });
  await page.mouse.up();
  await paint(page);
  const upper = await stored();
  expect(upper).toBeGreaterThan(100);
  // A 0.05 band: the axis grid alone (0.01) would have accepted 100.33.
  expect(Math.round(upper * 100) % 5).toBe(0);
  expect(upper).toBe(await page.evaluate(price => window.__ticks.ticks.round(price), up.price));
  await page.screenshot({ path: info.outputPath('tick-schedule-alert-upper-band.png') });

  const back = await grab(upper), down = await grab(99.63);
  await page.mouse.move(back.x, back.y);
  await page.mouse.down();
  await page.mouse.move(down.x, down.y, { steps: 10 });
  await page.mouse.up();
  await paint(page);
  const lower = await stored();
  expect(lower).toBeLessThan(100);
  expect(onGrid(lower)).toBe(true);
  expect(lower).toBe(await page.evaluate(price => window.__ticks.ticks.round(price), down.price));
});

/**
 * Docks a ladder over a book that straddles the boundary (cent bids below 100,
 * nickel asks from it) and records chart clicks. `tickSize` crosses into the
 * page as given, so a test can hand over what a plain-JS host would.
 */
async function mountLadder(page: Page, tickSize: unknown, withSchedule: boolean): Promise<void> {
  await page.evaluate(async ({ tickSize, withSchedule }) => {
    const { chart, ticks } = window.__ticks;
    const trade = await import('/dist/openalgo-charts.trade.mjs' as string);
    chart.panes()[0].priceScale.setFixedRange({ min: 99.78, max: 100.38 });
    const ladder = new trade.DomLadder({ tickSize, tickSchedule: withSchedule ? ticks : undefined, width: 120, rowHeight: 12 });
    chart.addPrimitive(ladder);
    ladder.setDepth({
      ltp: 99.99,
      bids: Array.from({ length: 20 }, (_, i) => ({ price: +(99.99 - i * 0.01).toFixed(2), qty: 40 + i * 7 })),
      asks: Array.from({ length: 8 }, (_, i) => ({ price: +(100 + i * 0.05).toFixed(2), qty: 60 + i * 11 })),
    });
    const ids: (string | null)[] = [];
    chart.on('click', event => ids.push((event as { id: string | null }).id));
    (window as unknown as { __clicks: (string | null)[] }).__clicks = ids;
  }, { tickSize, withSchedule });
  await paint(page);
}

/** Clicks the ladder strip at a price and returns the id the chart reported. */
async function clickLadder(page: Page, price: number): Promise<string | null> {
  const at = await page.evaluate(price => {
    const { chart } = window.__ticks;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    return { x: Math.round(rect.left + rect.width - 72 - 30), y: Math.round(rect.top + chart.priceToCoordinate(price, 0)!) };
  }, price);
  await page.mouse.click(at.x, at.y);
  await paint(page);
  return page.evaluate(() => (window as unknown as { __clicks: (string | null)[] }).__clicks.at(-1) ?? null);
}

test('a depth ladder across the boundary shows the rows each band allows', async ({ page }, info) => {
  // The upper band's tick as tickSize: without the schedule, the cent levels
  // below 100 would fold into nickel rows and 99.97 would have no row.
  await mountLadder(page, 0.05, true);
  // A cent row below the boundary and a nickel row above it, each a price the band allows.
  expect(await clickLadder(page, 99.97)).toBe('ladder-bid:99.97');
  expect(await clickLadder(page, 99.99)).toBe('ladder-bid:99.99');
  expect(await clickLadder(page, 100.15)).toBe('ladder-ask:100.15');
  // Between two nickel rows there is no row: 100.07 is not a price the upper band allows.
  expect(await clickLadder(page, 100.075)).toBeNull();
  await page.screenshot({ path: info.outputPath('tick-schedule-ladder.png') });
});

test('a ladder given its tick size as a numeric string draws the rows it did before schedules', async ({ page }, info) => {
  // A plain-JS host can read the tick from a form field or a query string.
  await mountLadder(page, '0.05', false);
  // Constant nickel rows, as a numeric 0.05 gives: the cent bids fold into them.
  expect(await clickLadder(page, 99.95)).toBe('ladder-bid:99.95');
  expect(await clickLadder(page, 100.15)).toBe('ladder-ask:100.15');
  expect(await clickLadder(page, 99.97)).toBeNull();
  await page.screenshot({ path: info.outputPath('string-tick-ladder.png') });
});
