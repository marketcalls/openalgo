import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type * as Charts from '../../src/index';
import type * as Widgets from '../../src/widget/index';

// Go to a date or range in both hosts. The widget half serves daily sessions
// stamped at the 09:15 open by date window, so a date before the first load
// needs one reach of older history; the reference half widens its period.
// Both check where the view landed by time, and that the plot is painted
// there rather than left on an empty stretch of axis.

const ORIGIN = `http://127.0.0.1:${process.env.OAC_E2E_DEMO_PORT || '8124'}`;
let referenceUp: boolean | null = null;

/** The reference host runs on a Python fixture server that not every machine has; skip, do not fail, without it. */
async function openReference(page: Page, request: APIRequestContext) {
  if (referenceUp === null) referenceUp = await request.get(ORIGIN + '/api/history?symbol=AAPL&interval=1d&period=1mo').then(r => r.ok(), () => false);
  test.skip(!referenceUp, 'Reference fixture server needs Python 3');
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto(ORIGIN + '/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => (window as any).__oac?.app.chart && !(window as any).__oac.app.loading);
  return errors;
}

/** A date `days` back, as the chart's own calendar names it. */
async function daysBack(page: Page, days: number): Promise<string> {
  return page.evaluate((back: number) => {
    const zone = (window as any).__oac.app.chart.timezone();
    return new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' })
      .format(new Date(Date.now() - back * 86400_000));
  }, days);
}

declare global {
  interface Window {
    __goto: { widget: Widget; requests: number; release(): void; at(y: number, m: number, d: number, hh?: number, mm?: number): number };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

/** `gated` holds every request after the first until `__goto.release()`. */
async function mountWidget(page: Page, width: number, setup: { interval?: string; theme?: 'dark' | 'light'; gated?: boolean } = {}) {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 760 });
  await page.route('**/date-navigation.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#0d0e12}#host{position:absolute;inset:0}</style></head><body><div id="host"></div></body></html>' }));
  await page.goto('/date-navigation.html');
  await page.evaluate(async ({ interval, theme, gated }) => {
    const lib = await import('/dist/openalgo-charts.mjs' as string) as typeof Charts;
    const widgets = await import('/dist/openalgo-charts.widget.mjs' as string) as typeof Widgets;
    const at = (y: number, m: number, d: number, hh = 0, mm = 0): number => lib.zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, 'Asia/Kolkata');
    const sessions: Charts.Bar[] = [];
    for (let day = 0; ; day++) {
      const time = at(2023, 1, 2 + day, 9, 15);
      if (time > at(2024, 6, 28, 23, 59)) break;
      const weekday = new Date((time + 19800) * 1000).getUTCDay();
      if (weekday === 0 || weekday === 6) continue;
      const close = 100 + Math.sin(sessions.length / 7) * 8 + sessions.length * 0.05;
      sessions.push({ time, open: close - 0.5, high: close + 1.2, low: close - 1.4, close: close + 0.4, volume: 1000 + sessions.length });
    }
    let open!: () => void;
    const gate = new Promise<void>(resolve => { open = resolve; });
    const state = { widget: null as unknown as Widget, requests: 0, at, release: () => open() };
    state.widget = widgets.createWidget(document.getElementById('host')!, {
      feed: { getBars: async request => {
        if (++state.requests > 1 && gated) await gate;
        return sessions.filter(value => value.time >= (request.from ?? -Infinity) && value.time <= (request.to ?? Infinity));
      } },
      symbol: 'SESSIONS', exchange: 'NSE', interval, lookbackBars: 60, theme, rail: false,
      now: () => at(2024, 6, 28, 16, 0) * 1000, animZoom: false, animAutoscale: false,
    });
    window.__goto = state;
    await new Promise<void>(resolve => { state.widget.on('data', () => resolve()); });
  }, { interval: setup.interval ?? '1d', theme: setup.theme ?? 'dark', gated: setup.gated ?? false });
  await paint(page);
  return errors;
}

async function openPanel(page: Page, width: number) {
  if (width > 640) await page.getByRole('button', { name: 'Go to', exact: true }).click();
  else {
    await page.locator('[data-mobile-action="more"]').click();
    await page.locator('[data-mobile-action="go-to"]').click();
  }
  const panel = page.locator('.oac-goto');
  await expect(panel).toBeVisible();
  const box = await panel.boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width + 0.5);
  return panel;
}

/** Bar time at the centre of the view, and how many plot pixels differ from the background there. */
async function landing(page: Page) {
  return page.evaluate(() => {
    const chart = window.__goto.widget.chart;
    const view = chart.getVisibleLogicalRange();
    const centre = chart.dataLayer.indexToTime(Math.round((view.from + view.to) / 2));
    const shot = chart.takeScreenshot();
    const ctx = shot.getContext('2d')!;
    const x = Math.round(shot.width * 0.4);
    const band = ctx.getImageData(x, 0, Math.round(shot.width * 0.2), shot.height).data;
    const bg = ctx.getImageData(1, 1, 1, 1).data;
    let painted = 0;
    for (let i = 0; i < band.length; i += 4) {
      if (Math.abs(band[i] - bg[0]) + Math.abs(band[i + 1] - bg[1]) + Math.abs(band[i + 2] - bg[2]) > 60) painted++;
    }
    return { centre, painted, range: view };
  });
}

for (const width of [1100, 390]) {
  test(`widget go-to loads missing history and paints the placed date at ${width}px`, async ({ page }, info) => {
    const errors = await mountWidget(page, width);
    const before = await page.evaluate(() => window.__goto.requests);
    const panel = await openPanel(page, width);
    await panel.locator('input[type=date]').first().fill('2023-10-16');
    // Daily bars: a date names its bar, so the panel offers no time to type.
    await expect(panel.locator('input[type=time]').first()).toBeHidden();
    await panel.getByRole('button', { name: 'Go', exact: true }).click();
    await expect(panel).toBeHidden();
    await paint(page);
    const placed = await landing(page);
    expect(placed.centre).toBe(await page.evaluate(() => window.__goto.at(2023, 10, 16, 9, 15)));
    expect(await page.evaluate(() => window.__goto.requests)).toBe(before + 1);
    expect(placed.painted).toBeGreaterThan(200);
    await page.screenshot({ path: info.outputPath('placed.png') });
    expect(errors).toEqual([]);
  });
}

test('widget go-to explains an empty request in place and fits a range', async ({ page }, info) => {
  const errors = await mountWidget(page, 1100);
  const view = await page.evaluate(() => window.__goto.widget.chart.getVisibleLogicalRange());
  let panel = await openPanel(page, 1100);
  await panel.locator('input[type=date]').first().fill('2030-01-01');
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  await expect(panel.locator('.oac-goto__message')).toContainText('No bars at or after');
  expect(await page.evaluate(() => window.__goto.widget.chart.getVisibleLogicalRange())).toEqual(view);
  await page.screenshot({ path: info.outputPath('no-data.png') });

  await panel.getByRole('button', { name: 'Range', exact: true }).click();
  const dates = panel.locator('input[type=date]');
  await dates.nth(0).fill('2024-03-04');
  await dates.nth(1).fill('2024-03-28');
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  await expect(panel).toBeHidden();
  await paint(page);
  const edges = await page.evaluate(() => {
    const chart = window.__goto.widget.chart;
    const range = chart.getVisibleLogicalRange();
    return [chart.dataLayer.indexToTime(Math.ceil(range.from)), chart.dataLayer.indexToTime(Math.floor(range.to))];
  });
  expect(edges).toEqual(await page.evaluate(() => [window.__goto.at(2024, 3, 4, 9, 15), window.__goto.at(2024, 3, 28, 9, 15)]));
  expect((await landing(page)).painted).toBeGreaterThan(200);
  await page.screenshot({ path: info.outputPath('range.png') });

  panel = await openPanel(page, 1100);
  await expect(panel.getByRole('button', { name: 'Range', exact: true })).toHaveAttribute('aria-pressed', 'false');
  expect(errors).toEqual([]);
});

test('widget go-to panel closed while loading leaves the view where the user left it', async ({ page }, info) => {
  const errors = await mountWidget(page, 1100, { gated: true });
  // The view as the user left it: the time of its rightmost bar, and its bar
  // spacing. Not the middle of the view: the first page is shorter than the
  // default view, so the middle can fall before the first bar and name no time.
  // A placement that went ahead would move the right edge to the requested date.
  const edge = () => page.evaluate(() => {
    const chart = window.__goto.widget.chart;
    const view = chart.getVisibleLogicalRange();
    const last = chart.primaryBars().length - 1;
    return { time: chart.dataLayer.indexToTime(Math.min(Math.floor(view.to), last)), spacing: chart.timeScale.barSpacing };
  });
  const panel = await openPanel(page, 1100);
  await panel.locator('input[type=date]').first().fill('2023-10-16');
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  await expect(panel.locator('.oac-goto__message')).toHaveText('Loading history');
  const shown = await edge();
  expect(shown.time).toBeDefined();
  await panel.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(panel).toBeHidden();
  await page.evaluate(() => window.__goto.release());
  await expect.poll(() => page.evaluate(() => window.__goto.widget.series.getData()[0].time))
    .toBeLessThanOrEqual(await page.evaluate(() => window.__goto.at(2023, 10, 16)));
  await paint(page);
  expect(await edge()).toEqual(shown);
  await expect(page.locator('.oac-statusline')).not.toContainText('Showing');
  await page.screenshot({ path: info.outputPath('dismissed.png') });
  expect(errors).toEqual([]);
});

test('widget go-to request is dropped by a wheel zoom while history loads', async ({ page }, info) => {
  const errors = await mountWidget(page, 1100, { gated: true });
  const panel = await openPanel(page, 1100);
  await panel.locator('input[type=date]').first().fill('2023-10-16');
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  const message = panel.locator('.oac-goto__message');
  await expect(message).toHaveText('Loading history');
  // Over the plot, well clear of the panel: a wheel is no outside press, so the panel stays.
  const plot = await page.locator('.oac-chart').boundingBox();
  await page.mouse.move(plot!.x + plot!.width * 0.3, plot!.y + plot!.height * 0.6);
  await page.mouse.wheel(0, -240);
  await expect(message).toHaveText('');
  await expect(panel).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Go', exact: true })).toBeEnabled();
  const zoomed = await page.evaluate(() => {
    const chart = window.__goto.widget.chart;
    const view = chart.getVisibleLogicalRange();
    return { span: view.to - view.from, first: chart.primaryBars()[0].time, from: view.from - chart.dataLayer.timeToIndex(chart.primaryBars()[0].time)! };
  });
  await page.evaluate(() => window.__goto.release());
  await expect.poll(() => page.evaluate(() => window.__goto.widget.series.getData()[0].time))
    .toBeLessThanOrEqual(await page.evaluate(() => window.__goto.at(2023, 10, 16)));
  await paint(page);
  const after = await page.evaluate((first: number) => {
    const chart = window.__goto.widget.chart;
    const view = chart.getVisibleLogicalRange();
    return { span: view.to - view.from, from: view.from - chart.dataLayer.timeToIndex(first)! };
  }, zoomed.first);
  expect(after.span).toBeCloseTo(zoomed.span, 6);
  expect(after.from).toBeCloseTo(zoomed.from, 6);
  await expect(page.locator('.oac-statusline')).not.toContainText('Showing');
  await page.screenshot({ path: info.outputPath('zoomed-during-load.png') });
  expect(errors).toEqual([]);
});

test('widget go-to panel closes when the interval changes under it', async ({ page }, info) => {
  const errors = await mountWidget(page, 1100, { interval: '1h' });
  let panel = await openPanel(page, 1100);
  await expect(panel.locator('input[type=time]').first()).toBeVisible();
  // Changed through the API: no press lands outside the panel to close it.
  await page.evaluate(() => new Promise<void>(resolve => {
    window.__goto.widget.on('data', () => resolve());
    window.__goto.widget.setInterval('1d');
  }));
  await expect(page.locator('.oac-goto')).toHaveCount(0);
  panel = await openPanel(page, 1100);
  await expect(panel.locator('input[type=time]').first()).toBeHidden();
  await expect(panel.locator('.oac-goto__hint')).toHaveText('Dates are in Asia/Kolkata.');
  await page.screenshot({ path: info.outputPath('interval-changed.png') });
  expect(errors).toEqual([]);
});

test('widget go-to panel offers a time on an intraday chart in the light theme', async ({ page }, info) => {
  const errors = await mountWidget(page, 1100, { interval: '1h', theme: 'light' });
  const panel = await openPanel(page, 1100);
  const time = panel.locator('input[type=time]').first();
  await expect(time).toBeVisible();
  await expect(panel.locator('.oac-goto__hint')).toContainText('Times are in Asia/Kolkata.');
  const [box, card] = [await time.boundingBox(), await panel.boundingBox()];
  expect(box!.width).toBeGreaterThan(60);
  expect(box!.x + box!.width).toBeLessThanOrEqual(card!.x + card!.width);
  await page.screenshot({ path: info.outputPath('intraday-light.png') });
  expect(errors).toEqual([]);
});

test('reference host go-to widens its period and places the date', async ({ page, request }, info) => {
  const errors = await openReference(page, request);
  // A daily chart opens on five years and its range menu offers nothing
  // shorter, so a date six years back needs the longest period.
  await page.getByRole('button', { name: 'History range' }).click();
  await expect(page.locator('.menu button')).toHaveText([/^5y/, /^max/]);
  await page.locator('.menu button', { hasText: '5y' }).click();
  await page.waitForFunction(() => (window as any).__oac.app.req.period === '5y' && !(window as any).__oac.app.loading);
  const target = await daysBack(page, 6 * 366);
  await page.locator('.host-bottombar .oac-bottombar__goto').click();
  const panel = page.locator('.oac-goto');
  await expect(panel).toBeVisible();
  await expect(panel.locator('input[type=time]')).toHaveCount(2);
  await expect(panel.locator('input[type=time]').first()).toBeHidden();
  await panel.locator('input[type=date]').first().fill(target);
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  // The rebuild takes the first panel with the old chart; the answer is the status line, then no panel at all.
  await expect(page.locator('#status')).toHaveText(/^Showing /, { timeout: 20_000 });
  await expect(page.locator('.oac-goto')).toHaveCount(0);
  const outcome = await page.evaluate(async (day: string) => {
    const lib = await import('/dist/openalgo-charts.mjs' as string) as typeof Charts;
    const app = (window as any).__oac.app;
    const chart = app.chart as Charts.Chart;
    const zone = chart.timezone();
    const [y, m, d] = day.split('-').map(Number);
    const start = lib.zonedWallClockToUtcSeconds(y, m, d, 0, 0, 0, zone);
    const expected = chart.primaryBars().find(value => lib.startOfZonedDay(value.time, zone) + 86400 > start)?.time;
    const view = chart.getVisibleLogicalRange();
    return { period: app.req.period, expected, centre: chart.dataLayer.indexToTime(Math.round((view.from + view.to) / 2)), first: chart.primaryBars()[0].time, start };
  }, target);
  expect(outcome.period).toBe('max');
  expect(outcome.first).toBeLessThanOrEqual(outcome.start);
  expect(outcome.centre).toBe(outcome.expected);
  await page.screenshot({ path: info.outputPath('reference-placed.png') });
  expect(errors).toEqual([]);
});

test('reference host reports short history in the panel it reopens after the rebuild', async ({ page, request }, info) => {
  const errors = await openReference(page, request);
  // An hourly frame goes back a year at most, so three years back cannot be reached.
  await page.evaluate(async () => {
    const app = (window as any).__oac.app;
    (document.getElementById('interval') as HTMLSelectElement).value = '1h';
    (document.getElementById('period') as HTMLSelectElement).value = '1mo';
    await app.load();
  });
  await page.waitForFunction(() => (window as any).__oac.app.req.interval === '1h' && !(window as any).__oac.app.loading);
  const target = await daysBack(page, 3 * 366);
  await page.locator('.host-bottombar .oac-bottombar__goto').click();
  let panel = page.locator('.oac-goto');
  await panel.locator('input[type=date]').first().fill(target);
  await panel.locator('input[type=time]').first().fill('');
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  panel = page.locator('.oac-goto');
  await expect(panel.locator('.oac-goto__message')).toHaveText(/^History starts at /, { timeout: 20_000 });
  expect(await page.evaluate(() => (window as any).__oac.app.req.period)).toBe('1y');
  await expect(panel.locator('input[type=date]').first()).toHaveValue(target);
  await page.screenshot({ path: info.outputPath('reference-short-history.png') });
  expect(errors).toEqual([]);
});

test('reference host drops a go-to request on a wheel zoom while the longer period loads', async ({ page, request }, info) => {
  const errors = await openReference(page, request);
  await page.waitForFunction(() => (window as any).__oac.app.req.period === '5y' && !(window as any).__oac.app.loading);
  // Hold the longer period on the wire, so the zoom lands while it loads.
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/history**', async route => { await held; await route.continue(); });
  // Six years back needs max, which nothing has fetched yet. A period the page
  // already loaded comes from the bar cache with no request, so nothing would
  // be on the wire to hold and the load would finish before any zoom.
  const target = await daysBack(page, 6 * 366);
  await page.locator('.host-bottombar .oac-bottombar__goto').click();
  const panel = page.locator('.oac-goto');
  await panel.locator('input[type=date]').first().fill(target);
  await panel.getByRole('button', { name: 'Go', exact: true }).click();
  const message = panel.locator('.oac-goto__message');
  await expect(message).toHaveText('Loading history');
  const plot = await page.locator('#chart').boundingBox();
  await page.mouse.move(plot!.x + plot!.width * 0.3, plot!.y + plot!.height * 0.7);
  await page.mouse.wheel(0, -240);
  await expect(message).toHaveText('');
  release();
  await page.waitForFunction(() => (window as any).__oac.app.req.period === 'max' && !(window as any).__oac.app.loading, undefined, { timeout: 20_000 });
  // The rebuild takes the panel, and a dropped request is not reopened.
  await expect(page.locator('.oac-goto')).toHaveCount(0);
  await expect(page.locator('#status')).not.toHaveText(/^Showing /);
  await page.screenshot({ path: info.outputPath('reference-zoomed-during-load.png') });
  expect(errors).toEqual([]);
});
