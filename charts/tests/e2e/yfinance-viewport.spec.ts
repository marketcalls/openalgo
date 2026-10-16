import { test, expect, type Page } from '@playwright/test';

/**
 * The reference host's pin toggle, in a real browser: a box pinned from the
 * properties bar keeps its pixels while the chart pans under it, and unpinning
 * puts it back on the bars it covers. And the space right of the last candle
 * on an intraday chart, which the host lays out in the venue's trading hours.
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

type Box = { x0: number; y0: number; x1: number; y1: number; count: number };

/** Bounding box of the magenta outline on the main pane's top canvas, in device px. */
async function magenta(page: Page): Promise<Box> {
  return page.locator('#chart canvas').nth(1).evaluate(element => {
    const c = element as HTMLCanvasElement;
    const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    const box = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity, count: 0 };
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        if (data[i + 3] < 120 || data[i] < 180 || data[i + 1] > 90 || data[i + 2] < 180) continue;
        box.count++;
        box.x0 = Math.min(box.x0, x); box.y0 = Math.min(box.y0, y);
        box.x1 = Math.max(box.x1, x); box.y1 = Math.max(box.y1, y);
      }
    }
    return box;
  });
}

test('the pin toggle keeps a box in place through a pan, and unpinning returns it to the bars', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const id = await page.evaluate(() => {
    const app = (window as any).__oac.app;
    const bars = app.currentBars;
    const a = bars[bars.length - 40];
    const b = bars[bars.length - 20];
    const drawing = app.draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 4 },
      points: [{ time: a.time, price: Math.max(a.high, b.high) }, { time: b.time, price: Math.min(a.low, b.low) }] });
    app.draw.select(drawing.id);
    return drawing.id;
  });
  const pin = page.locator('#propbar [data-path="space"]');
  await expect(pin).toBeVisible();
  await expect(pin).toHaveAttribute('aria-pressed', 'false');
  await pin.click();
  await expect(pin).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#propbar').screenshot({ path: info.outputPath('host-pinned-bar.png') });
  expect(await page.evaluate(i => (window as any).__oac.app.draw.get(i).space, id)).toBe('viewport');
  // Deselect so the handles and the bar are out of the pixels.
  await page.evaluate(() => (window as any).__oac.app.draw.select(null));
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('Chart is not visible');
  await page.mouse.move(box.x + 5, box.y + 5);
  await expect.poll(async () => (await magenta(page)).count).toBeGreaterThan(20);
  const before = await magenta(page);
  await page.screenshot({ path: info.outputPath('host-before-pan.png') });
  const range0 = await page.evaluate(() => (window as any).__oac.app.chart.getVisibleLogicalRange());
  await page.mouse.move(box.x + 120, box.y + box.height - 90);
  await page.mouse.down();
  await page.mouse.move(box.x + 420, box.y + box.height - 90, { steps: 10 });
  await page.mouse.up();
  await page.mouse.move(box.x + 5, box.y + 5);
  const range1 = await page.evaluate(() => (window as any).__oac.app.chart.getVisibleLogicalRange());
  expect(Math.abs(range1.from - range0.from)).toBeGreaterThan(3);
  await page.screenshot({ path: info.outputPath('host-after-pan.png') });
  const after = await magenta(page);
  for (const key of ['x0', 'y0', 'x1', 'y1'] as const) expect(Math.abs(after[key] - before[key])).toBeLessThanOrEqual(1);
  // Unpin: back on time and price, under the same pixels it was pinned at.
  await page.evaluate(i => (window as any).__oac.app.draw.select(i), id);
  await pin.click();
  await expect(pin).toHaveAttribute('aria-pressed', 'false');
  const back = await page.evaluate(i => (window as any).__oac.app.draw.get(i), id);
  expect(back.space).toBeUndefined();
  expect(back.points).toHaveLength(2);
  expect(errors).toEqual([]);
});

test('the pin toggle says why a drawing on a folded pane did not move, and pins it once the pane is open', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const { id, paneIndex } = await page.evaluate(() => {
    const app = (window as any).__oac.app;
    const bars = app.currentBars;
    const study = app.chart.addIndicator('rsi', { length: 14 });
    const a = bars[bars.length - 40];
    const b = bars[bars.length - 20];
    const drawing = app.draw.add({ tool: 'rectangle', paneIndex: study.paneIndex, style: { color: '#ff00ff', lineWidth: 4 },
      points: [{ time: a.time, price: 65 }, { time: b.time, price: 35 }] });
    app.draw.select(drawing.id);
    return { id: drawing.id, paneIndex: study.paneIndex };
  });
  expect(paneIndex).toBeGreaterThan(0);
  expect(await page.evaluate(p => (window as any).__oac.app.chart.setPaneCollapsed(p, true), paneIndex)).toBe(true);
  const pin = page.locator('#propbar [data-path="space"]');
  await expect(pin).toBeVisible();
  await pin.click();
  await expect(page.locator('#toasts .toast__msg')).toHaveText(['A drawing can be pinned only while its pane is on screen']);
  await expect(pin).toHaveAttribute('aria-pressed', 'false');
  expect(await page.evaluate(i => (window as any).__oac.app.draw.get(i).space, id)).toBeUndefined();
  await page.screenshot({ path: info.outputPath('host-pin-refused.png') });
  expect(await page.evaluate(p => (window as any).__oac.app.chart.setPaneCollapsed(p, false), paneIndex)).toBe(true);
  await page.evaluate(i => (window as any).__oac.app.draw.select(i), id);
  await pin.click();
  await expect(pin).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(i => (window as any).__oac.app.draw.get(i).space, id)).toBe('viewport');
  await expect(page.locator('#toasts .toast__msg')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('on an intraday NSE chart, a trend line drawn past the last candle ends on the next session\'s bars', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(async () => {
    (document.getElementById('symbol') as HTMLInputElement).value = 'RELIANCE.NS';
    (document.getElementById('interval') as HTMLSelectElement).value = '5m';
    await (window as any).__oac.app.load();
  });
  await page.waitForFunction(() => {
    const app = (window as any).__oac?.app;
    return app?.req?.symbol === 'RELIANCE.NS' && app.req.interval === '5m' && !app.loading && app.currentBars.length > 0;
  });
  // The fixture server's session, 09:15 to 15:30 IST on weekdays, walked here
  // independently of the library: the target is the third bar of the session
  // after the one the last candle is in, whatever time of day the run is.
  const plan = await page.evaluate(() => {
    const chart = (window as any).__oac.app.chart;
    const IST = 19800, OPEN = 9 * 3600 + 15 * 60, CLOSE = 15 * 3600 + 30 * 60;
    const open = (t: number) => {
      const local = t + IST, day = Math.floor(local / 86400), weekday = (day + 4) % 7, second = local - day * 86400;
      return weekday >= 1 && weekday <= 5 && second >= OPEN && second < CLOSE;
    };
    const last = chart.dataLayer.length - 1, lastTime = chart.dataLayer.indexToTime(last);
    const slots: number[] = [];
    let crossed = -1;
    for (let t = lastTime + 300; slots.length < crossed + 3 || crossed < 0; t += 300) {
      if (!open(t)) continue;
      if (crossed < 0 && t - (slots.at(-1) ?? lastTime) > 300) crossed = slots.length;
      slots.push(t);
    }
    const k = slots.length;
    chart.setVisibleLogicalRange({ from: last - 30, to: last + k + 12 });
    const left = chart.timeToCoordinate(lastTime) - chart.timeScale.indexToX(last);
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    const close = chart.primaryBars().at(-1).close;
    return {
      last, k, expected: slots[k - 1], left, plotRight: left + chart.timeScale.width,
      from: { x: rect.left + left + chart.timeScale.indexToX(last - 10), y: rect.top + chart.priceToCoordinate(close * 1.002, 0) },
      to: { x: rect.left + left + chart.timeScale.indexToX(last + k), y: rect.top + chart.priceToCoordinate(close * 0.998, 0) },
    };
  });
  await page.evaluate(() => (window as any).__oac.app.draw.setTool('trend-line'));
  await page.mouse.click(plan.from.x, plan.from.y);
  await page.mouse.move(plan.to.x, plan.to.y, { steps: 10 });
  await page.mouse.click(plan.to.x, plan.to.y);
  const drawn = await page.evaluate(() => {
    const { app } = (window as any).__oac;
    const drawing = app.draw.drawings().at(-1);
    app.draw.update(drawing.id, { style: { ...drawing.style, color: '#ff00ff', lineWidth: 4 } });
    app.draw.select(null);
    return { time: drawing.points[1].time as number, last: app.chart.dataLayer.length - 1 };
  });
  // Placed on the next session's third bar: not in the night, not on a weekend.
  expect(drawn.last).toBe(plan.last);
  expect(Math.abs(drawn.time - plan.expected)).toBeLessThan(60);
  const box = await page.locator('#chart').boundingBox();
  if (!box) throw new Error('Chart is not visible');
  await page.mouse.move(box.x + 5, box.y + 5);
  const ink = async () => page.locator('#chart canvas').nth(1).evaluate((element, bounds) => {
    const c = element as HTMLCanvasElement;
    const chart = (window as any).__oac.app.chart;
    const dpr = c.width / c.getBoundingClientRect().width;
    const future = (bounds.left + chart.timeScale.indexToX(bounds.last) + 6) * dpr, right = bounds.plotRight * dpr;
    const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let plot = 0, axis = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 120 || data[i] < 180 || data[i + 1] > 90 || data[i + 2] < 180) continue;
      const x = (i / 4) % c.width;
      if (x >= right) axis++;
      else if (x >= future) plot++;
    }
    return { plot, axis };
  }, { left: plan.left, last: plan.last, plotRight: plan.plotRight });
  await expect.poll(async () => (await ink()).plot).toBeGreaterThan(40);
  expect((await ink()).axis).toBe(0);
  await page.screenshot({ path: info.outputPath('host-intraday-future.png') });
  expect(errors).toEqual([]);
});
